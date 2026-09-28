"""Turn a ``RecurringTemplate`` into a real Bill or Expense.

Phase 1 exposes this through the template "Use" action, dispatched on
``txn_type``:

* **Bill** — built and posted via :class:`MigrationBillCreateService` (money
  owed: posts to A/P, inventory, tax, and the journal like a manual bill).
* **Expense** — built and posted via :class:`MigrationExpenseCreateService`
  (money already paid: posts directly against the template's payment account,
  never touches A/P, has no due date).

Both are the one programmatic creation path for their transaction type, and the
generated bill/expense is linked back to its template via
``Purchase.source_template`` so run history is queryable.

Schedule advancement and the ``RecurringOccurrence`` idempotency ledger belong to
the background Generation Job (Phase 2); on-demand "Use" deliberately does not
touch them, so repeated same-day use never trips the ``unique(template,
occurrence_date)`` guard and already-generated transactions stay untouched (spec
sections 9.4, 10.4).
"""

import logging
import os
import re
from types import SimpleNamespace
from datetime import date as date_type, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from termio.choicess import TermKindChoices
from termio.models import TermConnector

from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices
from addressio.models import Address, AddressConnector

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from currencyio.models import Currency
from purchaseio.choices import PurchaseStatus
from purchaseio.models import ExpenseConnector, Purchase

# Resolved by system_key inside get_chart_of_account; the title is the lookup
# label, not what the account must be called.
AR_TITLE = "Accounts Receivable (A/R)"

from datamigrationio.django_rest.services.bill_importer import (
    MigrationBillCreateService,
)
from datamigrationio.django_rest.services.check_importer import (
    MigrationCheckCreateService,
)
from datamigrationio.django_rest.services.estimate_importer import (
    MigrationEstimateCreateService,
)
from datamigrationio.django_rest.services.expense_importer import (
    MigrationExpenseCreateService,
)
from datamigrationio.django_rest.services.invoice_importer import (
    MigrationInvoiceCreateService,
)
from datamigrationio.django_rest.services.sales_receipt_importer import (
    MigrationSaleReceiptCreateService,
)

from ..choices import (
    RecurringAcceptanceStatusChoices,
    RecurringLineTypeChoices,
    RecurringWhenToChargeChoices,
)
from .totals import INCLUSIVE, line_tax_amount

logger = logging.getLogger(__name__)


def _synthetic_request(user):
    """A stand-in request for driving a DRF serializer outside a view.

    Two generators (deposit, refund receipt) reuse the serializer the manual
    screen uses, rather than reimplementing its ledger work. Those serializers
    read ``request.user`` and, on the email path, ``request.get_host()`` — so a
    scheduled firing has to supply both. The host comes from settings because an
    unattended run has no inbound request to read it from.
    """
    host = (
        getattr(settings, "BASE_BACKEND_URL", None)
        or os.environ.get("BASE_BACKEND_URL")
        or "localhost:8000"
    )
    return SimpleNamespace(user=user, get_host=lambda: str(host).rstrip("/"))


def _map_lines(lines, tax_kind=None):
    """Map template lines to importer line dicts; return (subtotal, tax, lines).

    The line shape is identical for bills and expenses (line_kind PRODUCT/EXPENSE
    with the matching product/account, qty, rate, total, tax).
    """
    subtotal = Decimal("0")
    total_tax = Decimal("0")
    mapped = []

    for line in lines:
        amount = Decimal(str(line.amount or "0"))
        line_tax = line_tax_amount(line, tax_kind)
        total_tax += line_tax
        # Under INCLUSIVE the tax is already inside `amount`, so back it out --
        # and back it out of the LINE as well as the subtotal.
        #
        # These disagreed: the subtotal went net while each line's `total`
        # stayed gross. The importer debits the line totals and credits the
        # subtotal plus tax, so the debit side carried the tax twice and the
        # entry came out long by exactly it. On a 550 gross line at 10% the
        # debits were 550 + 50 against a 500 credit.
        #
        # One value now feeds both, so the two cannot drift apart again.
        line_net = amount - line_tax if tax_kind == INCLUSIVE else amount
        subtotal += line_net

        if line.line_type == RecurringLineTypeChoices.ITEM:
            mapped.append(
                {
                    "line_kind": "PRODUCT",
                    "product": line.product,
                    "quantity": line.quantity or 1,
                    "purchase_price": line.rate or line.amount,
                    "total": line_net,
                    "description": line.description or "",
                    "tax": line.tax,
                }
            )
        else:  # CATEGORY -> account-based line
            mapped.append(
                {
                    "line_kind": "EXPENSE",
                    "expense_account": line.charter_account,
                    "total": line_net,
                    "description": line.description or "",
                    "tax": line.tax,
                }
            )

    return subtotal, total_tax, mapped


