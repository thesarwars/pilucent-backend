from datetime import timedelta

from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


# Runway is normalized to this many months for the radial gauge (>= this = 100%).
RUNWAY_TARGET_MONTHS = 12
DAYS_PER_MONTH = 30.44


class PrivateWeDashboardCashRunwayView(DashboardCardView):
    """Card 25 — Cash Runway.

    Runway = current cash / average monthly net burn (outflow − inflow) over the
    trailing window. When the business is cash-flow positive there is no finite
    runway. Returns the gauge-shaped payload directly; error/restricted states
    are still emitted as envelopes by the base view.
    """

    card_key = "cash_runway"
    action_route = "/banking/accounts"
    BURN_WINDOW_MONTHS = 6

    def get_card_data(self, request, filters):
        cash = float(finance.cash_balance(filters.company))
        series = finance.cash_flow_by_month(filters.company, self.BURN_WINDOW_MONTHS)

        count = len(series) or 1
        avg_inflow = sum(r["inflow"] for r in series) / count
        avg_outflow = sum(r["outflow"] for r in series) / count
        net_burn = avg_outflow - avg_inflow

        if net_burn > 0:
            runway = cash / net_burn
            months = f"{runway:.1f} months"
            until_date = filters.today + timedelta(days=runway * DAYS_PER_MONTH)
            until = f"Until {until_date.strftime('%b %d, %Y')}"
            radial = min(round(runway / RUNWAY_TARGET_MONTHS * 100), 100)
        else:
            months = "Stable"
            until = "Cash flow positive"
            radial = 100

        burn_percent = (
            min(round(avg_outflow / avg_inflow * 100), 100) if avg_inflow else 0
        )

        return {
            "months": months,
            "untilDate": until,
            "radialValue": radial,
            "monthlyBurn": f"${avg_outflow:,.2f}",
            "burnPercent": burn_percent,
        }
