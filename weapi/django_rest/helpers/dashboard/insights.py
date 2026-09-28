"""Deterministic rules engine for the AI Business Insights card (card 05).

No ML/model is involved: insights are derived from existing data via explicit
business rules so results are explainable and reproducible. Each insight is
shaped for the frontend as:

    {title, message, action, severity, type, action_route}

severity is one of: critical | high | medium | info
type is one of:    invoice | bill | inventory | payroll | tax | forecast
"""

from datetime import timedelta

from django.db.models import Count, Sum, DecimalField
from django.db.models.functions import Coalesce

from .finance import open_invoices_qs, open_bills_qs, cash_balance, cash_flow_by_month, ZERO
from .inventory import low_stock_items
from .tax import tax_due
from .hr import payroll_due


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}

CASH_RUNWAY_CRITICAL_MONTHS = 1
CASH_RUNWAY_WARNING_MONTHS = 3
PAYROLL_DUE_WINDOW_DAYS = 14
TAX_DUE_WINDOW_DAYS = 30


def _money(value):
    return f"${float(value or 0):,.2f}"


def _date(value):
    return value.strftime("%b %d, %Y") if value else None


def generate_insights(company, filters):
    insights = []
    today = filters.today

    # 1. Overdue invoices (AR past due).
    overdue_inv = open_invoices_qs(company).filter(due_date__lt=today)
    inv_agg = overdue_inv.aggregate(
        count=Count("id"),
        amount=Coalesce(Sum("due_total"), ZERO, output_field=DecimalField()),
        customers=Count("customer", distinct=True),
    )
    if inv_agg["count"]:
        insights.append(
            {
                "title": f"{inv_agg['count']} overdue invoice"
                + ("s" if inv_agg["count"] != 1 else ""),
                "message": f"Total {_money(inv_agg['amount'])} from "
                f"{inv_agg['customers']} customer"
                + ("s" if inv_agg["customers"] != 1 else ""),
                "action": "View invoices",
                "severity": "critical",
                "type": "invoice",
                "action_route": "/sales/invoices",
            }
        )

    # 2. Overdue bills (AP past due).
    overdue_bills = open_bills_qs(company).filter(due_date__lt=today)
    bill_agg = overdue_bills.aggregate(
        count=Count("id"),
        amount=Coalesce(Sum("due_total"), ZERO, output_field=DecimalField()),
    )
    if bill_agg["count"]:
        insights.append(
            {
                "title": f"{bill_agg['count']} overdue bill"
                + ("s" if bill_agg["count"] != 1 else ""),
                "message": f"Total {_money(bill_agg['amount'])} owed to suppliers",
                "action": "View bills",
                "severity": "high",
                "type": "bill",
                "action_route": "/purchases/bills",
            }
        )

    # 3. Low stock.
    low_stock_count = low_stock_items(company).count()
    if low_stock_count:
        insights.append(
            {
                "title": f"{low_stock_count} low-stock item"
                + ("s" if low_stock_count != 1 else ""),
                "message": "Reorder soon to avoid stockouts",
                "action": "View inventory",
                "severity": "high",
                "type": "inventory",
                "action_route": "/inventory/products",
            }
        )

    # 4. Payroll due soon.
    payroll = payroll_due(company, today=today)
    if (
        payroll["amount"] > 0
        and payroll["due_date"] is not None
        and payroll["days_until"] is not None
        and payroll["days_until"] <= PAYROLL_DUE_WINDOW_DAYS
    ):
        insights.append(
            {
                "title": "Payroll due soon",
                "message": f"{_money(payroll['amount'])} due on {_date(payroll['due_date'])}",
                "action": "Run payroll",
                "severity": "medium",
                "type": "payroll",
                "action_route": "/payroll/runs",
            }
        )

    # 5. Tax filing due.
    tax = tax_due(company, today=today)
    if (
        tax["amount"] > 0
        and tax["due_date"] is not None
        and tax["days_until"] is not None
        and tax["days_until"] <= TAX_DUE_WINDOW_DAYS
    ):
        severity = "high" if tax["days_until"] < 0 else "medium"
        insights.append(
            {
                "title": "Tax filing due",
                "message": f"{_money(tax['amount'])} due on {_date(tax['due_date'])}",
                "action": "Tax center",
                "severity": severity,
                "type": "tax",
                "action_route": "/tax-center",
            }
        )

    # 6. Cash flow forecast.
    cash = float(cash_balance(company))
    series = cash_flow_by_month(company, 6)
    nets = [row["net"] for row in series]
    avg_net = sum(nets) / len(nets) if nets else 0
    avg_burn = -avg_net
    if avg_burn > 0:
        runway = cash / avg_burn
        projected = cash - avg_burn  # ~one month out
        forecast_date = today + timedelta(days=30)
        if runway < CASH_RUNWAY_CRITICAL_MONTHS:
            severity = "critical"
        elif runway < CASH_RUNWAY_WARNING_MONTHS:
            severity = "high"
        else:
            severity = "info"
        insights.append(
            {
                "title": "Cash flow forecast",
                "message": f"Cash may dip to {_money(projected)} by {_date(forecast_date)}",
                "action": "View forecast",
                "severity": severity,
                "type": "forecast",
                "action_route": "/banking/accounts",
            }
        )

    insights.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 99))
    return insights
