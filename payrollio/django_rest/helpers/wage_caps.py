"""Federal payroll wage-base / threshold tax tables and clamp helper.

These constants encode the IRS-published wage bases and rates used to bound
Social Security, FUTA, and Additional Medicare withholdings. Each year is a
snapshot — the current run's `pay_date.year` selects which table applies, so
a check dated 2026-01-03 for late-2025 work uses the 2026 numbers (per IRS
"pay date governs" rule).

State unemployment caps are intentionally NOT included here — wage bases
vary per state and per year and should live alongside state tax setup.

Currency: all values are USD `Decimal` to avoid float drift in tax math.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional


_TWO_DP = Decimal("0.01")


@dataclass(frozen=True)
class WageBase:
    """Tax bound configuration.

    Exactly one of `wage_base` (capped-style: rate applies up to ceiling)
    or `threshold` (additional-style: rate applies *above* a floor) is set.
    """

    rate: Decimal
    wage_base: Optional[Decimal] = None
    threshold: Optional[Decimal] = None


# IRS-published values. Add a new year here at year-end after Treasury
# publishes the updated SSA wage base; nothing else needs to change.
TAX_TABLE: dict[int, dict[str, WageBase]] = {
    2024: {
        "SOCIAL_SECURITY": WageBase(rate=Decimal("0.062"), wage_base=Decimal("168600")),
        "SOCIAL_SECURITY_EMPLOYER": WageBase(rate=Decimal("0.062"), wage_base=Decimal("168600")),
        "FUTA_EMPLOYER": WageBase(rate=Decimal("0.006"), wage_base=Decimal("7000")),
        # Additional Medicare: 0.9% on YTD wages above $200,000 (single filer).
        # Employer does not match.
        "MEDICARE_ADDITIONAL": WageBase(rate=Decimal("0.009"), threshold=Decimal("200000")),
    },
    2025: {
        "SOCIAL_SECURITY": WageBase(rate=Decimal("0.062"), wage_base=Decimal("176100")),
        "SOCIAL_SECURITY_EMPLOYER": WageBase(rate=Decimal("0.062"), wage_base=Decimal("176100")),
        "FUTA_EMPLOYER": WageBase(rate=Decimal("0.006"), wage_base=Decimal("7000")),
        "MEDICARE_ADDITIONAL": WageBase(rate=Decimal("0.009"), threshold=Decimal("200000")),
    },
    2026: {
        "SOCIAL_SECURITY": WageBase(rate=Decimal("0.062"), wage_base=Decimal("184500")),
        "SOCIAL_SECURITY_EMPLOYER": WageBase(rate=Decimal("0.062"), wage_base=Decimal("184500")),
        "FUTA_EMPLOYER": WageBase(rate=Decimal("0.006"), wage_base=Decimal("7000")),
        "MEDICARE_ADDITIONAL": WageBase(rate=Decimal("0.009"), threshold=Decimal("200000")),
    },
}

DEFAULT_TAX_YEAR = 2026  # most-recent-known fallback


def get_wage_base(year: int, payroll_type: str) -> Optional[WageBase]:
    """Look up the tax-cap config for `(year, payroll_type)`.

    Returns `None` for uncapped or unknown payroll types — caller should
    leave their `current` value as-is.
    """
    table = TAX_TABLE.get(year) or TAX_TABLE[DEFAULT_TAX_YEAR]
    return table.get(payroll_type)


def correct_tax_for_component(
    payroll_type: str,
    *,
    taxable_wages_this_run: Decimal,
    ytd_taxable_wages: Decimal,
    year: int,
) -> Optional[Decimal]:
    """Return the cap-/threshold-aware tax this component *should* be.

    Returns `None` for uncapped payroll types.

    Capped (SS/FUTA): only the wages in `[0, wage_base - prior_YTD]`
    contribute. Above the wage base, contribution is 0.

    Threshold (Additional Medicare): only wages *above* `threshold` are
    taxed, with no upper cap. Splits cleanly across pay periods because we
    keep YTD-aware accounting.
    """
    base = get_wage_base(year, payroll_type)
    if base is None:
        return None

    if base.wage_base is not None:
        remaining = max(Decimal("0"), base.wage_base - ytd_taxable_wages)
        taxable = min(taxable_wages_this_run, remaining)
    elif base.threshold is not None:
        new_ytd = ytd_taxable_wages + taxable_wages_this_run
        if new_ytd <= base.threshold:
            taxable = Decimal("0")
        else:
            already_over = max(Decimal("0"), ytd_taxable_wages - base.threshold)
            now_over = new_ytd - base.threshold
            taxable = now_over - already_over
    else:
        return None

    return (taxable * base.rate).quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _sum_pay_components(components: Iterable[dict]) -> Decimal:
    """Sum `current` for components in the PAY category (taxable wages)."""
    total = Decimal("0")
    for c in components:
        if c.get("payroll_category") == "PAY":
            total += Decimal(str(c.get("current", 0) or 0))
    return total


def clamp_payroll_components(
    components: list,
    *,
    employee,
    pay_date,
    exclude_process_id=None,
) -> list:
    """Mutate the in-flight component list to respect federal wage caps.

    For each capped/thresholded payroll_type (`SOCIAL_SECURITY`,
    `SOCIAL_SECURITY_EMPLOYER`, `FUTA_EMPLOYER`, `MEDICARE_ADDITIONAL`):
      1. Compute what the value *should* be given YTD taxable wages and the
         current run's PAY total.
      2. If the frontend sent more than that, silently clamp down to the
         correct amount. Server is source of truth.

    Never raises the value — the frontend's number reflects what was actually
    withheld, and we trust it when it's *under* the cap (employer may have
    a lower internal rate, etc.). Only over-cap values get corrected.

    Returns the same list (also mutated in place) for ergonomic chaining.
    """
    # Lazy import to dodge any circular: ytd helper imports wage_caps
    # transitively only via tests.
    from .ytd import previous_ytd_taxable_wages

    year = pay_date.year
    taxable_this_run = _sum_pay_components(components)
    ytd_taxable = previous_ytd_taxable_wages(
        employee, year, exclude_process_id=exclude_process_id
    )

    for component in components:
        payroll_type = component.get("payroll_type") or ""
        correct = correct_tax_for_component(
            payroll_type,
            taxable_wages_this_run=taxable_this_run,
            ytd_taxable_wages=ytd_taxable,
            year=year,
        )
        if correct is None:
            continue

        sent = Decimal(str(component.get("current", 0) or 0))
        if sent > correct:
            component["current"] = correct

    return components
