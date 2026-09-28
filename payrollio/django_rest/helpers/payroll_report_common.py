"""Shared arithmetic behind the payroll reports.

Both the by-employee summary and the details report answer the same question
from different angles -- one pivots line items against employee columns, the
other lists one row per payroll run -- so the bucketing, the sign convention,
the pre-tax resolution and the row ordering all live here rather than being
written twice and drifting apart.

Sign convention, applied by the report builders rather than here: employee
withholdings print negative, employer costs positive. Storage is positive for
both, since `net_pay = gross_pay - employee_taxes_deductions`.
"""

from collections import defaultdict
from decimal import Decimal

from payrollio.django_rest.helpers.component_labels import component_label


PAY = "PAY"
EMPLOYEE_TAXES = "EMPLOYEE_TAXES"
EMPLOYEE_DEDUCTIONS = "EMPLOYEE_DEDUCTIONS"
EMPLOYER_TAXES = "EMPLOYER_TAXES"
COMPANY_PAID_CONTRIBUTIONS = "COMPANY_PAID_CONTRIBUTIONS"

ZERO = Decimal("0.00")

# Federal lines print above state lines, in the order a payroll clerk expects.
# Anything not listed sorts after these, by label.
EMPLOYEE_TAX_ORDER = (
    "FEDERAL_INCOME_TAX",
    "SOCIAL_SECURITY",
    "MEDICARE",
    "MEDICARE_ADDITIONAL",
)
EMPLOYER_TAX_ORDER = (
    "FUTA_EMPLOYER",
    "SOCIAL_SECURITY_EMPLOYER",
    "MEDICARE_EMPLOYER",
)


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def amount_string(value):
    """The wire format: plain 2dp, no symbol, no separators."""
    return f"{value:.2f}"


def employee_label(employee):
    """"Last, First Middle" -- how the printed reports name an employee."""
    last = (employee.last_name or "").strip()
    first = " ".join(
        part
        for part in (
            (employee.first_name or "").strip(),
            (employee.middle_name or "").strip(),
        )
        if part
    )
    if last and first:
        return f"{last}, {first}"
    if last or first:
        return last or first
    user = getattr(employee, "user", None)
    return (getattr(user, "name", None) or "").strip() or "—"


def ordered_types(types, preferred):
    """Preferred codes first in their fixed order, then the rest by label.

    The remainder sorts on the printed label, not the raw code -- by code,
    `NYS_UI_EMPLOYER` precedes `NY_RSF` (``'S'`` sorts before ``'_'``) and the
    report would print "NY SUI Employer" above "NY Re-employment", the reverse
    of how a reader scans it.
    """
    known = [code for code in preferred if code in types]
    rest = sorted(
        (code for code in types if code not in preferred),
        key=lambda code: (component_label(code).lower(), code),
    )
    return known + rest


class Bucket:
    """Component totals for one grouping -- an employee, a run, or the report."""

    def __init__(self):
        self.hours_by_type = defaultdict(lambda: ZERO)
        self.pay_by_type = defaultdict(lambda: ZERO)
        self.employee_taxes = defaultdict(lambda: ZERO)
        self.employee_deductions = defaultdict(lambda: ZERO)
        self.employer_taxes = defaultdict(lambda: ZERO)
        self.employer_contributions = defaultdict(lambda: ZERO)
        self.pretax_deductions = ZERO

    def add_component(self, component, *, is_pretax):
        amount = money(component.current)
        category = component.payroll_category
        payroll_type = component.payroll_type or ""

        if category == PAY:
            self.pay_by_type[payroll_type] += amount
            hours = money(component.hours)
            if hours:
                self.hours_by_type[payroll_type] += hours
        elif category == EMPLOYEE_TAXES:
            self.employee_taxes[payroll_type] += amount
        elif category == EMPLOYEE_DEDUCTIONS:
            self.employee_deductions[payroll_type] += amount
            if is_pretax:
                self.pretax_deductions += amount
        elif category == EMPLOYER_TAXES:
            self.employer_taxes[payroll_type] += amount
        elif category == COMPANY_PAID_CONTRIBUTIONS:
            self.employer_contributions[payroll_type] += amount

    @property
    def gross(self):
        return sum(self.pay_by_type.values(), ZERO)

    @property
    def adjusted_gross(self):
        return self.gross - self.pretax_deductions

    @property
    def total_hours(self):
        return sum(self.hours_by_type.values(), ZERO)

    @property
    def employee_tax_total(self):
        return sum(self.employee_taxes.values(), ZERO)

    @property
    def employee_deduction_total(self):
        return sum(self.employee_deductions.values(), ZERO)

    @property
    def employee_withheld_total(self):
        return self.employee_tax_total + self.employee_deduction_total

    @property
    def employer_tax_total(self):
        return sum(self.employer_taxes.values(), ZERO)

    @property
    def employer_contribution_total(self):
        return sum(self.employer_contributions.values(), ZERO)

    @property
    def employer_cost_total(self):
        return self.employer_tax_total + self.employer_contribution_total

    @property
    def net_pay(self):
        return self.gross - self.employee_withheld_total

    @property
    def total_payroll_cost(self):
        return self.gross + self.employer_cost_total


def normalize_name(value):
    return "".join(
        character for character in str(value or "").lower() if character.isalnum()
    )


# Below this length a substring match is noise -- "hsa" would hit any setup name
# containing those three letters.
_MIN_MATCH_LENGTH = 4


def is_pretax(payroll_type, pretax_names):
    """Does this component correspond to one of the company's pre-tax setups?

    Component names and setup names are entered independently, so exact
    equality misses the common cases: a `Health` component against a
    `Health Insurance` setup, or `Vision Plan` against sub-type `vision`. Either
    containing the other is treated as the same deduction.
    """
    if not pretax_names:
        return False
    name = normalize_name(payroll_type)
    if len(name) < _MIN_MATCH_LENGTH:
        return False
    for candidate in pretax_names:
        if name == candidate or name in candidate or candidate in name:
            return True
    return False


def resolve_pretax_deduction_names(company):
    """Normalized names of the company's pre-tax deduction setups.

    `PayrollSalaryComponent` records only a free-text `payroll_type` ("Health",
    "Vision Plan"), with no link back to the `DeductionAndContributions` row it
    came from and no pre-tax flag of its own. Matching on the normalized name is
    the only join available, so a deduction whose component was labelled
    differently from its setup counts as post-tax. That direction is the safe
    one: "Adjusted gross" can equal gross, but it can never subtract a deduction
    that was actually post-tax.
    """
    from payrollio.models import DeductionAndContributions

    names = set()
    rows = DeductionAndContributions.objects.filter(
        company=company, tax_type="PRETAX"
    ).values_list("deduction_type", "sub_type")
    for deduction_type, sub_type in rows:
        for value in (deduction_type, sub_type):
            normalized = normalize_name(value)
            if normalized:
                names.add(normalized)
    return names