def _build_bill_group(template, lines, *, bill_date, due_date):
    """Assemble the ``bill_group`` dict MigrationBillCreateService expects."""
    total, total_tax, bill_lines = _map_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    return {
        "supplier": template.supplier,
        "tax_kind": template.tax_kind,
        "bill_number": "",  # assigned by the standard bill-numbering sequence
        "bill_date": bill_date,
        "due_date": due_date,
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "full_billing_address": template.mailing_address or "",
        "memo": template.memo or "",
        "total": total,
        "total_tax": total_tax,
        "warehouse": template.warehouse,
        "lines": bill_lines,
    }


def _build_expense_group(template, lines, *, expense_date):
    """Assemble the ``expense_group`` dict MigrationExpenseCreateService expects.

    Currency is resolved from the payee at fire time, not frozen at template
    creation — a hardcoded rate of 1 is worse than a display bug here, because
    the importer does ``Currency.objects.get_or_create(kind=…, exchange_rate=…)``
    and would mint a bogus ``EUR @ 1.0`` row for the company.
    """
    total, total_tax, expense_lines = _map_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    return {
        "supplier": template.supplier,
        "payment_account": template.payment_account,
        "payment_method": template.payment_method,
        "expense_date": expense_date,
        "tax_kind": template.tax_kind,
        "reference_number": "",  # assigned by the standard sequence
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "description": template.memo or "",
        "memo": template.memo or "",
        "total": total,
        "total_tax": total_tax,
        # An expense is money already paid, not money owed: it settles in full
        # the moment it is recorded. Leaving both at zero left the record saying
        # neither paid nor outstanding, which reconciles as neither.
        "deposit": total + total_tax,
        "due_total": Decimal("0"),
        "lines": expense_lines,
    }


# A cheque number is "<anything><digits>" — the trailing digits are the counter.
_CHEQUE_SEED_RE = re.compile(r"^(?P<prefix>.*?)(?P<digits>\d+)$")


def next_cheque_number(template):
    """Next unused cheque number for the template's bank account.

    The template's ``cheque_number`` is a **seed, not a literal** — twelve
    monthly cheques cannot all be ``CHQ-004182``, and nothing on this write path
    enforces uniqueness, so copying it verbatim silently issues duplicates
    against one bank account and corrupts reconciliation.

    Advances the trailing digits (preserving prefix and zero-padding) and skips
    numbers already issued on that bank account — a cheque book belongs to an
    account, not to a template. Returns ``""`` when the cheque should be left
    unnumbered for the print queue: ``print_later`` is set, no seed was given,
    or the seed has no numeric tail to advance.

    The template's own seed is never mutated, so the edit screen keeps showing
    what the user actually typed.
    """
    if template.print_later:
        return ""

    seed = (template.cheque_number or "").strip()
    if not seed:
        return ""

    match = _CHEQUE_SEED_RE.match(seed)
    if match is None:
        # e.g. "DRAFT" — nothing to increment. Queue it for printing rather
        # than issue the same number on every occurrence.
        logger.warning(
            "Recurring cheque template %s has a seed with no numeric tail (%r); "
            "leaving the cheque unnumbered for the print queue.",
            template.uid,
            seed,
        )
        return ""

    prefix = match.group("prefix")
    width = len(match.group("digits"))
    number = int(match.group("digits"))

    used = set(
        Purchase.objects.filter(
            company=template.company,
            charter_account=template.payment_account,
            is_cheque=True,
        )
        .exclude(cheque_number__isnull=True)
        .exclude(cheque_number="")
        .values_list("cheque_number", flat=True)
    )

    candidate = f"{prefix}{number:0{width}d}"
    while candidate in used:
        number += 1
        candidate = f"{prefix}{number:0{width}d}"
    return candidate


def _party_currency(template):
    """``(currency_kind, currency_rate)`` resolved at fire time.

    The rate is read from the company's currency table **now** rather than
    frozen when the template was created, so a long-running monthly template
    posts at the current rate. Falls back to the template's own code, then to
    1.0 when the company has no matching currency row.

    Hardcoding the rate to 1 is worse than a display bug: every importer does
    ``Currency.objects.get_or_create(kind=…, exchange_rate=…)``, so a EUR
    document would mint a bogus ``EUR @ 1.0`` row for the company.

    The party is the supplier on money-out types and the customer on
    sales-side ones (estimate / refund receipt).
    """
    party = template.supplier or template.customer
    kind = (
        getattr(party, "currency", None)
        or template.currency_code
        or getattr(template.company, "currency", "USD")
    )

    rate = (
        Currency.objects.filter(company=template.company, kind=kind)
        .values_list("exchange_rate", flat=True)
        .first()
    )
    return kind, Decimal(str(rate)) if rate is not None else Decimal("1")


