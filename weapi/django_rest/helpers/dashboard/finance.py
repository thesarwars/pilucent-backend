"""Reusable finance aggregations for v2 dashboard cards.

All helpers are company-scoped and use ``due_total`` (not ``total``) for open
AR/AP balances, and a computed overdue rule (``due_date < today AND
due_total > 0``) since there is no OVERDUE status in the sales/purchase enums.
"""

import calendar
import math
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.db.models import Q, Sum, Count, F, DecimalField
from django.db.models.functions import Coalesce, TruncMonth

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices

from salesio.models import Sale, SaleItem
from salesio.choices import SalesStatusChoices, SaleItemStatusChoices

from purchaseio.models import Purchase
from purchaseio.choices import PurchaseStatus

from transactionio.models import TransactionInformation


ZERO = Decimal("0.00")

# Sale/purchase statuses that represent "live" documents (exclude drafts,
# removed, rejected). Used for revenue, invoice counts, top customers, etc.
LIVE_SALE_STATUSES = [
    SalesStatusChoices.PENDING,
    SalesStatusChoices.OPEN,
    SalesStatusChoices.ACCEPTED,
    SalesStatusChoices.CLOSED,
    SalesStatusChoices.PAID,
]
LIVE_PURCHASE_STATUSES = [
    PurchaseStatus.PENDING,
    PurchaseStatus.OPEN,
    PurchaseStatus.ACCEPTED,
    PurchaseStatus.CLOSED,
    PurchaseStatus.COMPLETED,
]

AGING_BUCKETS = ["current", "1_30", "31_60", "61_90", "90_plus"]


def _sum(qs, field):
    return qs.aggregate(
        total=Coalesce(Sum(field), ZERO, output_field=DecimalField())
    )["total"]


# ---------------------------------------------------------------------------
# Revenue / P&L
# ---------------------------------------------------------------------------

def revenue_total(company, date_from, date_to):
    """Posted sales revenue for the period (invoices + sale receipts)."""
    qs = Sale.objects.filter(
        company=company,
        status__in=LIVE_SALE_STATUSES,
        date__range=[date_from, date_to],
    ).filter(Q(is_invoice=True) | Q(is_sale_receipt=True))
    return _sum(qs, "total")


def coa_income_expense(company, date_from, date_to):
    """Income and expense totals from the GL (Chart of Accounts connectors).

    Mirrors the v1 P&L approach so dashboard numbers reconcile with the P&L
    report; filtered to the posting date range via journal entry connectors.
    """
    base = (
        ChartOfAccount.objects.get_status_all()
        .filter(
            company=company,
            journalentryconnector__isnull=False,
            journalentryconnector__created_at__date__range=[date_from, date_to],
        )
        .distinct()
    )
    agg = base.aggregate(
        total_income=Coalesce(
            Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.INCOMES),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
        total_expense=Coalesce(
            Sum(
                "opening_balance",
                filter=Q(kind=ChartOfAccountKindChoices.EXPENSES),
            ),
            ZERO,
            output_field=DecimalField(),
        ),
    )
    return agg["total_income"], agg["total_expense"]


def net_profit(company, date_from, date_to):
    income, expense = coa_income_expense(company, date_from, date_to)
    return income - expense


def income_expense_by_month(company, months):
    """Return per-month income/expense rows for the trailing ``months`` window."""
    today = date.today()
    end_month_start = date(today.year, today.month, 1)
    start_month = end_month_start - relativedelta(months=months - 1)

    rows = []
    cursor = start_month
    while cursor <= end_month_start:
        month_end = cursor + relativedelta(months=1) - relativedelta(days=1)
        income, expense = coa_income_expense(company, cursor, month_end)
        rows.append(
            {
                "month": calendar.month_abbr[cursor.month],
                "year": cursor.year,
                "income": float(income),
                "expense": float(expense),
            }
        )
        cursor = cursor + relativedelta(months=1)
    return rows


# ---------------------------------------------------------------------------
# Accounts Receivable / Payable
# ---------------------------------------------------------------------------

