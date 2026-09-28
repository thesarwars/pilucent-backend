"""Global dashboard filter state shared by every v2 card.

Per the dashboard spec (section 4), every card reads the same filter inputs so
numbers stay consistent: company, date range, comparison period, currency, and
accounting basis. Branch/location is intentionally omitted because there is no
branch model in the data layer yet (see plan section 6.4).
"""

from datetime import date, datetime, timedelta


DEFAULT_WINDOW_DAYS = 30


def _parse_date(raw):
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except (TypeError, ValueError):
            continue
    return None


class DashboardFilters:
    """Resolved, validated global filter state for a single request."""

    def __init__(
        self,
        company,
        date_from,
        date_to,
        currency=None,
        accounting_basis="accrual",
        comparison_period="previous_period",
    ):
        self.company = company
        self.date_from = date_from
        self.date_to = date_to
        self.currency = currency
        self.accounting_basis = accounting_basis
        self.comparison_period = comparison_period
        self.today = date.today()

        # Previous matching period: the equally long window immediately before
        # the selected range. Used for trend / comparison values.
        window = (self.date_to - self.date_from).days
        self.previous_date_to = self.date_from - timedelta(days=1)
        self.previous_date_from = self.previous_date_to - timedelta(days=window)

    @property
    def date_range(self):
        return [self.date_from, self.date_to]

    @property
    def previous_date_range(self):
        return [self.previous_date_from, self.previous_date_to]

    def as_dict(self):
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "comparison_period": self.comparison_period,
            "currency": self.currency,
            "accounting_basis": self.accounting_basis,
        }


def build_filters(request):
    """Build a :class:`DashboardFilters` from the request query params.

    Accepts both ``date_from``/``date_to`` and the v1-style
    ``start_date``/``end_date`` aliases. Defaults to a trailing 30-day window
    ending today.
    """
    user = request.user
    company = user.get_active_company() if not user.is_anonymous else None

    params = request.query_params
    date_to = _parse_date(params.get("date_to") or params.get("end_date"))
    date_from = _parse_date(params.get("date_from") or params.get("start_date"))

    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    return DashboardFilters(
        company=company,
        date_from=date_from,
        date_to=date_to,
        currency=params.get("currency"),
        accounting_basis=params.get("accounting_basis", "accrual"),
        comparison_period=params.get("comparison_period", "previous_period"),
    )
