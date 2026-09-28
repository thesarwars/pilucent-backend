"""Build the "Payroll tax and wage summary" report.

Same filing groups as the tax liability report -- it reuses that module's
grouping outright -- but answers a different question per line: not "what do we
owe", but "what wages was this tax charged on, and how much was over the cap".

    total wages = excess wages + taxable wages

**Excess is per employee and year-to-date, not per range.** A wage base is an
annual, per-person ceiling: once someone's wages for the year pass the FUTA base
of $7,000, every later dollar is excess. So a range covering only their December
pay shows the whole amount as excess even though the range itself is under the
base -- which is exactly what the reference report prints. Computing it against
range wages alone would report tax due on wages already exhausted.

Wage bases come from two places, because the codebase deliberately splits them:
`wage_caps.TAX_TABLE` holds the federal ones, and state unemployment bases live
in each state's `PayrollTaxConfig` blob (`wage_caps` says so explicitly -- state
bases "vary per state and per year and should live alongside state tax setup").
Anything with no resolvable base is treated as uncapped, so its wages are fully
taxable -- the safe direction, since it never invents an exemption.
"""

from decimal import Decimal

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    normalize_us_state,
)
from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_report_common import (
    EMPLOYEE_TAXES,
    EMPLOYER_TAXES,
    PAY,
    ZERO,
    amount_string,
    money,
)
from payrollio.django_rest.helpers.payroll_tax_liability import (
    known_groups,
    member_order,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    payroll_types_for_group,
)
from payrollio.django_rest.helpers.wage_caps import get_wage_base


COLUMNS = [
    {"key": "tax_type", "label": "Tax types", "align": "left"},
    {"key": "total_wages", "label": "Total wages", "align": "right"},
    {"key": "excess_wages", "label": "Excess wages", "align": "right"},
    {"key": "taxable_wages", "label": "Taxable wages", "align": "right"},
    {"key": "tax_amount", "label": "Tax amount", "align": "right"},
]

_TAX_CATEGORIES = (EMPLOYEE_TAXES, EMPLOYER_TAXES)

# Suffixes marking a state unemployment-style tax, whose base is per-state.
_STATE_UI_SUFFIXES = ("_UI_EMPLOYER", "_SUI_EMPLOYER", "_UNEMPLOYMENT_TAXES",
                      "_REEMPLOYMENT_TAX", "_RSF", "_EMPLOYMENT_TAXES")


def _config_wage_base(config_data, kind):
    """Pull a wage base out of a state's `PayrollTaxConfig` blob.

    Key naming is not consistent across states -- NY and MN put `uiWageBase` at
    the top level, while others nest it as `{state}UI.wageBase`. Both shapes are
    checked rather than assuming one.
    """
    if not isinstance(config_data, dict):
        return None

    direct = {"ui": ("uiWageBase",), "paid_leave": ("paidLeaveWageBase",)}
    for key in direct.get(kind, ()):
        value = config_data.get(key)
        if value:
            return Decimal(str(value))

    if kind != "ui":
        return None
    for key, value in config_data.items():
        if key.lower().endswith("ui") and isinstance(value, dict):
            base = value.get("wageBase")
            if base:
                return Decimal(str(base))
    return None


def state_of(payroll_type):
    """The USPS code a state tax belongs to, from its own prefix.

    Codes are not uniform -- New York appears as both `NY_RSF` and
    `NYS_UI_EMPLOYER` -- so a three-letter prefix ending in S is retried as its
    first two letters.
    """
    head = (payroll_type or "").split("_")[0].upper()
    # Return the *normalized* code, not the raw prefix: "NYS" is an alias that
    # resolves to "NY", and handing back "NYS" would miss the NY config.
    normalized = normalize_us_state(head)
    if normalized:
        return normalized
    if len(head) == 3 and head.endswith("S"):
        return normalize_us_state(head[:2])
    return None


def resolve_wage_base(payroll_type, *, year, state_config=None, state_configs=None):
    """The annual per-employee ceiling for a tax, or None when uncapped.

    Federal bases are authoritative and come first. A state tax uses **its own**
    state's config, not the company's home state -- a Minnesota company running
    NY payroll would otherwise charge NY unemployment against Minnesota's wage
    base, which production actually did before `state_configs` existed.
    `state_config` remains as the single-state fallback.
    """
    federal = get_wage_base(year, payroll_type)
    if federal is not None and federal.wage_base:
        return federal.wage_base

    configs = state_configs or {}
    own_state = state_of(payroll_type)
    config = configs.get(own_state) if own_state else None
    if config is None:
        config = state_config

    if any(payroll_type.endswith(suffix) for suffix in _STATE_UI_SUFFIXES):
        return _config_wage_base(config, "ui")
    if payroll_type.endswith("_PAID_LEAVE") or payroll_type.endswith(
        "_PAID_LEAVE_EMPLOYER"
    ):
        return _config_wage_base(config, "paid_leave")
    return None


def _wage_split(wage_base, prior_wages, range_wages):
    """(taxable, excess) for one employee against an annual ceiling."""
    if wage_base is None:
        return range_wages, ZERO
    remaining = wage_base - prior_wages
    if remaining <= ZERO:
        return ZERO, range_wages
    taxable = min(range_wages, remaining)
    return taxable, range_wages - taxable


