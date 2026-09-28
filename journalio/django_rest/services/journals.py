import logging
from decimal import Decimal

from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.balance_helpers import get_debit_or_credit

from ...choices import (
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryConnectorKindChoices,
)
from ...models import JournalEntry, JournalEntryConnector

logger = logging.getLogger(__name__)


def assert_entry_balances(journal_entry):
    """Report a journal entry whose debits and credits disagree.

    This is the only place worth putting it. There are five independent posting
    implementations -- `sale_posting.post_sale_document`, the `weapi` purchase /
    credit-note / deposit serializers, `salary_process_journal_entry`, the
    `datamigrationio` `Migration*CreateService` importers (which the nightly
    recurring generator also drives), and the chart-of-account opening-balance
    writers -- and `create_journal_entry_connector` is the single function all
    of them pass through. Nothing compared the two sides here, so an entry that
    did not balance was written and committed in silence.

    Production found out the expensive way: 307 unbalanced entries across 12
    companies, 134 of them dated 2026, one being regenerated nightly by a cron.

    **Logs, does not raise.** Several document types are still producing
    unbalanced entries today, so raising would turn each of those into a 500 on
    a request that currently succeeds -- trading silent bad data for an outage,
    before the fixes that would prevent it have landed. The log line is the
    measurement instrument for those fixes; once they are in and this stops
    firing, it should become a raise inside the surrounding transaction so no
    future call site can reintroduce the problem.

    Reads the entry's whole connector set rather than the batch just written,
    because a few callers build an entry across more than one call.
    """
    if journal_entry is None:
        return True

    rows = journal_entry.journalentryconnector_set.all()
    debit = sum(Decimal(str(row.debit or 0)) for row in rows)
    credit = sum(Decimal(str(row.credit or 0)) for row in rows)
    if debit == credit:
        return True

    logger.error(
        "journal entry %s (%s, company=%s) does NOT balance -- debit %s vs "
        "credit %s (out by %s) across %s lines",
        journal_entry.pk,
        getattr(journal_entry, "kind", "?"),
        getattr(journal_entry, "company_id", "?"),
        debit,
        credit,
        debit - credit,
        len(rows),
    )
    return False


def reverse_item_connectors(connectors):
    """Undo and remove every ledger leg a document line wrote.

    Returns the number of legs reversed.

    The delete paths this replaces reversed a **hand-picked list of accounts** --
    income, product asset and cost of sales for a sale line; inventory and the
    charter account for a purchase line -- and then deleted the line. Any leg on
    an account outside that list was not reversed, and the CASCADE on
    `JournalEntryConnector.saleitem` / `.purchase_item` / `.credit_note_item`
    then deleted it silently. The stored balance kept the movement while the
    ledger line that explained it was gone, and the parent entry was left short
    with nothing recording why.

    That was never a safe way to write it: the list of accounts a line can touch
    is not fixed. It depends on the product's configuration, on which tax groups
    the line carries, and on what the request supplied. Enumerating the
    connectors that actually exist is the only version that cannot fall behind.

    Each undo is derived from the leg's own stored `kind` against its account's
    kind, so it reverses what was really written -- including rows posted before
    the sides were corrected, which a hard-coded undo gets backwards. The
    reversal is computed from the connector, never from the document, because
    the document's own figures may already have been amended.
    """
    from common.django_rest.helpers.balance_helpers import (
        get_migration_undo_balance_operation,
        update_opening_balance,
    )

    # Materialise before deleting: the queryset would otherwise be re-evaluated
    # against rows that no longer exist.
    rows = list(connectors.select_related("account"))
    reversed_legs = 0

    for connector in rows:
        account = connector.account
        if account is None:
            continue
        amount = connector.debit if connector.debit else connector.credit
        if not amount:
            continue

        update_opening_balance(
            account,
            get_migration_undo_balance_operation(account, connector.kind),
            amount,
            0,
        )
        reversed_legs += 1

    if rows:
        JournalEntryConnector.objects.filter(
            pk__in=[c.pk for c in rows]
        ).delete()

    return reversed_legs