def _build_check_group(template, lines, *, check_date):
    """Assemble the ``check_group`` dict MigrationCheckCreateService expects.

    The bank account is the template's ``payment_account``. The cheque number is
    assigned per occurrence from the template's seed (see
    :func:`next_cheque_number`); currency is resolved from the payee at fire
    time. The payee email is handled downstream by the create service, which
    reads ``supplier.email`` when ``send_email`` is set.
    """
    total, total_tax, check_lines = _map_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    return {
        "supplier": template.supplier,
        "tax_kind": template.tax_kind,
        "check_number": next_cheque_number(template),
        "check_date": check_date,
        "bank_account": template.payment_account,
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "full_billing_address": template.mailing_address or "",
        "memo": template.memo or "",
        "total": total,
        "total_tax": total_tax,
        "warehouse": template.warehouse,
        "lines": check_lines,
    }


def _map_estimate_lines(lines, tax_kind=None):
    """Map template lines to estimate (sales) line dicts; return (subtotal, tax, lines).

    Sales lines use a different shape from purchases: a product/service with a
    ``sale_price`` (ITEM), or an income account (CATEGORY). Estimates are
    non-posting, so the account is informational.
    """
    subtotal = Decimal("0")
    total_tax = Decimal("0")
    mapped = []

    for line in lines:
        amount = Decimal(str(line.amount or "0"))
        line_tax = line_tax_amount(line, tax_kind)
        total_tax += line_tax
        subtotal += amount - line_tax if tax_kind == INCLUSIVE else amount

        if line.line_type == RecurringLineTypeChoices.ITEM:
            mapped.append(
                {
                    "product": line.product,
                    "income_account": None,
                    "quantity": line.quantity or 1,
                    "sale_price": line.rate or line.amount,
                    "total": amount,
                    "description": line.description or "",
                    "tax": line.tax,
                    "is_tax": bool(line.tax),
                }
            )
        else:  # CATEGORY -> income-account line (non-posting)
            mapped.append(
                {
                    "product": None,
                    "income_account": line.charter_account,
                    "quantity": 1,
                    "sale_price": amount,
                    "total": amount,
                    "description": line.description or "",
                    "tax": line.tax,
                    "is_tax": bool(line.tax),
                }
            )

    return subtotal, total_tax, mapped


def _build_estimate_group(template, lines, *, estimate_date):
    """Assemble the ``estimate_group`` dict MigrationEstimateCreateService expects.

    An estimate is non-posting and customer-facing: no terms, no due date, no
    posting accounts. ``mailing_address`` doubles as the billing address.

    Expiry is stored on the template as a **duration** (``expiry_days``) rather
    than an absolute date, because a fixed date is meaningless on a template
    that fires for years; each occurrence expires that many days after its own
    date. Left null when the template sets none.
    """
    subtotal, total_tax, estimate_lines = _map_estimate_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    expiry_date = (
        estimate_date + timedelta(days=template.expiry_days)
        if template.expiry_days
        else None
    )
    return {
        "customer": template.customer,
        "tax_kind": template.tax_kind,
        "estimate_number": "",  # assigned by the standard EST sequence
        "estimate_date": estimate_date,
        "expiry_date": expiry_date,
        "warehouse": template.warehouse,
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "full_billing_address": template.mailing_address or "",
        "full_shipping_address": "",
        "shipping_by": None,
        "shipping_date": None,
        "term": None,  # estimates carry no terms (non-posting)
        "memo": template.memo or "",
        "total": subtotal,
        "total_tax": total_tax,
        "lines": estimate_lines,
    }


def _due_date_from_terms(template, bill_date):
    """Bill date + the term's net days, or ``None`` when no term is set."""
    if not template.terms:
        return None
    try:
        return bill_date + timedelta(days=int(template.terms.days or 0))
    except (TypeError, ValueError):
        return None


@transaction.atomic
def generate_bill_from_template(template, user, company, *, bill_date=None, send_email=False):
    """Create and return a real Bill (``Purchase``) from ``template``.

    ``bill_date`` defaults to today; the due date is derived from the template's
    terms. The bill is linked back to the template via ``source_template``.
    """
    bill_date = bill_date or date_type.today()
    due_date = _due_date_from_terms(template, bill_date)

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a bill from a template with no lines.")

    bill_group = _build_bill_group(
        template, lines, bill_date=bill_date, due_date=due_date
    )

    purchase = MigrationBillCreateService.create_bill(
        bill_group,
        user,
        company,
        options={"send_email": send_email, "source": "recurring_template"},
    )

    # Link the bill back to its template (run-history / audit trail).
    purchase.source_template = template
    purchase.save(update_fields=["source_template", "updated_at"])

    # Mirror the terms onto the bill so A/P aging and the terms display match a
    # manually-entered bill.
    if template.terms:
        TermConnector.objects.create(
            kind=TermKindChoices.PURCHASE,
            purchase=purchase,
            term=template.terms,
        )

    return purchase