def open_invoices_qs(company):
    return Sale.objects.filter(
        company=company,
        is_invoice=True,
        due_total__gt=0,
    ).exclude(status__in=[SalesStatusChoices.DRAFT, SalesStatusChoices.REMOVED])


def open_bills_qs(company):
    return Purchase.objects.filter(
        company=company,
        is_bill=True,
        due_total__gt=0,
    ).exclude(status__in=[PurchaseStatus.DRAFT, PurchaseStatus.REMOVED])


def ar_open_total(company):
    return _sum(open_invoices_qs(company), "due_total")


def ap_open_total(company):
    return _sum(open_bills_qs(company), "due_total")


def _aging_from_rows(rows, as_of):
    """Bucket ``(due_date, due_total)`` rows into aging buckets by due date."""
    buckets = {b: ZERO for b in AGING_BUCKETS}
    for due_date, due_total in rows:
        amount = due_total or ZERO
        if due_date is None:
            buckets["current"] += amount
            continue
        days = (as_of - due_date).days
        if days <= 0:
            buckets["current"] += amount
        elif days <= 30:
            buckets["1_30"] += amount
        elif days <= 60:
            buckets["31_60"] += amount
        elif days <= 90:
            buckets["61_90"] += amount
        else:
            buckets["90_plus"] += amount
    return {k: float(v) for k, v in buckets.items()}


def ar_aging(company, as_of=None):
    as_of = as_of or date.today()
    rows = open_invoices_qs(company).values_list("due_date", "due_total")
    return _aging_from_rows(rows, as_of)


def ap_aging(company, as_of=None):
    as_of = as_of or date.today()
    rows = open_bills_qs(company).values_list("due_date", "due_total")
    return _aging_from_rows(rows, as_of)


# ---------------------------------------------------------------------------
# Invoice status distribution
# ---------------------------------------------------------------------------

def invoice_status_distribution(company, date_from, date_to):
    """Counts + amounts by paid / pending / overdue / draft for invoices."""
    today = date.today()
    base = Sale.objects.filter(
        company=company,
        is_invoice=True,
        date__range=[date_from, date_to],
    )

    def bucket(qs):
        agg = qs.aggregate(
            count=Count("id"),
            amount=Coalesce(Sum("total"), ZERO, output_field=DecimalField()),
        )
        return {"count": agg["count"], "amount": float(agg["amount"])}

    paid = base.filter(status=SalesStatusChoices.PAID)
    draft = base.filter(status=SalesStatusChoices.DRAFT)
    overdue = base.filter(due_total__gt=0, due_date__lt=today).exclude(
        status__in=[SalesStatusChoices.DRAFT, SalesStatusChoices.REMOVED]
    )
    pending = base.filter(
        due_total__gt=0,
        status__in=[SalesStatusChoices.PENDING, SalesStatusChoices.OPEN],
    ).filter(Q(due_date__gte=today) | Q(due_date__isnull=True))

    return {
        "paid": bucket(paid),
        "pending": bucket(pending),
        "overdue": bucket(overdue),
        "draft": bucket(draft),
        "total": bucket(base.exclude(status=SalesStatusChoices.REMOVED)),
    }


# ---------------------------------------------------------------------------
# Banking / cash
# ---------------------------------------------------------------------------

def bank_accounts_qs(company):
    return ChartOfAccount.objects.get_status_all().filter(
        company=company,
        account_type__title="Bank",
    )


def cash_balance(company):
    return _sum(bank_accounts_qs(company), "opening_balance")


def cash_in_out(company, date_from, date_to):
    """Cash inflow/outflow from the bank feed for the period."""
    qs = TransactionInformation.objects.filter(
        company=company,
        date__range=[date_from, date_to],
    )
    agg = qs.aggregate(
        inflow=Coalesce(Sum("received"), ZERO, output_field=DecimalField()),
        outflow=Coalesce(Sum("spent"), ZERO, output_field=DecimalField()),
    )
    return agg["inflow"], agg["outflow"]


