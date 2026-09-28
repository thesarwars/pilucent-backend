"""Taxable Sales Summary report builder.

Builds the report described in
``docs/updated-prompts/Taxable_Sales_Summary_Documentation.md``: the taxable
sales *base* (the amount sales tax is charged on -- NOT the tax itself), grouped
by product/service, with category subtotals, a "no item" bucket, and a grand
total that is the period's filing-ready taxable base.

Inclusion rule (doc section 1/5): every **taxable** line (``SaleItem.is_tax=True``)
on an invoice or sales receipt dated in the period counts at its ex-tax line
amount (``SaleItem.total``); credit memos (``CreditNoteItem`` on a
``CreditNote`` of kind=SALE) and refund receipts (``Sale.kind=REFUND``) net in as
**negatives**. Lines with no product fall in the unlabeled "no item" bucket;
deleted products still appear (marked "(deleted)").

Documented modelling choices (no runtime dataset to reconcile against -- the spec
only gives final figures, so the *pure* assembler is unit-tested against them):
  * ``SaleItem.total`` is treated as the ex-tax base (true for EXCLUSIVE tax; for
    INCLUSIVE-tax documents it may already include tax -- flagged, not corrected).
  * In-place partial refunds (``SaleItem.refund_total``) are NOT separately netted
    here; refunds/returns are assumed represented as refund receipts / credit
    memos (their own documents) to avoid double-counting.
  * Accrual basis only (by ``Sale.date`` / ``CreditNote.date``); cash basis is not
    cleanly derivable from the data and is out of scope.
  * A credit-memo line is treated as taxable when it carries a tax (``tax`` FK set)
    -- ``CreditNoteItem`` has no ``is_tax`` flag.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from categoryio.choicess import CategoryKindChoices

from creditnoteio.choices import CreditNoteItemStatusChoices, CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNoteItem

from django.db.models import Q

from productio.choices import ProductStatusChoices

from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices
from salesio.models import SaleItem

from weapi.django_rest.helpers.dashboard.finance import LIVE_SALE_STATUSES

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _product_category(product):
    """First product/service category title for a product, or None.

    Product<->Category is the through model ``CategoryConnector``; the app reads
    the single category as ``categoryconnector_set.first`` -- we mirror that but
    restrict to product/service categories (the same Category model is reused for
    chart-of-accounts).
    """
    connector = (
        product.categoryconnector_set.filter(
            category__kind__in=[CategoryKindChoices.PRODUCT, CategoryKindChoices.SERVICE]
        )
        .select_related("category")
        .first()
    )
    return connector.category.title if connector and connector.category_id else None


def _product_descriptor(product):
    """Return (key, label, category) for a sale/credit line's product.

    ``key`` is the product uid (or None for the no-item bucket); deleted products
    keep their historical row with a "(deleted)" marker (doc section 7.3).
    """
    if product is None:
        return None, "", None
    label = product.title or ""
    if product.status == ProductStatusChoices.REMOVED:
        label = f"{label} (deleted)".strip()
    return str(product.uid), label, _product_category(product)


def assemble_taxable_sales(buckets, as_of, has_no_item=False):
    """Pure: organize per-product net taxable amounts into no-item / uncategorized
    item rows / category groups + a grand total.

    ``buckets`` is an iterable of ``{key, label, category, amount}`` where ``key``
    is the product uid (or None for the no-item bucket) and ``amount`` is the net
    taxable base (Decimal, already signed for credits/refunds). Kept ORM-free so
    the totals are unit-testable against the documentation's worked example.
    """
    no_item_amount = ZERO
    uncategorized = []
    categories = {}
    grand_total = ZERO

    for bucket in buckets:
        amount = _money(bucket["amount"])
        grand_total += amount
        if bucket["key"] is None:
            no_item_amount += amount
            continue
        category = bucket.get("category")
        row = {"uid": bucket["key"], "label": bucket["label"], "amount": float(amount)}
        if category:
            group = categories.setdefault(
                category, {"label": category, "items": [], "_amount": ZERO}
            )
            group["items"].append(row)
            group["_amount"] += amount
        else:
            uncategorized.append(row)

    uncategorized.sort(key=lambda r: (r["label"] or "").lower())
    category_rows = []
    for name in sorted(categories, key=lambda s: (s or "").lower()):
        group = categories[name]
        group["items"].sort(key=lambda r: (r["label"] or "").lower())
        category_rows.append(
            {
                "label": group["label"],
                "amount": float(group["_amount"]),
                "items": group["items"],
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "no_item": {"amount": float(no_item_amount)} if has_no_item else None,
        "items": uncategorized,
        "categories": category_rows,
        "total": float(grand_total),
    }


def _accumulate(buckets, product, amount):
    # Resolve the cheap dedup key first; only do the category lookup (a DB query)
    # the first time a product is seen, not for every line it appears on.
    key = str(product.uid) if product is not None else None
    entry = buckets.get(key)
    if entry is None:
        _, label, category = _product_descriptor(product)
        entry = buckets[key] = {
            "key": key,
            "label": label,
            "category": category,
            "amount": ZERO,
        }
    entry["amount"] += amount


def taxable_sales_summary(company, as_of=None, start_date=None, end_date=None):
    """Build the full Taxable Sales Summary for ``company`` (accrual basis)."""
    as_of = as_of or date.today()
    buckets = {}

    # Invoices + sales receipts: taxable lines add (refund receipts subtract).
    sale_items = (
        SaleItem.objects.filter(
            sale__company=company,
            is_tax=True,
            sale__status__in=LIVE_SALE_STATUSES,
        )
        .filter(Q(sale__is_invoice=True) | Q(sale__is_sale_receipt=True))
        .exclude(status=SaleItemStatusChoices.REMOVED)
        .select_related("sale", "product")
    )
    if start_date:
        sale_items = sale_items.filter(sale__date__gte=start_date)
    if end_date:
        sale_items = sale_items.filter(sale__date__lte=end_date)
    for item in sale_items:
        sign = -1 if item.sale.kind == SaleReceptKindChoices.REFUND else 1
        _accumulate(buckets, item.product, _money(item.total) * sign)

    # Credit memos (sales-side): taxable lines net negative.
    credit_items = (
        CreditNoteItem.objects.filter(
            credit_note__company=company,
            credit_note__kind=CreditNoteKindChoices.SALE,
            tax__isnull=False,
        )
        .exclude(credit_note__status=CreditNoteStatusChoices.REMOVED)
        .exclude(status=CreditNoteItemStatusChoices.REMOVED)
        .select_related("product")
    )
    if start_date:
        credit_items = credit_items.filter(credit_note__date__gte=start_date)
    if end_date:
        credit_items = credit_items.filter(credit_note__date__lte=end_date)
    for item in credit_items:
        _accumulate(buckets, item.product, -_money(item.total))

    return assemble_taxable_sales(
        list(buckets.values()), as_of, has_no_item=(None in buckets)
    )
