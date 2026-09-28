"""Aggregate a company's sales into per-(state, month) buckets for nexus.

Mirrors the proven two-leg, sign-aware, customer-address join used by the
Taxable Sales / Sales Tax Liability reports so nexus figures reconcile with them:

* Invoices + sales receipts (``Sale.is_invoice`` / ``is_sale_receipt``, live
  statuses) add; refund receipts (``Sale.kind == REFUND``) subtract; credit memos
  (sales-side ``CreditNote``) subtract.
* A sale's state is its **customer's** address ``province`` (normalized to a USPS
  code); the sale's own SALE-kind address is unstructured free text, so the
  customer address is the only reliable structured state. Country must be US.
* Sales that resolve to no US state land in an ``unattributed`` bucket (surfaced
  as a data-quality figure, never silently dropped).

Money is in document currency (multicurrency normalization to USD is a
documented v1 limitation; matches the existing tax reports).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q

from addressio.choices import AddressConnectorKindCoices
from addressio.models import AddressConnector

from creditnoteio.choices import (
    CreditNoteItemStatusChoices,
    CreditNoteKindChoices,
    CreditNoteStatusChoices,
)
from creditnoteio.models import CreditNoteItem

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    normalize_us_state,
)

from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices
from salesio.models import SaleItem

from weapi.django_rest.helpers.dashboard.finance import LIVE_SALE_STATUSES


def _month(d):
    return date(d.year, d.month, 1) if d else None


def normalize_nexus_state(province):
    """USPS code for a nexus jurisdiction (50 states + DC + PR), or None.

    ``normalize_us_state`` (shared with payroll) covers the 50 states + DC but not
    Puerto Rico, which IS a tracked nexus jurisdiction — so add PR here.
    """
    if not province:
        return None
    code = normalize_us_state(province)
    if code:
        return code
    upper = str(province).strip().upper()
    if upper in ("PR", "PUERTO RICO"):
        return "PR"
    return None


def customer_state_map(company):
    """{customer_id: USPS state code or None} from each customer's CUSTOMER address.

    First connector per customer wins (mirrors the app's ``.first()`` read). A
    missing/foreign/unrecognized address resolves to None (unattributed).
    """
    mapping = {}
    seen = set()
    connectors = (
        AddressConnector.objects.filter(
            customer__company=company,
            kind=AddressConnectorKindCoices.CUSTOMER,
        )
        .select_related("address")
        .order_by("customer_id", "created_at")
    )
    for conn in connectors:
        cid = conn.customer_id
        if cid in seen:
            continue
        seen.add(cid)
        addr = conn.address
        if addr and (addr.country or "us").lower() == "us":
            mapping[cid] = normalize_nexus_state(addr.province)
        else:
            mapping[cid] = None
    return mapping


def _empty_bucket():
    return {"gross": Decimal("0"), "taxable": Decimal("0"), "sales": set()}


def aggregate_by_state_month(company):
    """Return (buckets, unattributed).

    ``buckets[state_code][month_first_day] = {gross, taxable, sales:set(sale_ids)}``.
    ``unattributed = {gross, taxable}`` for sales with no resolvable US state.
    Transaction count = distinct positive (non-refund) sales; refund receipts and
    credit memos reduce dollars but are not counted as transactions.
    """
    state_map = customer_state_map(company)
    buckets = defaultdict(lambda: defaultdict(_empty_bucket))
    unattributed = {"gross": Decimal("0"), "taxable": Decimal("0")}

    sale_items = (
        SaleItem.objects.filter(
            sale__company=company, sale__status__in=LIVE_SALE_STATUSES
        )
        .filter(Q(sale__is_invoice=True) | Q(sale__is_sale_receipt=True))
        .exclude(status=SaleItemStatusChoices.REMOVED)
        .select_related("sale")
    )
    for item in sale_items:
        sale = item.sale
        sign = -1 if sale.kind == SaleReceptKindChoices.REFUND else 1
        amount = Decimal(str(item.total or 0)) * sign
        taxable = amount if item.is_tax else Decimal("0")
        state = state_map.get(sale.customer_id)
        month = _month(sale.date)
        if state is None or month is None:
            unattributed["gross"] += amount
            unattributed["taxable"] += taxable
            continue
        bucket = buckets[state][month]
        bucket["gross"] += amount
        bucket["taxable"] += taxable
        if sign > 0:
            bucket["sales"].add(sale.id)

    credit_items = (
        CreditNoteItem.objects.filter(
            credit_note__company=company,
            credit_note__kind=CreditNoteKindChoices.SALE,
        )
        # Only issued credit memos net down — a DRAFT one isn't live, mirroring the
        # sale leg's LIVE_SALE_STATUSES (which excludes drafts). Netting a draft
        # credit would understate sales and mask a real crossing (false negative).
        .exclude(
            credit_note__status__in=[
                CreditNoteStatusChoices.DRAFT,
                CreditNoteStatusChoices.REMOVED,
            ]
        )
        .exclude(status=CreditNoteItemStatusChoices.REMOVED)
        .select_related("credit_note")
    )
    for item in credit_items:
        credit_note = item.credit_note
        amount = -Decimal(str(item.total or 0))
        taxable = amount if item.tax_id is not None else Decimal("0")
        state = state_map.get(credit_note.customer_id)
        month = _month(credit_note.date)
        if state is None or month is None:
            unattributed["gross"] += amount
            unattributed["taxable"] += taxable
            continue
        bucket = buckets[state][month]
        bucket["gross"] += amount
        bucket["taxable"] += taxable

    return buckets, unattributed


def sum_window(state_buckets, window_start, window_end):
    """Sum a state's month buckets over [window_start, window_end].

    Month-level inclusion: a bucket counts if its first-of-month falls within the
    window's month span. Year-aligned windows sum exactly; a TRAILING_12M window
    may over-include its start boundary month (a documented v1 approximation —
    the precise boundary top-up is a later refinement).
    """
    start_m = _month(window_start)
    end_m = _month(window_end)
    gross = Decimal("0")
    taxable = Decimal("0")
    count = 0
    for month, bucket in state_buckets.items():
        if start_m <= month <= end_m:
            gross += bucket["gross"]
            taxable += bucket["taxable"]
            count += len(bucket["sales"])
    return {"gross": gross, "taxable": taxable, "count": count}