def _cash_in_out_by_date(company, date_from, date_to):
    """One query: per-day inflow/outflow over the range as ``{date: (in, out)}``."""
    rows = (
        TransactionInformation.objects.filter(
            company=company, date__range=[date_from, date_to]
        )
        .values("date")
        .annotate(
            inflow=Coalesce(Sum("received"), ZERO, output_field=DecimalField()),
            outflow=Coalesce(Sum("spent"), ZERO, output_field=DecimalField()),
        )
    )
    return {row["date"]: (row["inflow"], row["outflow"]) for row in rows}


def cash_flow_series(company, date_from, date_to, buckets=7):
    """Cash inflow/outflow split into evenly-sized date buckets over the range.

    Returns rows ``{label, inflow, outflow}`` where ``label`` is the bucket
    start date formatted like ``"Apr 24"`` — suited to a short-window
    (e.g. 30-day) cash flow chart. Uses a single grouped query and buckets the
    per-day totals in Python rather than one query per bucket.
    """
    total_days = (date_to - date_from).days + 1
    if total_days <= 0:
        return []

    by_date = _cash_in_out_by_date(company, date_from, date_to)
    bucket_size = max(1, math.ceil(total_days / buckets))

    rows = []
    start = date_from
    while start <= date_to:
        end = min(start + timedelta(days=bucket_size - 1), date_to)
        inflow = outflow = ZERO
        cursor = start
        while cursor <= end:
            day_in, day_out = by_date.get(cursor, (ZERO, ZERO))
            inflow += day_in
            outflow += day_out
            cursor += timedelta(days=1)
        rows.append(
            {
                "label": start.strftime("%b %d"),
                "inflow": float(inflow),
                "outflow": float(outflow),
            }
        )
        start = end + timedelta(days=1)
    return rows


def cash_flow_by_month(company, months):
    """Per-month inflow/outflow/net over the trailing ``months`` window.

    Single ``TruncMonth`` grouped query; months with no transactions are
    backfilled with zeros so the series is always ``months`` rows long.
    """
    today = date.today()
    end_month_start = date(today.year, today.month, 1)
    start_month = end_month_start - relativedelta(months=months - 1)
    range_end = end_month_start + relativedelta(months=1) - relativedelta(days=1)

    grouped = (
        TransactionInformation.objects.filter(
            company=company, date__range=[start_month, range_end]
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            inflow=Coalesce(Sum("received"), ZERO, output_field=DecimalField()),
            outflow=Coalesce(Sum("spent"), ZERO, output_field=DecimalField()),
        )
    )
    by_month = {
        (row["month"].year, row["month"].month): (row["inflow"], row["outflow"])
        for row in grouped
    }

    rows = []
    cursor = start_month
    while cursor <= end_month_start:
        inflow, outflow = by_month.get((cursor.year, cursor.month), (ZERO, ZERO))
        rows.append(
            {
                "month": calendar.month_abbr[cursor.month],
                "year": cursor.year,
                "inflow": float(inflow),
                "outflow": float(outflow),
                "net": float(inflow - outflow),
            }
        )
        cursor = cursor + relativedelta(months=1)
    return rows


def cash_health_score(company, months=6):
    """Deterministic 0–100 cash-health score (no ML).

    Blends three normalized signals over the trailing window:
    - runway      (40%): months of cash vs average burn (capped at 6 months)
    - cash flow   (30%): inflow coverage of outflow
    - reserve     (30%): cash vs average monthly outflow (capped at 3 months)
    """
    cash = float(cash_balance(company))
    series = cash_flow_by_month(company, months)
    if not series:
        return 50

    inflow_total = sum(r["inflow"] for r in series)
    outflow_total = sum(r["outflow"] for r in series)
    avg_net = sum(r["net"] for r in series) / len(series)
    avg_outflow = outflow_total / len(series)
    avg_burn = -avg_net

    if avg_burn <= 0:
        runway_signal = 1.0
    else:
        runway_signal = min((cash / avg_burn) / 6, 1.0)

    cashflow_signal = (
        1.0 if outflow_total <= 0 else min(inflow_total / outflow_total, 1.0)
    )
    reserve_signal = (
        1.0 if avg_outflow <= 0 else min((cash / avg_outflow) / 3, 1.0)
    )

    score = (0.4 * runway_signal + 0.3 * cashflow_signal + 0.3 * reserve_signal) * 100
    return max(0, min(round(score), 100))


