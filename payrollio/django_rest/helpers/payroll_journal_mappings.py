"""
Shared payroll → journal mapping keys for default accounting preference strategies.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from payrollio.choicess import AccountingPreferencesExpenseTypeChoices

TWOPLACES = Decimal("0.01")
EMPLOYEE_NET_PAY_CATEGORIES = ("EMPLOYEE_TAXES", "EMPLOYEE_DEDUCTIONS")


def quantize_money(value):
    """Normalize to dollars/cents (max 2 decimal places), no float rounding drift."""
    if value is None:
        return Decimal("0.00")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

# Tax liability component account_type → payroll component payroll_type values
FEDERAL_TAX_GROUP_941 = "FEDERAL_TAXES_(941/943/944)"
FEDERAL_TAX_GROUP_940 = "FEDERAL_UNEMPLOYMENT_(940)"

FEDERAL_TAXES_941_943_944_PAYROLL_TYPES = (
    "FEDERAL_INCOME_TAX",
    "SOCIAL_SECURITY",
    "MEDICARE",
    # Additional Medicare Tax: 0.9% on wages above 200,000, withheld from the
    # employee with no employer match. `wage_caps.py:45` has carried it for
    # every jurisdiction all along and this list did not, so a pay run that
    # crossed the threshold withheld it from the employee and credited it to no
    # liability -- the entry short by exactly the withholding, and the money
    # owed to the IRS recorded nowhere.
    #
    # It is reported on Form 941 like the rest of this group, so this is where
    # it belongs rather than a group of its own.
    "MEDICARE_ADDITIONAL",
    "MEDICARE_EMPLOYER",
    "SOCIAL_SECURITY_EMPLOYER",
)

FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES = ("FUTA_EMPLOYER",)

TAX_GROUP_PAYROLL_TYPES = {
    FEDERAL_TAX_GROUP_941: FEDERAL_TAXES_941_943_944_PAYROLL_TYPES,
    FEDERAL_TAX_GROUP_940: FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES,
    "NYS_INCOME_TAX": (
        "NYS_INCOME_TAX",
        "_INCOME_TAX",  # payroll engine state income key for NY
    ),
    "MN_INCOME_TAX": (
        "MN_INCOME_TAX",
        "_INCOME_TAX",
    ),
    # Employee paid-leave withholding (employer premium is in MN_UNEMPLOYMENT_TAXES)
    "MN_PAID_LEAVE": ("MN_PAID_LEAVE",),
    "NYS_EMPLOYMENT_TAXES": (
        "NYS_EMPLOYMENT_TAXES",
        "NYS_UI_EMPLOYER",
        "NY_SUI_EMPLOYER",
        "NY_REEMPLOYMENT_TAX",
        "NY_RSF",
    ),
    "MN_UNEMPLOYMENT_TAXES": (
        "MN_UNEMPLOYMENT_TAXES",
        "MN_UI_EMPLOYER",
        "MN_WORKFORCE_DEVELOPMENT_FEE",
        "MN_ADDITIONAL_ASSESSMENT",
        "MN_PAID_LEAVE_EMPLOYER",
    ),
}

STATE_INCOME_TAX_GROUP_KEY = {
    "NY": "NYS_INCOME_TAX",
    "MN": "MN_INCOME_TAX",
}

STATE_EMPLOYMENT_TAX_GROUP_KEY = {
    "NY": "NYS_EMPLOYMENT_TAXES",
    "MN": "MN_UNEMPLOYMENT_TAXES",
}

# Other-liability account_type may differ from payroll engine payroll_type
OTHER_LIABILITY_PAYROLL_TYPE_ALIASES = {
    "Health Insurance": ("Health Ins.",),
    "Health Ins.": ("Health Insurance",),
    "Retirement 401k": ("Retirement Plan", "Retirement 401(k)"),
    "Retirement Plan": ("Retirement 401k",),
    "Child/Spouse Support": ("CHILD_SPOUSE_SUPPORT", "child/spouse support-0"),
    "CHILD_SPOUSE_SUPPORT": ("Child/Spouse Support", "child/spouse support-0"),
}

DEFAULT_PAYROLL_ACCOUNTING_STRATEGIES = {
    "wage_expense_type": AccountingPreferencesExpenseTypeChoices.SINGLE_WAGE_ACCOUNT,
    "company_contribution_expense_type": (
        AccountingPreferencesExpenseTypeChoices.COMPANY_CONTRIBUTION_SINGLE_ACCOUNT
    ),
    "employer_tax_expense_type": (
        AccountingPreferencesExpenseTypeChoices.SINGLE_EMPLOYER_TAX_ACCOUNT
    ),
    "tax_liability_expense_type": (
        AccountingPreferencesExpenseTypeChoices.DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP
    ),
    "other_liability_asset_account": (
        AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE
    ),
}


def uses_default_payroll_accounting_strategies(settings):
    if not settings:
        return False
    for field, expected in DEFAULT_PAYROLL_ACCOUNTING_STRATEGIES.items():
        if getattr(settings, field) != expected:
            return False
    return True


def normalize_liability_key(value):
    """Upper-case, with every run of non-alphanumerics collapsed to one `_`.

    The two sides of this comparison come from different namespaces that were
    never made to agree. `PayrollAccountExpenseAccountComponent.account_type`
    is upper snake (`SUP_LIFE_EE`, `HEALTH`); the `payroll_type` on a
    `PayrollSalaryComponent` is title case with spaces (`Sup Life Ee`,
    `Health`) for deductions, while tax rows happen to be upper snake and so
    matched by luck.

    Company 184 has both accounts configured and neither ever matched, which is
    why `SUP LIFE EE` carries zero journal lines.
    """
    return re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")


def payroll_type_matches_other_liability(account_type, payroll_type):
    if not account_type or not payroll_type:
        return False
    if payroll_type == account_type:
        return True
    if normalize_liability_key(payroll_type) == normalize_liability_key(account_type):
        return True
    aliases = OTHER_LIABILITY_PAYROLL_TYPE_ALIASES.get(account_type, ())
    if payroll_type in aliases:
        return True
    reverse_aliases = OTHER_LIABILITY_PAYROLL_TYPE_ALIASES.get(payroll_type, ())
    return account_type in reverse_aliases


def state_income_tax_group_key(state):
    if not state:
        return None
    normalized = str(state).strip().upper()
    return STATE_INCOME_TAX_GROUP_KEY.get(
        normalized, f"{normalized}_INCOME_TAX"
    )


def state_employment_tax_group_key(state):
    if not state:
        return None
    normalized = str(state).strip().upper()
    return STATE_EMPLOYMENT_TAX_GROUP_KEY.get(
        normalized, f"{normalized}_UNEMPLOYMENT_TAXES"
    )


def payroll_types_for_group(group_key):
    """Payroll component types credited to a tax liability group.

    Explicit entries in TAX_GROUP_PAYROLL_TYPES (federal, NY, MN) win; any
    other state's synthesized group key expands generically so an arbitrary
    state's components are matched: the engine emits the bare "_INCOME_TAX"
    key for state withholding, and employer unemployment lines as
    {ST}_UI_EMPLOYER / {ST}_SUI_EMPLOYER.
    """
    if not group_key:
        return ()
    mapped = TAX_GROUP_PAYROLL_TYPES.get(group_key)
    if mapped:
        return mapped
    if group_key.endswith("_INCOME_TAX"):
        return (group_key, "_INCOME_TAX")
    if group_key.endswith("_UNEMPLOYMENT_TAXES"):
        state = group_key[: -len("_UNEMPLOYMENT_TAXES")]
        return (
            group_key,
            f"{state}_UI_EMPLOYER",
            f"{state}_SUI_EMPLOYER",
        )
    return (group_key,)


def sum_payroll_components(components, *, payroll_types=None, payroll_category=None):
    total = Decimal("0.00")
    type_set = set(payroll_types) if payroll_types else None
    for comp in components:
        if payroll_category and comp.get("payroll_category") != payroll_category:
            continue
        if type_set is not None and comp.get("payroll_type") not in type_set:
            continue
        total += quantize_money(comp.get("current") or 0)
    return quantize_money(total)


def net_pay_from_components(components):
    """Net pay from gross minus employee taxes and deductions (2 decimal places)."""
    gross = sum_payroll_components(components, payroll_category="PAY")
    withheld = sum(
        (
            sum_payroll_components(components, payroll_category=category)
            for category in EMPLOYEE_NET_PAY_CATEGORIES
        ),
        Decimal("0.00"),
    )
    return quantize_money(gross - withheld)