def collect_wage_facts(payrolls):
    """Per-employee wages in range, plus which taxes each employee incurred.

    Returns `(range_wages_by_employee, tax_totals, employees_by_tax)`.
    """
    range_wages = {}
    tax_totals = {}
    employees_by_tax = {}

    for payroll in payrolls:
        employee_id = payroll.employee_id
        for component in payroll.payroll_components.all():
            category = component.payroll_category
            amount = money(component.current)
            if category == PAY:
                range_wages[employee_id] = (
                    range_wages.get(employee_id, ZERO) + amount
                )
            elif category in _TAX_CATEGORIES:
                payroll_type = component.payroll_type or ""
                tax_totals[payroll_type] = (
                    tax_totals.get(payroll_type, ZERO) + amount
                )
                employees_by_tax.setdefault(payroll_type, set()).add(employee_id)

    return range_wages, tax_totals, employees_by_tax


def build_tax_and_wage_summary(
    payrolls,
    *,
    state_code=None,
    year=None,
    prior_wages=None,
    state_config=None,
    state_configs=None,
):
    """Group taxes with their wage bases.

    `prior_wages` maps employee id -> wages earlier in the same year, before the
    range. Omit it and every employee is treated as starting the year at zero,
    which understates excess wages -- see `resolve_prior_wages`.
    """
    prior_wages = prior_wages or {}
    range_wages, tax_totals, employees_by_tax = collect_wage_facts(payrolls)
    claimed = set()
    rows = []

    def line(payroll_type):
        """Wage columns for one tax, summed over the employees who incurred it."""
        wage_base = resolve_wage_base(
            payroll_type,
            year=year,
            state_config=state_config,
            state_configs=state_configs,
        )
        total = ZERO
        taxable = ZERO
        excess = ZERO
        for employee_id in employees_by_tax.get(payroll_type, ()):
            employee_wages = range_wages.get(employee_id, ZERO)
            total += employee_wages
            employee_taxable, employee_excess = _wage_split(
                wage_base, prior_wages.get(employee_id, ZERO), employee_wages
            )
            taxable += employee_taxable
            excess += employee_excess
        return {
            "key": payroll_type,
            "label": component_label(payroll_type),
            "is_group": False,
            "total_wages": amount_string(total),
            "excess_wages": amount_string(excess),
            # taxable + excess == total by construction, per employee.
            "taxable_wages": amount_string(taxable),
            "tax_amount": amount_string(tax_totals.get(payroll_type, ZERO)),
        }

    def group_row(key, label, amount):
        # Wage columns are blank on a group: summing them across taxes charged
        # on the same wages would double-count the payroll.
        return {
            "key": key,
            "label": label,
            "is_group": True,
            "total_wages": None,
            "excess_wages": None,
            "taxable_wages": None,
            "tax_amount": amount_string(amount),
        }

    for group_key, group_label in known_groups(state_code, set(tax_totals)):
        members = [
            payroll_type
            for payroll_type in payroll_types_for_group(group_key)
            if payroll_type in tax_totals and payroll_type not in claimed
        ]
        if not members:
            continue
        members = member_order(group_key, members)
        group_total = sum(
            (tax_totals[payroll_type] for payroll_type in members), ZERO
        )
        rows.append(group_row(group_key, group_label, group_total))
        for payroll_type in members:
            row = line(payroll_type)
            row["key"] = f"{group_key}.{payroll_type}"
            rows.append(row)
        claimed.update(members)

    ungrouped = sorted(
        (payroll_type for payroll_type in tax_totals if payroll_type not in claimed),
        key=lambda code: component_label(code).lower(),
    )
    if ungrouped:
        rows.append(
            group_row(
                "OTHER_TAXES",
                "Other taxes",
                sum((tax_totals[code] for code in ungrouped), ZERO),
            )
        )
        for payroll_type in ungrouped:
            row = line(payroll_type)
            row["key"] = f"OTHER_TAXES.{payroll_type}"
            rows.append(row)

    return {"columns": COLUMNS, "rows": rows}


def resolve_prior_wages(company, year, before_date):
    """Wages each employee earned earlier in `year`, before `before_date`.

    Without this a wage base looks untouched at the start of every range, and
    an employee who passed the FUTA base in March would show taxable wages
    again in December.
    """
    from payrollio.models import PayrollSalaryComponent

    if not year or not before_date:
        return {}

    rows = PayrollSalaryComponent.objects.filter(
        payroll_category=PAY,
        payroll__pay_date__year=year,
        payroll__pay_date__lt=before_date,
        payroll__employee__user__companyuser__company=company,
    ).values_list("payroll__employee_id", "current")

    totals = {}
    for employee_id, current in rows:
        totals[employee_id] = totals.get(employee_id, ZERO) + money(current)
    return totals


def resolve_state_configs(state_codes, year):
    """Config blobs for several states at once, keyed by USPS code."""
    return {
        code: resolve_state_config(code, year)
        for code in {c for c in state_codes if c}
    }


def resolve_state_config(state_code, year):
    """The state's published tax config blob for the year, or None."""
    from payrollio.models import PayrollTaxConfig

    if not state_code:
        return None
    config = (
        PayrollTaxConfig.objects.filter(jurisdiction=state_code.upper(), year=year)
        .order_by("-id")
        .first()
    )
    if config is None:
        return None
    data = config.data
    if isinstance(data, dict):
        return data
    try:
        import json

        return json.loads(data or "{}")
    except (TypeError, ValueError):
        return None