@transaction.atomic
def generate_expense_from_template(template, user, company, *, expense_date=None, send_email=False):
    """Create and return a real Expense from ``template``.

    The expense posts immediately against ``template.payment_account`` (no A/P,
    no due date). The backing ``Purchase`` is linked to the template via
    ``source_template``. Returns the ``Expense`` instance.
    """
    if template.payment_account is None:
        raise ValueError("A recurring expense needs a payment account.")

    expense_date = expense_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate an expense from a template with no lines.")

    expense_group = _build_expense_group(template, lines, expense_date=expense_date)

    expense = MigrationExpenseCreateService.create_expense(
        expense_group,
        user,
        company,
        options={"send_email": send_email, "source": "recurring_template"},
    )

    # Link the backing purchase back to its template (run-history / audit trail).
    connector = ExpenseConnector.objects.filter(expense=expense).first()
    if connector and connector.purchase:
        connector.purchase.source_template = template
        connector.purchase.save(update_fields=["source_template", "updated_at"])

    return expense


@transaction.atomic
def generate_cheque_from_template(template, user, company, *, cheque_date=None, send_email=False):
    """Create and return a real cheque (``Purchase`` with ``is_cheque=True``).

    The cheque is drawn on ``template.payment_account`` (a bank account); the
    bank register updates immediately. Linked back via ``source_template``.
    """
    if template.payment_account is None:
        raise ValueError("A recurring cheque needs a bank account.")

    cheque_date = cheque_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a cheque from a template with no lines.")

    check_group = _build_check_group(template, lines, check_date=cheque_date)

    purchase = MigrationCheckCreateService.create_check(
        check_group,
        user,
        company,
        options={"send_email": send_email, "source": "recurring_template"},
    )

    purchase.source_template = template
    purchase.save(update_fields=["source_template", "updated_at"])

    return purchase


@transaction.atomic
def generate_estimate_from_template(template, user, company, *, estimate_date=None, send_email=False):
    """Create and return a real Estimate (a non-posting ``Sale``) from ``template``.

    An estimate is a customer-facing quote: it writes no journal entry and does
    not touch inventory, A/R, income, or tax (those post only if it is later
    converted to an invoice). Linked back via ``Sale.source_template``.
    """
    if template.customer is None:
        raise ValueError("A recurring estimate needs a customer.")

    estimate_date = estimate_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate an estimate from a template with no lines.")

    estimate_group = _build_estimate_group(template, lines, estimate_date=estimate_date)

    sale = MigrationEstimateCreateService.create_estimate(
        estimate_group,
        user,
        company,
        options={
            # The template's own "email it automatically" switch counts as well
            # as the caller's flag -- an unattended firing has no caller to set
            # one, which is exactly when auto_email is meant to apply.
            "send_email": bool(send_email or template.auto_email),
            "source": "recurring_template",
        },
    )

    sale.source_template = template
    sale.save(update_fields=["source_template", "updated_at"])

    return sale


def _build_receipt_group(template, lines, *, receipt_date):
    """Assemble the ``receipt_group`` MigrationSaleReceiptCreateService expects.

    A PAYMENT template materializes a **sales receipt** — a cash sale charged to
    a stored payment method — not a "payment received". There is no open invoice
    to apply cash against at template-creation time, and the screen collects
    product lines, which a payment-received has none of (spec §3).

    The service settles it in full itself (``deposit = total + tax``,
    ``due_total = 0``), which is correct for a receipt: the money is taken as it
    is recorded.
    """
    subtotal, total_tax, receipt_lines = _map_estimate_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    return {
        "customer": template.customer,
        "tax_kind": template.tax_kind,
        "receipt_number": "",  # assigned by the standard SR sequence
        "receipt_date": receipt_date,
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "full_billing_address": template.mailing_address or "",
        "full_shipping_address": "",
        "shipping_by": None,
        "shipping_date": None,
        "term": None,  # a receipt is settled on the spot, so it carries no terms
        "memo": template.memo or "",
        "total": subtotal,
        "total_tax": total_tax,
        "deposit_account": template.payment_account,  # wire name: deposit_to
        "warehouse": template.warehouse,
        "lines": receipt_lines,
    }


@transaction.atomic
def generate_sales_receipt_from_template(
    template, user, company, *, receipt_date=None, send_email=False
):
    """Create and return the ``Sale`` a SALES_RECEIPT template produces.

    A sales receipt is a cash sale paid in full on the fire date. This is the
    SAME document a PAYMENT template produces (spec section 12.1) -- the two
    types are kept separate because their screens collect different inputs, not
    because the output differs, so they deliberately share one code path.
    """
    if template.payment_account is None:
        raise ValueError("A recurring sales receipt needs a deposit account.")

    receipt_date = receipt_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError(
            "Cannot generate a sales receipt from a template with no lines."
        )

    receipt_group = _build_receipt_group(template, lines, receipt_date=receipt_date)

    sale = MigrationSaleReceiptCreateService.create_receipt(
        receipt_group,
        user,
        company,
        options={
            "send_email": bool(send_email or template.auto_email),
            "source": "recurring_template",
        },
    )

    sale.source_template = template
    sale.save(update_fields=["source_template", "updated_at"])

    return sale


