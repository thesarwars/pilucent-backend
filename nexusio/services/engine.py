"""The economic-nexus calculation engine — pure functions, no DB.

Given a state rule + aggregated activity + today, resolve the measurement
window, evaluate the threshold verdict under the state's combination logic, and
derive the four-value display status. Mirrors the module spec §12 / tech guide §9
exactly (``>=`` tests; AND states require BOTH; a high transaction count alone
never establishes nexus in an AND state).
"""

from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from nexusio.choices import (
    NexusCombinationLogicChoices,
    NexusIncludableSalesBasisChoices,
    NexusMeasurementPeriodChoices,
    NexusStatusChoices,
)

DEFAULT_WARNING_FRACTION = Decimal("0.80")


def resolve_windows(period_type, today):
    """The measurement window(s) for a period type as of ``today``.

    Returns a LIST of (start, end) spans. ``CURRENT_OR_PREVIOUS_YEAR`` returns
    TWO separate annual windows — the prior full calendar year and the current
    year-to-date — because the legal test is "crossed in the current OR the prior
    calendar year" (each year evaluated on its own, then OR'd). Summing both into
    one span would falsely trigger nexus when neither year individually crosses.
    """
    year = today.year
    if period_type == NexusMeasurementPeriodChoices.CURRENT_YEAR:
        return [(date(year, 1, 1), today)]
    if period_type == NexusMeasurementPeriodChoices.PREVIOUS_YEAR:
        return [(date(year - 1, 1, 1), date(year - 1, 12, 31))]
    if period_type == NexusMeasurementPeriodChoices.CURRENT_OR_PREVIOUS_YEAR:
        return [
            (date(year - 1, 1, 1), date(year - 1, 12, 31)),  # prior full year
            (date(year, 1, 1), today),  # current year-to-date
        ]
    if period_type == NexusMeasurementPeriodChoices.TRAILING_12M:
        return [(today - relativedelta(months=12) + timedelta(days=1), today)]
    # Unknown type -> two-year OR, the safe general case.
    return [
        (date(year - 1, 1, 1), date(year - 1, 12, 31)),
        (date(year, 1, 1), today),
    ]


def basis_amount(agg, basis):
    """The sales figure that counts toward the dollar threshold for a basis.

    ``agg`` carries ``gross`` and ``taxable``. Balanzify has no for-resale flag,
    so RETAIL (which only excludes resale) is treated as GROSS — documented; the
    only true distinction available is TAXABLE (``SaleItem.is_tax``).
    """
    if basis == NexusIncludableSalesBasisChoices.TAXABLE:
        return Decimal(str(agg.get("taxable") or 0))
    return Decimal(str(agg.get("gross") or 0))  # GROSS and RETAIL


def _can_txn_trigger(rule):
    """True where the transaction count can independently drive nexus.

    Only OR states with a transaction test; in an AND state the count alone never
    triggers, so it must not raise an 'approaching' on its own.
    """
    return (
        rule.txn_threshold is not None
        and rule.combination_logic == NexusCombinationLogicChoices.OR
    )


def evaluate(agg, rule):
    """Apply the state's combination logic to the aggregates.

    Returns a dict with ``met``, ``met_by_sales``, ``met_by_txn``, the chosen
    ``sales_basis`` amount, ``txn_count``, and the two percentages.
    """
    sales = basis_amount(agg, rule.includable_sales_basis)
    txns = int(agg.get("count") or 0)

    met_by_sales = rule.sales_threshold is not None and sales >= rule.sales_threshold
    met_by_txn = rule.txn_threshold is not None and txns >= rule.txn_threshold

    logic = rule.combination_logic
    if logic == NexusCombinationLogicChoices.SALES_ONLY:
        met = met_by_sales
    elif logic == NexusCombinationLogicChoices.OR:
        met = met_by_sales or met_by_txn
    elif logic == NexusCombinationLogicChoices.AND:
        met = met_by_sales and met_by_txn
    else:  # NONE (no sales tax)
        met = False

    pct_sales = (
        (sales / rule.sales_threshold) if rule.sales_threshold else Decimal("0")
    )
    pct_txn = (
        (Decimal(txns) / rule.txn_threshold) if rule.txn_threshold else None
    )
    return {
        "met": met,
        "met_by_sales": met_by_sales,
        "met_by_txn": met_by_txn,
        "sales_basis": sales,
        "txn_count": txns,
        "pct_sales": pct_sales,
        "pct_txn": pct_txn,
    }


def derive_status(ev, rule, registered=False, warning_fraction=DEFAULT_WARNING_FRACTION):
    """Translate the verdict + registration into the dashboard's display status."""
    if rule.combination_logic == NexusCombinationLogicChoices.NONE:
        return NexusStatusChoices.NOT_APPLICABLE
    if registered:
        return NexusStatusChoices.REGISTERED
    if ev["met"]:
        return NexusStatusChoices.MET

    approaching_by_sales = ev["pct_sales"] >= warning_fraction
    approaching_by_txn = (
        ev["pct_txn"] is not None
        and _can_txn_trigger(rule)
        and ev["pct_txn"] >= warning_fraction
    )
    if approaching_by_sales or approaching_by_txn:
        return NexusStatusChoices.APPROACHING
    return NexusStatusChoices.NOT_APPROACHING
