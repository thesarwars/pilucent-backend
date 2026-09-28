"""Rollup helpers — sum component totals onto their parent payroll run.

Lives next to `wage_caps.py` and `ytd.py` because the three are part of the
same write-time pipeline: clamp capped taxes → write per-component YTD →
re-sum totals onto the parent so it agrees with its children.
"""

from decimal import Decimal

from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money


_PAY_CATEGORY = "PAY"
_EMPLOYEE_TAX_CATEGORIES = ("EMPLOYEE_TAXES", "EMPLOYEE_DEDUCTIONS")
_EMPLOYER_TAX_CATEGORIES = ("EMPLOYER_TAXES", "COMPANY_PAID_CONTRIBUTIONS")
_ALL_CATEGORIES = (
    (_PAY_CATEGORY,)
    + _EMPLOYEE_TAX_CATEGORIES
    + _EMPLOYER_TAX_CATEGORIES
)


def recompute_parent_totals(payroll_instance):
    """Re-roll `gross_pay` / taxes / `net_pay` from saved components.

    Required after clamping. If SS/FUTA was lowered on a child, the parent
    `employee_taxes_deductions` must drop and `net_pay` must rise — otherwise
    parent and children disagree and the payslip shows inconsistent numbers.
    Uses `update_fields` so unrelated columns aren't clobbered.
    """
    bucket = {category: Decimal("0.00") for category in _ALL_CATEGORIES}
    for component in payroll_instance.payroll_components.all():
        if component.payroll_category in bucket:
            bucket[component.payroll_category] += quantize_money(
                component.current or 0
            )

    payroll_instance.gross_pay = quantize_money(bucket[_PAY_CATEGORY])
    payroll_instance.employee_taxes_deductions = quantize_money(
        sum((bucket[k] for k in _EMPLOYEE_TAX_CATEGORIES), Decimal("0.00"))
    )
    payroll_instance.employer_taxes_contributions = quantize_money(
        sum((bucket[k] for k in _EMPLOYER_TAX_CATEGORIES), Decimal("0.00"))
    )
    payroll_instance.net_pay = quantize_money(
        payroll_instance.gross_pay - payroll_instance.employee_taxes_deductions
    )
    payroll_instance.save(
        update_fields=[
            "gross_pay",
            "employee_taxes_deductions",
            "employer_taxes_contributions",
            "net_pay",
        ]
    )