@transaction.atomic
def generate_payment_from_template(template, user, company, *, receipt_date=None, send_email=False):
    """Create and return the ``Sale`` a PAYMENT template produces.

    Charging a customer who never accepted is exactly what ``when_to_charge =
    ACCEPT`` exists to prevent, so an unaccepted template refuses to fire rather
    than falling through to a charge.
    """
    if template.when_to_charge == RecurringWhenToChargeChoices.ACCEPT and (
        template.acceptance_status != RecurringAcceptanceStatusChoices.ACCEPTED
    ):
        raise ValueError(
            "This payment template charges only once the customer accepts, and "
            "no acceptance has been recorded."
        )

    if template.payment_account is None:
        raise ValueError("A recurring payment needs an account to deposit into.")

    receipt_date = receipt_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a payment from a template with no lines.")

    receipt_group = _build_receipt_group(template, lines, receipt_date=receipt_date)

    sale = MigrationSaleReceiptCreateService.create_receipt(
        receipt_group,
        user,
        company,
        options={
            "send_email": bool(send_email or template.auto_email),
            "source": "recurring_template",
        },
    )

    sale.source_template = template
    sale.save(update_fields=["source_template", "updated_at"])

    return sale


def _build_invoice_group(template, lines, company, *, invoice_date, due_date):
    """Assemble the ``invoice_group`` MigrationInvoiceCreateService expects.

    ``total`` follows the importer convention (ex-tax: subtotal + shipping −
    discount, with ``total_tax`` separate); ``due_total`` is what lands on A/R —
    the tax-inclusive document total minus the deposit. Tax is applied to line
    amounts before discount and shipping, matching the client's own arithmetic.
    """
    subtotal, total_tax, invoice_lines = _map_estimate_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)
    discount = template.discount or Decimal("0")
    shipping = template.shipping_fee or Decimal("0")
    deposit = template.deposit or Decimal("0")
    total = subtotal + shipping - discount
    return {
        "customer": template.customer,
        # Required, not cosmetic: the sale serializer reads is_invoice off
        # validated_data to decide whether to post the receivable side of the
        # journal (`is_invoice == True or is_sale_receipt == True`). Without it
        # the invoice is created and its income and inventory legs post, but the
        # accounts-receivable debit never does -- the entry is short by the
        # whole invoice total. The receipt builder sets its own flag for the
        # same reason.
        "is_invoice": True,
        "invoice_number": "",  # assigned by the standard INV sequence
        "invoice_date": invoice_date,
        "due_date": due_date,
        "tax_kind": template.tax_kind,
        "currency_kind": currency_kind,
        "currency_rate": currency_rate,
        "full_billing_address": template.mailing_address or "",
        "full_shipping_address": "",
        "shipping_by": None,
        "shipping_date": None,
        "term": template.terms,
        "warehouse": template.warehouse,
        "memo": template.memo or "",
        "total": total,
        "total_tax": total_tax,
        "discount": discount,
        "discount_kind": template.discount_kind,
        "shipping_fee": shipping,
        "deposit": deposit,
        "due_total": total + total_tax - deposit,
        # The DEBIT destination for due_total -- Accounts Receivable for an
        # ordinary invoice, or Undeposited Funds when the invoice is banked on
        # the spot (the importer compares the two to set `is_deposit`).
        #
        # This used to pass `template.payment_account`, read as "where the
        # deposit gets booked". That is a different account: the model calls it
        # "the account money is paid FROM ... required for EXPENSE and CHEQUE,
        # unused for BILL", and an invoice template has no reason to carry one.
        # It arrived as None, and `invoice_importer.py:323` guards the entire
        # A/R leg behind `if receivable_account:` -- so the invoice posted its
        # income and inventory legs and no receivable at all, leaving the entry
        # short by the whole invoice total. Production ran that nightly from a
        # beat schedule for weeks, unbalanced by 550.00 every time, and nothing
        # reported it: the balance check added with R5 lives on
        # `post_sale_document`, which this path does not use.
        "receivable_account": receivable_account_for(template, company),
        "lines": invoice_lines,
    }


def receivable_account_for(template, company):
    """The account an invoice's `due_total` is debited to.

    Resolved by `system_key`, so a tenant that renamed its A/R account still
    posts correctly -- resolving control accounts by title is R1, the root cause
    the `system_key` spine exists to close, and the CSV importer still does it
    by title at `invoice_importer.py:464`.

    A template that does name an account keeps it, which is what makes the
    importer's Undeposited-Funds branch reachable from here.
    """
    if template.payment_account is not None:
        return template.payment_account
    return get_chart_of_account([AR_TITLE], company).get(AR_TITLE)


