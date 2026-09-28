"""Year-to-Date (YTD) computation helpers for payroll.

Authoritative source for the `ytd` column on `PayrollSalaryComponent`. All
queries:
  - Filter by `payroll__pay_date__year` (NOT `created_at.year` — IRS
    "pay-date governs" rule, so a check dated 2026-01-03 for late-2025 work
    counts toward 2026 YTD).
  - Restrict to FINALIZED runs only. DRAFT runs aren't yet posted; VOIDED
    runs have been reversed and their amounts must NOT count toward YTD,
    which is precisely why voiding a run automatically subtracts from
    cumulative totals (no separate reversal accounting needed).
  - Optionally exclude one parent run via `exclude_process_id` so we don't
    double-count the very run we're re-saving.
"""

from decimal import Decimal
from typing import Optional

from django.db.models import Sum
from django.db.models.functions import Coalesce


def _finalized_qs():
    """Manager-style queryset filtered to FINALIZED parent runs."""
    # Local imports avoid an import cycle with payrollio.models -> choicess.
    from payrollio.choicess import PayrollSalaryProcessStatusChoices
    from payrollio.models import PayrollSalaryComponent

    return PayrollSalaryComponent.objects.filter(
        payroll__status=PayrollSalaryProcessStatusChoices.FINALIZED,
    )


def previous_ytd_taxable_wages(
    employee,
    year: int,
    *,
    exclude_process_id: Optional[int] = None,
) -> Decimal:
    """Sum of PAY-category `current` for `employee` in `year`, FINALIZED only.

    "Taxable wages" here uses the PAY category as the wage base. If you
    later distinguish pretax-deductible wages, narrow this filter — or add
    a sibling helper that excludes 401(k) etc. Caller passes the result to
    `correct_tax_for_component` for SS/FUTA cap math.
    """
    qs = _finalized_qs().filter(
        payroll__employee=employee,
        payroll__pay_date__year=year,
        payroll_category="PAY",
    )
    if exclude_process_id is not None:
        qs = qs.exclude(payroll_id=exclude_process_id)

    return qs.aggregate(
        total=Coalesce(Sum("current"), Decimal("0")),
    )["total"]


def previous_ytd_for_type(
    employee,
    payroll_type: str,
    year: int,
    *,
    exclude_process_id: Optional[int] = None,
) -> Decimal:
    """Sum of `current` for one `payroll_type` (e.g. "SOCIAL_SECURITY").

    This drives the per-row `ytd` column the frontend renders next to
    `current` on the payslip.
    """
    qs = _finalized_qs().filter(
        payroll__employee=employee,
        payroll__pay_date__year=year,
        payroll_type=payroll_type,
    )
    if exclude_process_id is not None:
        qs = qs.exclude(payroll_id=exclude_process_id)

    return qs.aggregate(
        total=Coalesce(Sum("current"), Decimal("0")),
    )["total"]


def compute_component_ytd(component, *, exclude_process_id: Optional[int] = None):
    """Set `component.ytd = previous YTD for this type + this run's current`.

    Returns the component (also mutated in place). Does NOT call `.save()`
    — the caller decides when to persist, so this can be invoked on
    unsaved instances inside a single transaction.

    Pass `exclude_process_id=component.payroll_id` when re-saving a
    previously-FINALIZED component so the helper doesn't double-count it
    against itself.
    """
    employee = component.payroll.employee
    pay_date = component.payroll.pay_date
    if employee is None or pay_date is None:
        # Defensive: should never happen — Process.pay_date is non-null in
        # the schema. If it does, leave ytd untouched rather than crash.
        return component

    previous = previous_ytd_for_type(
        employee,
        component.payroll_type,
        pay_date.year,
        exclude_process_id=exclude_process_id,
    )
    current = Decimal(str(component.current or 0))
    component.ytd = previous + current
    return component