# ---------------------------------------------------------------------------
# Expense breakdown
# ---------------------------------------------------------------------------

def expense_breakdown(company, date_from, date_to):
    """Expense totals grouped by Chart of Accounts account_type title."""
    qs = (
        ChartOfAccount.objects.get_status_all()
        .filter(
            company=company,
            kind=ChartOfAccountKindChoices.EXPENSES,
            journalentryconnector__isnull=False,
            journalentryconnector__created_at__date__range=[date_from, date_to],
        )
        .values("account_type__title")
        .annotate(
            amount=Coalesce(
                Sum("opening_balance"), ZERO, output_field=DecimalField()
            )
        )
        .order_by("-amount")
    )
    rows = [
        {
            "category": row["account_type__title"] or "Uncategorized",
            "amount": float(row["amount"]),
        }
        for row in qs
    ]
    total = sum(r["amount"] for r in rows)
    for row in rows:
        row["percent"] = round((row["amount"] / total * 100), 2) if total else 0
    return rows, total


# ---------------------------------------------------------------------------
# Top customers / products
# ---------------------------------------------------------------------------

def _customer_name(row):
    """Resolve a display name for a customer values() row.

    Customers store their name across display_name / company_name /
    first_name+last_name (there is no usable ``title``).
    """
    name = row.get("customer__display_name") or row.get("customer__company_name")
    if not name:
        first = row.get("customer__first_name") or ""
        last = row.get("customer__last_name") or ""
        name = f"{first} {last}".strip()
    return name or None


def top_customers(company, date_from, date_to, limit=5):
    qs = (
        Sale.objects.filter(
            company=company,
            status__in=LIVE_SALE_STATUSES,
            date__range=[date_from, date_to],
        )
        .filter(Q(is_invoice=True) | Q(is_sale_receipt=True))
        .values(
            "customer__uid",
            "customer__display_name",
            "customer__company_name",
            "customer__first_name",
            "customer__last_name",
        )
        .annotate(
            revenue=Coalesce(Sum("total"), ZERO, output_field=DecimalField())
        )
        .order_by("-revenue")
    )

    top = list(qs[:limit])
    # Percent is share of the displayed top-N revenue so the card's bars are
    # meaningful (a single customer's share of all-time revenue is often <1%).
    displayed_total = sum(float(row["revenue"]) for row in top)

    rows = []
    for row in top:
        revenue = float(row["revenue"])
        rows.append(
            {
                "uid": str(row["customer__uid"]) if row["customer__uid"] else None,
                "name": _customer_name(row),
                "revenue": revenue,
                "percent": round((revenue / displayed_total * 100), 2)
                if displayed_total
                else 0,
            }
        )
    return rows, displayed_total


def top_selling_products(company, date_from, date_to, limit=5):
    qs = (
        SaleItem.objects.filter(
            sale__company=company,
            sale__status__in=LIVE_SALE_STATUSES,
            sale__date__range=[date_from, date_to],
            status=SaleItemStatusChoices.PUBLISHED,
            product__isnull=False,
        )
        .values("product__uid", "product__title", "product__sku")
        .annotate(
            quantity=Coalesce(Sum(F("quantity") - F("refund_quantity")), 0),
            revenue=Coalesce(
                Sum(F("total") - F("refund_total")),
                ZERO,
                output_field=DecimalField(),
            ),
        )
        .order_by("-revenue")
    )
    rows = []
    total_revenue = ZERO
    for row in qs:
        total_revenue += Decimal(str(row["revenue"]))
    for row in qs[:limit]:
        revenue = float(row["revenue"])
        rows.append(
            {
                "uid": str(row["product__uid"]) if row["product__uid"] else None,
                "name": row["product__title"],
                "sku": row["product__sku"],
                "quantity": int(row["quantity"] or 0),
                "revenue": revenue,
                "percent": round((revenue / float(total_revenue) * 100), 2)
                if total_revenue
                else 0,
            }
        )
    return rows, float(total_revenue)