@transaction.atomic
def generate_invoice_from_template(template, user, company, *, invoice_date=None, send_email=False):
    """Create and return the ``Sale`` (``is_invoice=True``) a template produces.

    The due date is derived from the template's terms at fire time — each
    occurrence gets ``invoice_date + term.days``, falling back to the invoice
    date itself when no terms are set (due on receipt).
    """
    invoice_date = invoice_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate an invoice from a template with no lines.")

    if template.include_unbilled_charges:
        # Persisted but deliberately a no-op in v1: nothing in the product can
        # query a customer's open billable charges yet. Logged so a firing that
        # someone expected to sweep charges is explainable.
        logger.info(
            "Recurring template %s has include_unbilled_charges set; that is "
            "not implemented yet and the invoice carries only the template's "
            "own lines.",
            template.uid,
        )

    due_date = _due_date_from_terms(template, invoice_date) or invoice_date

    invoice_group = _build_invoice_group(
        template, lines, company, invoice_date=invoice_date, due_date=due_date
    )

    sale = MigrationInvoiceCreateService.create_invoice(
        invoice_group,
        user,
        company,
        options={
            "send_email": bool(send_email or template.auto_email),
            "source": "recurring_template",
        },
    )

    sale.source_template = template
    sale.save(update_fields=["source_template", "updated_at"])

    return sale


@transaction.atomic
def generate_purchase_order_from_template(
    template, user, company, *, order_date=None, send_email=False
):
    """Create and return the ``Purchase`` (``is_bill=False``) a PO template makes.

    A purchase order is the same record as a bill behind one flag, so it reuses
    the bill builder — but it is a **commitment to buy, not a liability**. The
    live endpoint gates A/P, inventory, account balances and the journal on
    ``is_bill``, so this posts none of them (``posting=False``). Flipping only
    the flag, as the spec suggests, would credit A/P and move stock as though
    the goods had already arrived.

    ``status`` is OPEN and there is no due date: nothing is owed until the order
    is received and billed.
    """
    order_date = order_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError(
            "Cannot generate a purchase order from a template with no lines."
        )

    order_group = _build_bill_group(
        template, lines, bill_date=order_date, due_date=None
    )
    order_group.update({"is_bill": False, "status": PurchaseStatus.OPEN})

    purchase = MigrationBillCreateService.create_bill(
        order_group,
        user,
        company,
        options={
            "send_email": send_email,
            "source": "recurring_template",
            "posting": False,
        },
    )

    # Shipping is not a Purchase column: it is a second Address flagged
    # is_shipping, carrying the carrier and ship date, linked by an
    # AddressConnector — the same shape the live endpoint writes.
    if template.full_shipping_address or template.shipping_by:
        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=template.full_shipping_address or "",
                is_shipping=True,
                shipping_by=template.shipping_by or "",
                # No ship-lag field exists, so goods are expected on the order
                # date; a template cannot carry an absolute ship date.
                shipping_date=order_date,
                company=company,
                status=AddressStatusChoices.ACTIVE,
            ),
            purchase=purchase,
            kind=AddressConnectorKindCoices.PURCHASE,
        )

    purchase.source_template = template
    purchase.save(update_fields=["source_template", "updated_at"])

    return purchase


@transaction.atomic
def generate_deposit_from_template(
    template, user, company, *, deposit_date=None, send_email=False
):
    """Create and return the ``BankDeposit`` a DEPOSIT template produces.

    A bank deposit has no standalone create service — the only path that posts
    it correctly is the DRF serializer the manual screen uses, and it carries
    ~200 lines of balance and journal work. Rather than mirror that (and let the
    copy drift), this drives the real serializer with a synthetic context: it
    only needs ``context["request"].user``, so a recurring deposit posts to the
    ledger identically to a hand-entered one, by construction.

    **Undeposited funds are not swept.** The real screen's headline feature is
    ticking open undeposited-fund journal entries into the deposit, but those
    entries do not exist when the template is authored, so a fired occurrence
    generates exactly the template's own fund lines (spec §7.3, option a).
    """
    from weapi.django_rest.serializers.transactions.bank_deposits import (
        PrivateWeBankDepositListCreateSerializer,
    )

    if template.payment_account is None:
        raise ValueError("A recurring deposit needs a bank account.")

    deposit_date = deposit_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a deposit from a template with no lines.")

    # deposit_items is a JSONField, so every value has to be JSON-native --
    # dates and Decimals must be strings, not Python objects.
    deposit_items = [
        {
            "date": deposit_date.isoformat(),
            "description": line.description or "",
            "reference_number": line.reference_number or "",
            # Empty for manually-added fund rows; only swept undeposited rows
            # carry a journal kind, and this path never sweeps.
            "type": "",
            "amount": str(line.amount or 0),
            "payment_method_uid": (
                str(line.payment_method.uid) if line.payment_method else ""
            ),
            "received_from_account_uid": (
                str(line.charter_account.uid) if line.charter_account else ""
            ),
            "customer_uid": str(line.customer.uid) if line.customer else "",
            "supplier_uid": str(line.supplier.uid) if line.supplier else "",
        }
        for line in lines
    ]

    payload = {
        "date": deposit_date.isoformat(),
        "bank_chart_of_account_uid": str(template.payment_account.uid),
        "description": template.memo or "",
        "cash_back_amount": str(template.cash_back_amount or 0),
        "cash_back_memo": template.cash_back_memo or "",
        "deposit_items": deposit_items,
    }
    if template.cash_back_account:
        payload["cash_back_account_uid"] = str(template.cash_back_account.uid)

    serializer = PrivateWeBankDepositListCreateSerializer(
        data=payload,
        context={"request": _synthetic_request(user)},
    )
    serializer.is_valid(raise_exception=True)
    deposit = serializer.save()

    return deposit


