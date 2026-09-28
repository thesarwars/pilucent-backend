from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard.envelope import compute_trend
from weapi.django_rest.helpers.dashboard import finance, hr, inventory, tax


# compute_trend directions -> frontend trendDirection
_DIRECTION_MAP = {"up": "up", "down": "down", "flat": "neutral", "new": "neutral"}


def _money(value):
    return f"${float(value or 0):,.2f}"


def _percent_trend(percent, direction):
    """Format a percentage trend like '+18.7%' / '-5.3%', or 'New'."""
    fe_direction = _DIRECTION_MAP.get(direction, "neutral")
    if percent is None:
        return "New", fe_direction
    return f"{percent:+.1f}%", fe_direction


def _days_trend(days_until):
    """Format a countdown trend like 'in 7 days' / 'today' / 'overdue'."""
    if days_until is None:
        return "—", "neutral"
    if days_until < 0:
        return "overdue", "down"
    if days_until == 0:
        return "today", "neutral"
    if days_until == 1:
        return "tomorrow", "neutral"
    return f"in {days_until} days", "neutral"


def _due_helper(due_date):
    if due_date is None:
        return "no scheduled date"
    return f"due {due_date.strftime('%b')} {due_date.day}"


class PrivateWeDashboardKpiSummaryView(DashboardCardView):
    """Card 01 — KPI Summary.

    Composite aggregator that returns the headline KPI row. Each KPI carries a
    preformatted display ``value`` + ``trend`` so the frontend can render the
    top row directly, plus ``rawValue`` for charting/sorting.
    """

    card_key = "kpi_summary"
    action_route = "/dashboard"

    def _kpis(self, request, filters):
        company = filters.company
        df, dt = filters.date_from, filters.date_to
        pdf, pdt = filters.previous_date_from, filters.previous_date_to

        kpis = []

        # 1. Total Revenue (vs previous period)
        revenue = finance.revenue_total(company, df, dt)
        prev_revenue = finance.revenue_total(company, pdf, pdt)
        trend, direction = _percent_trend(*compute_trend(revenue, prev_revenue))
        kpis.append(
            {
                "id": "revenue",
                "title": "Total Revenue",
                "value": _money(revenue),
                "rawValue": float(revenue),
                "helper": "vs last 30 days",
                "trend": trend,
                "trendDirection": direction,
                "tone": "purple",
                "action_route": "/sales/invoices",
            }
        )

        # 2. Cash Balance (trend approximated from net cash movement in period)
        cash = float(finance.cash_balance(company))
        inflow, outflow = finance.cash_in_out(company, df, dt)
        net_flow = float(inflow) - float(outflow)
        prev_cash = cash - net_flow
        trend, direction = _percent_trend(*compute_trend(cash, prev_cash))
        kpis.append(
            {
                "id": "cash",
                "title": "Cash Balance",
                "value": _money(cash),
                "rawValue": cash,
                "helper": "vs last 30 days",
                "trend": trend,
                "trendDirection": direction,
                "tone": "green",
                "action_route": "/banking/accounts",
            }
        )

        # 3. Accounts Receivable (open balance — point-in-time, no trend)
        ar = float(finance.ar_open_total(company))
        kpis.append(
            {
                "id": "ar",
                "title": "Accounts Receivable",
                "value": _money(ar),
                "rawValue": ar,
                "helper": "open balance",
                "trend": None,
                "trendDirection": "neutral",
                "tone": "blue",
                "action_route": "/sales/invoices",
            }
        )

        # 4. Accounts Payable (open supplier bills — point-in-time, no trend)
        ap = float(finance.ap_open_total(company))
        kpis.append(
            {
                "id": "ap",
                "title": "Accounts Payable",
                "value": _money(ap),
                "rawValue": ap,
                "helper": "open supplier bills",
                "trend": None,
                "trendDirection": "neutral",
                "tone": "orange",
                "action_route": "/purchases/bills",
            }
        )

        # 5. Payroll Due (upcoming run)
        payroll = hr.payroll_due(company, today=filters.today)
        trend, direction = _days_trend(payroll["days_until"])
        kpis.append(
            {
                "id": "payroll",
                "title": "Payroll Due",
                "value": _money(payroll["amount"]),
                "rawValue": payroll["amount"],
                "helper": _due_helper(payroll["due_date"]),
                "trend": trend,
                "trendDirection": direction,
                "tone": "rose",
                "action_route": "/payroll/runs",
            }
        )

        # 6. Tax Due (open sales tax + next due date)
        tax_info = tax.tax_due(company, today=filters.today)
        trend, direction = _days_trend(tax_info["days_until"])
        kpis.append(
            {
                "id": "tax",
                "title": "Tax Due",
                "value": _money(tax_info["amount"]),
                "rawValue": tax_info["amount"],
                "helper": _due_helper(tax_info["due_date"]),
                "trend": trend,
                "trendDirection": direction,
                "tone": "rose",
                "action_route": "/tax-center",
            }
        )

        # 7. Inventory Value (point-in-time, valued at unit cost)
        inv_value = float(inventory.inventory_value(company))
        kpis.append(
            {
                "id": "inventory",
                "title": "Inventory Value",
                "value": _money(inv_value),
                "rawValue": inv_value,
                "helper": "valuation at cost",
                "trend": None,
                "trendDirection": "neutral",
                "tone": "cyan",
                "action_route": "/inventory/products",
            }
        )

        # 8. Net Profit (vs previous period)
        net = finance.net_profit(company, df, dt)
        prev_net = finance.net_profit(company, pdf, pdt)
        trend, direction = _percent_trend(*compute_trend(net, prev_net))
        kpis.append(
            {
                "id": "profit",
                "title": "Net Profit",
                "value": _money(net),
                "rawValue": float(net),
                "helper": "vs last period",
                "trend": trend,
                "trendDirection": direction,
                "tone": "green",
                "action_route": "/reports/profit-and-loss",
            }
        )

        # 9. Attendance Rate (today vs yesterday)
        today_rate, yesterday_rate = hr.attendance_rate_with_trend(
            company, day=filters.today
        )
        trend, direction = _percent_trend(
            *compute_trend(today_rate, yesterday_rate)
        )
        kpis.append(
            {
                "id": "attendance",
                "title": "Attendance Rate",
                "value": f"{today_rate}%",
                "rawValue": today_rate,
                "helper": "today",
                "trend": trend,
                "trendDirection": direction,
                "tone": "green",
                "action_route": "/hr/attendance",
            }
        )

        return kpis

    def get_card_data(self, request, filters):
        # This card returns just the KPI list (no envelope wrapper). Error and
        # restricted states are still emitted as envelopes by the base view.
        return {"kpis": self._kpis(request, filters)}
