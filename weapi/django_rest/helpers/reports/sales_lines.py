"""Line-level sales reports: the same rows grouped three ways.

"Sales by Customer Detail", "Sales by Product/Service Detail" and "Sales by
Product/Service Summary" all print *transaction lines* -- invoice, sales
receipt, refund receipt and credit-memo items -- where the account-level
reports (profit and loss, sales by customer summary) read the journal. The
inclusion rules mirror `taxable_sales_summary`, the existing line-level
report: live sale statuses only, refund receipts (``Sale.kind=REFUND``) and
sales-side credit memos net in as negatives, removed lines are skipped. The
one difference is that every line counts here, not just taxable ones.

The Summary's COGS is unit purchase cost x net quantity. The unit cost is the
product's latest ``ProductAdditionalCost`` amount -- the same figure
``Product.get_purchase_price()`` returns. The journal's COGS legs would say
the same thing when they exist, but quantity never reaches the journal and
there is no stock-movement ledger to give a historical (FIFO) cost, so the
current purchase cost is the only per-unit figure the data holds.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from creditnoteio.choices import (
    CreditNoteItemStatusChoices,
    CreditNoteKindChoices,
    CreditNoteStatusChoices,
)
from creditnoteio.models import CreditNoteItem

from productio.choices import ProductStatusChoices

from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices
from salesio.models import SaleItem

from weapi.django_rest.helpers.dashboard.finance import LIVE_SALE_STATUSES
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    UNASSIGNED_KEY,
    UNASSIGNED_LABEL,
    amount_string,
)


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def _money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def percent_string(value):
    """``96.15``, ``20.0``, ``100.0`` -- two decimals with one trailing zero
    dropped, the way the reference prints its percent columns."""
    text = f"{Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP):.2f}"
    return text[:-1] if text.endswith("0") else text


def _customer_label(customer):
    if customer is None:
        return UNASSIGNED_LABEL
    label = (customer.display_name or "").strip()
    if not label:
        label = " ".join(
            part
            for part in (
                (customer.first_name or "").strip(),
                (customer.last_name or "").strip(),
            )
            if part
        )
    return label or "(unnamed)"


def _product_label(product):
    if product is None:
        return UNASSIGNED_LABEL
    label = product.title or ""
    if product.status == ProductStatusChoices.REMOVED:
        label = f"{label} (deleted)".strip()
    return label or "(unnamed)"


def collect_sales_lines(company, date_from=None, date_to=None):
    """Every countable sale/credit line in the period, one dict per printed row.

    Quantities and amounts are already signed: a refund receipt or credit memo
    line arrives negative, its unit price stays positive -- exactly how the
    reference prints them.
    """
    rows = []

    sale_items = (
        SaleItem.objects.filter(
            sale__company=company, sale__status__in=LIVE_SALE_STATUSES
        )
        .filter(Q(sale__is_invoice=True) | Q(sale__is_sale_receipt=True))
        .exclude(status=SaleItemStatusChoices.REMOVED)
        .select_related("sale", "sale__customer", "product")
        .order_by("sale__date", "sale__invoice_id", "id")
    )
    if date_from:
        sale_items = sale_items.filter(sale__date__gte=date_from)
    if date_to:
        sale_items = sale_items.filter(sale__date__lte=date_to)

    for item in sale_items:
        sale = item.sale
        if sale.kind == SaleReceptKindChoices.REFUND:
            sign, txn_type = Decimal("-1"), "Refund"
        else:
            sign = Decimal("1")
            txn_type = "Invoice" if sale.is_invoice else "Sales Receipt"
        customer = sale.customer if sale.customer_id else None
        rows.append(
            {
                "date": sale.date,
                "txn_type": txn_type,
                "num": sale.invoice_id or "",
                "txn_uid": str(sale.uid),
                "customer_uid": str(customer.uid) if customer else None,
                "customer_name": _customer_label(customer),
                "product_uid": str(item.product.uid) if item.product_id else None,
                "product_name": _product_label(item.product),
                "description": item.description or "",
                "quantity": sign * Decimal(item.quantity or 0),
                "sale_price": _money(item.sale_price),
                "amount": sign * _money(item.total),
            }
        )

    credit_items = (
        CreditNoteItem.objects.filter(
            credit_note__company=company, credit_note__kind=CreditNoteKindChoices.SALE
        )
        .exclude(credit_note__status=CreditNoteStatusChoices.REMOVED)
        .exclude(status=CreditNoteItemStatusChoices.REMOVED)
        .select_related("credit_note", "credit_note__customer", "product")
        .order_by("credit_note__date", "credit_note__credit_note_number", "id")
    )
    if date_from:
        credit_items = credit_items.filter(credit_note__date__gte=date_from)
    if date_to:
        credit_items = credit_items.filter(credit_note__date__lte=date_to)

    for item in credit_items:
        note = item.credit_note
        quantity = Decimal(item.quantity or 0)
        # The printed "sales price" is the per-unit credit; rows that only
        # carry a line total fall back to deriving it.
        unit = _money(item.item_credit)
        if not unit and quantity:
            unit = _money(Decimal(item.total or 0) / quantity)
        customer = note.customer if note.customer_id else None
        rows.append(
            {
                "date": note.date,
                "txn_type": "Credit Memo",
                "num": note.credit_note_number or "",
                "txn_uid": str(note.uid),
                "customer_uid": str(customer.uid) if customer else None,
                "customer_name": _customer_label(customer),
                "product_uid": str(item.product.uid) if item.product_id else None,
                "product_name": _product_label(item.product),
                "description": item.description or "",
                "quantity": -quantity,
                "sale_price": unit,
                "amount": -_money(item.total),
            }
        )

    # Merge the two sources into one date order. Python's sort is stable, so
    # same-day rows keep each source's id order and the sale/credit interleave
    # is decided by document number, matching the reference.
    rows.sort(key=lambda row: (row["date"], row["num"]))
    return rows


def _detail_columns(entity_key, entity_label):
    return [
        {"key": "date", "label": "Transaction date", "align": "left"},
        {"key": "txn_type", "label": "Transaction type", "align": "left"},
        {"key": "num", "label": "Num", "align": "left"},
        {"key": entity_key, "label": entity_label, "align": "left"},
        {"key": "description", "label": "Description", "align": "left"},
        {"key": "quantity", "label": "Quantity", "align": "right"},
        {"key": "sale_price", "label": "Sales price", "align": "right"},
        {"key": "amount", "label": "Amount", "align": "right"},
        {"key": "balance", "label": "Balance", "align": "right"},
    ]


def _group_sort_key(group):
    # "Not specified" trails the named groups, same as the summary report.
    return (
        group["key"] == UNASSIGNED_KEY,
        (group["label"] or "").lower(),
        group["key"],
    )


def assemble_sales_detail(lines, group_by="customer"):
    """Pure: group collected lines by customer or product with running
    balances, per-group totals and a grand TOTAL.

    The Balance column restarts at zero for each group and accumulates the
    Amount column in print order -- both references show exactly that.
    """
    if group_by == "customer":
        uid_field, name_field = "customer_uid", "customer_name"
        columns = _detail_columns("product_name", "Product/Service full name")
    else:
        uid_field, name_field = "product_uid", "product_name"
        columns = _detail_columns("customer_name", "Customer full name")

    groups = {}
    for line in lines:
        key = line[uid_field] or UNASSIGNED_KEY
        group = groups.setdefault(
            key, {"key": key, "label": line[name_field], "lines": []}
        )
        group["lines"].append(line)

    rows = []
    grand_quantity = ZERO
    grand_amount = ZERO
    for group in sorted(groups.values(), key=_group_sort_key):
        rows.append(
            {
                "key": group["key"],
                "label": group["label"],
                "depth": 0,
                "is_group": True,
                uid_field: None if group["key"] == UNASSIGNED_KEY else group["key"],
            }
        )
        balance = ZERO
        quantity_total = ZERO
        amount_total = ZERO
        for index, line in enumerate(group["lines"]):
            balance += line["amount"]
            quantity_total += line["quantity"]
            amount_total += line["amount"]
            rows.append(
                {
                    "key": f"{group['key']}.{index}",
                    "depth": 1,
                    "date": line["date"],
                    "txn_type": line["txn_type"],
                    "num": line["num"],
                    "txn_uid": line["txn_uid"],
                    "customer_uid": line["customer_uid"],
                    "customer_name": line["customer_name"],
                    "product_uid": line["product_uid"],
                    "product_name": line["product_name"],
                    "description": line["description"],
                    "quantity": amount_string(line["quantity"]),
                    "sale_price": amount_string(line["sale_price"]),
                    "amount": amount_string(line["amount"]),
                    "balance": amount_string(balance),
                }
            )
        rows.append(
            {
                "key": f"{group['key']}.total",
                "label": f"Total for {group['label']}",
                "depth": 0,
                "is_total": True,
                "quantity": amount_string(quantity_total),
                "amount": amount_string(amount_total),
            }
        )
        grand_quantity += quantity_total
        grand_amount += amount_total

    rows.append(
        {
            "key": "total",
            "label": "TOTAL",
            "depth": 0,
            "is_total": True,
            "quantity": amount_string(grand_quantity),
            "amount": amount_string(grand_amount),
        }
    )
    return {"columns": columns, "rows": rows}


SUMMARY_COLUMNS = [
    {"key": "label", "label": "", "align": "left"},
    {"key": "quantity", "label": "Quantity", "align": "right"},
    {"key": "amount", "label": "Amount", "align": "right"},
    {"key": "pct_of_sales", "label": "% of sales", "align": "right"},
    {"key": "avg_price", "label": "Avg. price", "align": "right"},
    {"key": "cogs", "label": "COGS", "align": "right"},
    {"key": "avg_cogs", "label": "Avg. COGS", "align": "right"},
    {"key": "gross_margin", "label": "Gross margin", "align": "right"},
    {"key": "gross_margin_pct", "label": "Gross margin %", "align": "right"},
]


def assemble_product_summary(lines, unit_costs, posted_cogs=None):
    """Pure: one row per product with quantity, sales, share, averages and
    margin, then a TOTAL.

    ``posted_cogs`` maps product uid -> the cost of sales actually posted for
    that product in the period, read from the FIFO layer consumption the sale
    recorded. It is preferred over ``unit_costs`` because it is what the books
    say, and because it cannot move afterwards.

    ``unit_costs`` maps product uid -> per-unit purchase cost, and remains the
    fallback for products whose sales predate the layer ledger. That figure is
    the CURRENT cost of the item, multiplied by quantity sold: editing an item's
    cost therefore restated the cost of sales on every period it had ever
    appeared in, including closed ones, and the report disagreed with the
    journal, which had posted the FIFO layer price in force at the time.

    Margin cells are
    ``None`` (render blank) when the product's sales amount is zero -- there is
    no meaningful margin on zero revenue, and the reference leaves exactly
    those cells empty. The TOTAL row also leaves both margin cells blank,
    mirroring the reference.
    """
    buckets = {}
    for line in lines:
        key = line["product_uid"] or UNASSIGNED_KEY
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "label": line["product_name"],
                "quantity": ZERO,
                "amount": ZERO,
            },
        )
        bucket["quantity"] += line["quantity"]
        bucket["amount"] += line["amount"]

    total_quantity = sum((b["quantity"] for b in buckets.values()), ZERO)
    total_amount = sum((b["amount"] for b in buckets.values()), ZERO)

    rows = []
    total_cogs = ZERO
    for bucket in sorted(buckets.values(), key=_group_sort_key):
        quantity, amount = bucket["quantity"], bucket["amount"]
        actual = (posted_cogs or {}).get(bucket["key"])
        if actual is not None:
            cogs = _money(actual)
        else:
            # No layer consumption recorded -- a sale from before the ledger.
            # Fall back to the item's current cost, which is what this report
            # always did, rather than reporting zero cost of sales.
            cogs = _money(unit_costs.get(bucket["key"], ZERO) * quantity)
        total_cogs += cogs
        row = {
            "key": bucket["key"],
            "label": bucket["label"],
            "product_uid": None if bucket["key"] == UNASSIGNED_KEY else bucket["key"],
            "quantity": amount_string(quantity),
            "amount": amount_string(amount),
            "pct_of_sales": percent_string(
                amount / total_amount * HUNDRED if total_amount else ZERO
            ),
            "avg_price": amount_string(amount / quantity if quantity else ZERO),
            "cogs": amount_string(cogs),
            "avg_cogs": amount_string(cogs / quantity if quantity else ZERO),
            "gross_margin": None,
            "gross_margin_pct": None,
        }
        if amount:
            margin = amount - cogs
            row["gross_margin"] = amount_string(margin)
            row["gross_margin_pct"] = percent_string(margin / amount * HUNDRED)
        rows.append(row)

    rows.append(
        {
            "key": "total",
            "label": "TOTAL",
            "is_total": True,
            "quantity": amount_string(total_quantity),
            "amount": amount_string(total_amount),
            "pct_of_sales": percent_string(HUNDRED if total_amount else ZERO),
            "avg_price": amount_string(
                total_amount / total_quantity if total_quantity else ZERO
            ),
            "cogs": amount_string(total_cogs),
            "avg_cogs": amount_string(
                total_cogs / total_quantity if total_quantity else ZERO
            ),
            "gross_margin": None,
            "gross_margin_pct": None,
        }
    )
    return {"columns": SUMMARY_COLUMNS, "rows": rows}


def _unit_costs(keys):
    """Latest additional-cost amount per product uid -- what
    ``Product.get_purchase_price()`` answers, in one query."""
    from productio.models import ProductAdditionalCost

    real = [key for key in keys if key != UNASSIGNED_KEY]
    if not real:
        return {}
    costs = {}
    rows = (
        ProductAdditionalCost.objects.filter(product__uid__in=real)
        .order_by("product__uid", "-created_at", "-id")
        .values("product__uid", "amount")
    )
    for row in rows:
        costs.setdefault(str(row["product__uid"]), _money(row["amount"]))
    return costs


def build_sales_detail(company, date_from=None, date_to=None, group_by="customer"):
    lines = collect_sales_lines(company, date_from, date_to)
    return assemble_sales_detail(lines, group_by=group_by)


def _posted_cogs(company, keys, date_from=None, date_to=None):
    """Cost of sales actually posted per product, from the layer ledger.

    Sums `StockMovementLayerConsumption.cost_amount` over the outbound sale
    movements in the period. That is the cost the journal relieved, lot by lot,
    at the price in force when each sale happened -- so it reproduces the same
    figure however long afterwards the report is run, and however often the
    item's cost is edited since.
    """
    from stockio.choices import StockMovementTypeChoices
    from stockio.models import StockMovementLayerConsumption

    real = [key for key in keys if key != UNASSIGNED_KEY]
    if not real:
        return {}

    queryset = StockMovementLayerConsumption.objects.filter(
        movement__company=company,
        movement__movement_type=StockMovementTypeChoices.SALE,
        movement__product__uid__in=real,
    )
    if date_from:
        queryset = queryset.filter(movement__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(movement__date__lte=date_to)

    return {
        str(row["movement__product__uid"]): _money(row["total"])
        for row in queryset.values("movement__product__uid").annotate(
            total=Sum("cost_amount")
        )
    }


def build_sales_by_product_summary(company, date_from=None, date_to=None):
    lines = collect_sales_lines(company, date_from, date_to)
    keys = {line["product_uid"] or UNASSIGNED_KEY for line in lines}
    return assemble_product_summary(
        lines,
        _unit_costs(keys),
        posted_cogs=_posted_cogs(company, keys, date_from, date_to),
    )