# Which field on each document carries the date its posting belongs to.
#
# Keyed by the FK name on `JournalEntry`, so it lines up with the kind -> FK map
# inside `create_journal_entry` and a reader can check the two against each
# other. Ten of the thirteen are just `date`; the exceptions are named rather
# than found by scanning attributes, because several of these models carry more
# than one date and picking by first-match would silently choose a due date over
# a posting date.
DOCUMENT_DATE_FIELD = {
    "credit_note": "date",
    "purchase": "date",
    "expense": "date",
    "purchase_payment": "date",
    "pay_bill": "date",
    "sale": "date",
    "sale_payment_receive": "date",
    "stock_adjustment": "date",
    "product": "date",
    "bank_deposit": "date",
    "bank_reconciliation": "statement_ending_date",
    "payroll_salary": "pay_date",
    "tax_payment": "payment_date",
}

# `sales_tax` is deliberately absent. `SalesTax` carries `sales_tax_due_date`
# and `sales_tax_period`, a CharField -- a due date is not a posting date, and
# deriving one from a period string would be guessing at a format nothing
# validates. Those entries keep the model default until the model carries a date
# that means what this needs.
DOCUMENT_DATE_FIELD_EXEMPT = {"sales_tax"}


class JournalEntryService:

    def create_journal_entry(
        journal_entry_number: str = "",
        amount: float = 0,
        status: str = JournalEntryStatusChoices.PUBLISHED,
        kind: str = JournalEntryKindChoices.PURCHASE,
        is_transaction: bool = False,
        is_journal_entry: bool = True,
        is_deposit: bool = False,
        company=None,
        object=None,
        date=None,
    ):
        """`date` is the date the entry BELONGS to, not when it was written.

        Both `JournalEntry.date` and `JournalEntryConnector.date` are
        `DateField(default=date.today)` and nothing ever passed one, so every
        document posting -- sale, purchase, payroll, credit note, pay bill,
        bank deposit, opening balance -- landed on the day it was entered. A
        backdated invoice posted to today. The only path that got this right
        was the manual journal-entry serializer, which sets the field itself.

        Additive: omitted, the date is taken from `object`'s own date field via
        `DOCUMENT_DATE_FIELD`, and failing that the model default applies.

        Callers may still pass `date` explicitly and it wins -- the
        reconciliation module does, because a forced-close adjustment belongs to
        the statement date rather than to any document.
        """
        payload = {}
        fk_name = (
            {
                JournalEntryKindChoices.CREDIT_NOTE: "credit_note",
                JournalEntryKindChoices.PURCHASE: "purchase",
                JournalEntryKindChoices.EXPENSE: "expense",
                JournalEntryKindChoices.PURCHASE_PAYMENT: "purchase_payment",
                JournalEntryKindChoices.PAY_BILL: "pay_bill",
                JournalEntryKindChoices.SALE: "sale",
                JournalEntryKindChoices.SALE_RECEPT: "sale",
                JournalEntryKindChoices.REFUND_RECEIPT: "sale",
                JournalEntryKindChoices.SALE_PAYMENT_RECEIVE: "sale_payment_receive",
                JournalEntryKindChoices.STOCK_ADJUSTMENT: "stock_adjustment",
                JournalEntryKindChoices.PRODUCT_PRURCHASE: "product",
                JournalEntryKindChoices.CHEQUE: "purchase",
                JournalEntryKindChoices.BANK_DEPOSIT: "bank_deposit",
                JournalEntryKindChoices.BANK_RECONCILIATION: "bank_reconciliation",
                JournalEntryKindChoices.PAYROLL_SALARY_PROCESS: "payroll_salary",
                JournalEntryKindChoices.PAYROLL_TAX_PAYMENT: "tax_payment",
                JournalEntryKindChoices.SALES_TAX: "sales_tax",
            }
        ).get(kind)
        payload[fk_name] = object

        # Take the date from the document when the caller has not given one.
        #
        # The caller always passes `object` -- it is how the entry is linked to
        # its document -- so the date it belongs to is already here, and every
        # call site would otherwise have to remember to pass it separately.
        # Twenty-seven of twenty-nine did not, which is how a backdated invoice
        # came to post to the day it was keyed.
        if date is None and object is not None:
            document_date_field = DOCUMENT_DATE_FIELD.get(fk_name)
            if document_date_field:
                date = getattr(object, document_date_field, None)

        return JournalEntry.objects.get_or_create(
            defaults={
                "entry_number": (
                    journal_entry_number
                    if journal_entry_number != ""
                    else get_unique_id(JournalEntry, company.id, "entry_number", "JE")
                ),
                "amount": amount,
                "status": status,
                "kind": kind,
                "is_transaction": is_transaction,
                "is_journal_entry": is_journal_entry,
                "is_deposit": is_deposit,
                "company": company,
                **({"date": date} if date is not None else {}),
            },
            **payload,
        )[0]

    def create_journal_entry_connector(
        connector_data: list = [],
        total: float = 0,
        request_kind: str = JournalEntryConnectorRequestKindChoices.CREATED,
        journal_entry=None,
        supplier=None,
        customer=None,
        warehose=None,
        tax=None,
        created_by=None,
        employee=None,
        date=None,
        description=None,
    ):
        """`date` is the date these lines BELONG to -- see create_journal_entry.

        Defaults to the entry's own date when one is available, so a caller
        that dates the entry does not have to remember to date its lines too.
        """
        if date is None:
            date = getattr(journal_entry, "date", None)
        journal_connectors = []
        for item in connector_data:
            # Unpack the fixed elements that are always required
            account = item[0]
            action_type = item[1]
            total_debit_or_credit = item[2]
            last_balance = item[3]
            parent = item[4] if len(item) > 4 else None
            sale_item = item[5] if len(item) > 5 else None
            purchase_item = item[6] if len(item) > 6 else None
            credit_note_item = item[7] if len(item) > 7 else None
            # Which payee line a Pay Bills leg belongs to. Without it a payment
            # to two payees cannot be unwound one line at a time -- the entry is
            # shared, and `supplier` alone is ambiguous the moment the same
            # vendor appears twice on one payment.
            pay_bill_item = item[8] if len(item) > 8 else None
            _debit_or_credit = get_debit_or_credit(account.kind)[action_type]
            _total_debit_or_credit = {
                "debit_total": (
                    total_debit_or_credit
                    if _debit_or_credit == JournalEntryConnectorKindChoices.DEBIT
                    else 0
                ),
                "credit_total": (
                    total_debit_or_credit
                    if _debit_or_credit == JournalEntryConnectorKindChoices.CREDIT
                    else 0
                ),
            }
            journal_connectors.append(
                JournalEntryConnector(
                    parent=parent,
                    **({"date": date} if date is not None else {}),
                    # Carried onto the leg so a reversal can say why it exists.
                    # `JournalEntryConnector` is auditlog-registered and
                    # `BankReconciliation` is not, so for an undo this is the
                    # copy of the reason an auditor actually reaches.
                    **({"description": description} if description else {}),
                    debit=_total_debit_or_credit["debit_total"],
                    credit=_total_debit_or_credit["credit_total"],
                    total=total,
                    last_balance=last_balance,
                    kind=_debit_or_credit,
                    request_kind=request_kind,
                    journal=journal_entry,
                    account=account,
                    supplier=supplier,
                    customer=customer,
                    warehose=warehose,
                    tax=tax,
                    saleitem=sale_item,
                    purchase_item=purchase_item,
                    credit_note_item=credit_note_item,
                    pay_bill_item=pay_bill_item,
                    created_by=created_by,
                    employee=employee,
                    transaction_id=get_unique_id(
                        JournalEntryConnector, journal_entry.id, "transaction_id", "JI"
                    ),
                    is_customer_or_supplier_transaction=account is None,
                )
            )
        JournalEntryConnector.objects.bulk_create(journal_connectors)
        assert_entry_balances(journal_entry)
        return True