@transaction.atomic
def generate_refund_receipt_from_template(
    template, user, company, *, refund_date=None, send_email=False
):
    """Create and return the ``Sale`` (``kind=REFUND``) a template produces.

    A refund pays real money **out** of a bank or credit-card account, so the
    spec is emphatic that the generated occurrence must post exactly as the live
    refund screen does and must not open a second GL path. It therefore drives
    the same serializer the manual screen uses, rather than reimplementing the
    refund-side inventory and journal work.

    The account the money leaves is the template's ``payment_account`` (wire
    name ``refund_from``), which reaches the sale as
    ``payable_charter_account_uid`` — the opposite direction from a receipt's
    ``receivable_charter_account_uid``.
    """
    from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer

    if user is None:
        # The serializer reads user.get_employee() directly, and a refund moves
        # money -- fail clearly rather than with an opaque AttributeError.
        raise ValueError(
            "A recurring refund needs a user to attribute the transaction to; "
            "the template has no creator on record."
        )
    if template.payment_account is None:
        raise ValueError("A recurring refund needs an account to refund from.")
    if template.customer is None:
        raise ValueError("A recurring refund needs a customer.")

    refund_date = refund_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a refund from a template with no lines.")

    subtotal, total_tax, _ = _map_estimate_lines(lines, template.tax_kind)
    total = subtotal + total_tax

    sales_items = [
        {
            "product_uid": str(line.product.uid) if line.product else "",
            # The refund path does int(quantity), so a Decimal's "2.0000"
            # blows up. Refunds are whole units on that path either way.
            "quantity": str(int(Decimal(str(line.quantity or 0)))),
            "sale_price": str(line.rate or 0),
            "total": str(Decimal(str(line.rate or 0)) * Decimal(str(line.quantity or 0))),
            "is_item_tax": bool(line.tax),
            "tax_uid": str(line.tax.uid) if line.tax else "",
            "description": line.description or "",
            "note": "",
            "section": "",
        }
        for line in lines
    ]

    # No template carries a currency; resolve it from the customer at fire time
    # so a long-running template posts at the current rate (spec section 12.10).
    currency_kind, currency_rate = _party_currency(template)

    payload = {
        "date": refund_date.isoformat(),
        "kind": "REFUND",
        "status": "OPEN",
        "is_sale_receipt": True,
        "customer_uid": str(template.customer.uid),
        "currency_kind": currency_kind,
        "currency_rate": str(currency_rate),
        "payable_charter_account_uid": str(template.payment_account.uid),
        "reference_number": template.reference_number or "",
        # Sent for completeness, but the sales path assigns its own receipt
        # number and wins -- which is right: twelve occurrences cannot share
        # one document number.
        "tracking_number": template.tracking_number or "",
        "description": template.memo or template.message_on_estimate or "",
        "tax_kind": template.tax_kind or "NO_TAX",
        "total": str(total),
        "total_tax": str(total_tax),
        # A refund receipt is settled in full when it is recorded.
        "deposit": str(total),
        # No template source for these; the live screen's own defaults.
        "discount_kind": "PERCENTAGE",
        "discount": "0",
        "shipping_fee": "0",
        "sales_items": sales_items,
        "email": {
            "customer_email": template.email_to or "",
            "cc_emails": template.email_cc or "",
            "bcc_emails": template.email_bcc or "",
        },
    }
    if template.mailing_address:
        payload["full_billing_address"] = template.mailing_address
    if template.warehouse:
        payload["warehouse_uid"] = str(template.warehouse.uid)
    if template.payment_method:
        payload["payment_method_uid"] = str(template.payment_method.uid)
    if template.tax:
        payload["tax_uid"] = str(template.tax.uid)

    serializer = PrivateWeSaleListSerializer(
        data=payload,
        context={"request": _synthetic_request(user)},
    )
    serializer.is_valid(raise_exception=True)
    sale = serializer.save()

    sale.source_template = template
    sale.save(update_fields=["source_template", "updated_at"])

    return sale


@transaction.atomic
def generate_credit_memo_from_template(
    template, user, company, *, memo_date=None, send_email=False
):
    """Create and return the ``CreditNote`` a CREDIT_MEMO template produces.

    A credit note reduces the customer's balance. Amounts are stored **positive**
    with a negative ledger effect — the manual screen does the same and renders
    ``money(-total)`` — so nothing is negated on the way in (spec §12 Q1).

    ``credit_note_number`` is minted from the same per-company sequence manual
    credit notes use, so recurring and hand-entered notes share one numbering
    series rather than colliding -- and twelve occurrences cannot reuse one
    number. The serializer requires the field, so it is generated here rather
    than left to its fallback.
    """
    from common.django_rest.helpers.id_generator import get_unique_id
    from creditnoteio.models import CreditNote
    from weapi.django_rest.serializers.creditnotes import (
        PrivateWeCreditNoteListSerializer,
    )

    if user is None:
        raise ValueError(
            "A recurring credit memo needs a user to attribute the note to; "
            "the template has no creator on record."
        )
    if template.customer is None:
        raise ValueError("A recurring credit memo needs a customer.")
    if template.warehouse is None:
        # we/credit-notes hard-fails without one.
        raise ValueError("A recurring credit memo needs a store.")

    memo_date = memo_date or date_type.today()

    lines = list(template.lines.all())
    if not lines:
        raise ValueError("Cannot generate a credit memo from a template with no lines.")

    subtotal, total_tax, _ = _map_estimate_lines(lines, template.tax_kind)
    currency_kind, currency_rate = _party_currency(template)

    credit_note_items = [
        {
            "product_uid": str(line.product.uid) if line.product else "",
            # Same as the refund path: the endpoint does int(quantity), which a
            # Decimal's "2.0000" breaks.
            "quantity": str(int(Decimal(str(line.quantity or 0)))),
            # The unit price is called item_credit downstream.
            "item_credit": str(line.rate or 0),
            "total": str(
                Decimal(str(line.rate or 0)) * Decimal(str(line.quantity or 0))
            ),
            "is_item_tax": bool(line.tax),
            "tax_uid": str(line.tax.uid) if line.tax else "",
            "description": line.description or "",
            "note": "",
            "section": "",
        }
        for line in lines
    ]

    credit_note_number = get_unique_id(
        CreditNote, company.id, "credit_note_number", "CN"
    )
    payload = {
        "date": memo_date.isoformat(),
        "credit_note_number": credit_note_number,
        "kind": "SALE",
        "status": "OPEN",
        "customer_uid": str(template.customer.uid),
        "warehouse_uid": str(template.warehouse.uid),
        "currency_kind": currency_kind,
        "currency_rate": str(currency_rate),
        "tax_kind": template.tax_kind or "NO_TAX",
        "description": template.memo or template.message_on_estimate or "",
        "total": str(subtotal + total_tax),
        "total_tax": str(total_tax),
        "credit_note_items": credit_note_items,
        "email": {
            "customer_email": template.email_to or "",
            "cc_emails": template.email_cc or "",
            "bcc_emails": template.email_bcc or "",
        },
    }
    if template.mailing_address:
        payload["full_address"] = template.mailing_address
    if template.tax:
        payload["tax_uid"] = str(template.tax.uid)

    serializer = PrivateWeCreditNoteListSerializer(
        data=payload,
        context={"request": _synthetic_request(user)},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    # That serializer's create() returns validated_data rather than the
    # instance, so the note is looked up by the number we minted for it.
    return CreditNote.objects.get(
        company=company, credit_note_number=credit_note_number
    )


def generate_from_template(template, user, company, *, transaction_date=None, send_email=False):
    """Dispatch to the bill / expense / cheque / estimate generator by type.

    Every supported type is matched **explicitly** and an unrecognised one
    raises. This used to fall through to the bill generator, which was harmless
    only for as long as BILL was the sole unmatched type: the moment a new
    ``txn_type`` is added to the choices without a generator here, a fallthrough
    would silently post bills for it (an invoice template quietly creating
    accounts-payable entries). Fail loudly instead.
    """
    from ..choices import RecurringTxnTypeChoices

    if template.txn_type == RecurringTxnTypeChoices.BILL:
        return generate_bill_from_template(
            template, user, company, bill_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.EXPENSE:
        return generate_expense_from_template(
            template, user, company, expense_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.CHEQUE:
        return generate_cheque_from_template(
            template, user, company, cheque_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.CREDIT_MEMO:
        return generate_credit_memo_from_template(
            template, user, company, memo_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.DEPOSIT:
        return generate_deposit_from_template(
            template, user, company, deposit_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.SALES_RECEIPT:
        return generate_sales_receipt_from_template(
            template, user, company, receipt_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.PURCHASE_ORDER:
        return generate_purchase_order_from_template(
            template, user, company, order_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.INVOICE:
        return generate_invoice_from_template(
            template, user, company, invoice_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.PAYMENT:
        return generate_payment_from_template(
            template, user, company, receipt_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.ESTIMATE:
        return generate_estimate_from_template(
            template, user, company, estimate_date=transaction_date, send_email=send_email
        )
    if template.txn_type == RecurringTxnTypeChoices.REFUND_RECEIPT:
        return generate_refund_receipt_from_template(
            template, user, company, refund_date=transaction_date, send_email=send_email
        )

    raise ValueError(
        f"No generator is wired for recurring txn_type {template.txn_type!r}; "
        "add one before allowing templates of that type to fire."
    )
