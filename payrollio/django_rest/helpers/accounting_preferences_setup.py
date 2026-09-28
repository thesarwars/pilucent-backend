import logging

from django.db import transaction

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
from categoryio.models import Category

from companyio.models import CompanySetting

from payrollio.choicess import AccountingPreferencesExpenseTypeChoices
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAX_GROUP_940,
    FEDERAL_TAX_GROUP_941,
)
from payrollio.models import (
    DeductionAndContributions,
    PayrollAccountExpenseAccountComponent,
    PayrollAccountingPreferencesSetting,
    PayrollGeneralTaxSetting,
)

logger = logging.getLogger(__name__)

# All 50 states + DC. Payroll runs in any of them; NY/MN keep their bespoke
# component tuples below, every other state gets the generic pair from
# _generic_state_components().
US_STATE_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

STATE_ALIASES = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NYS": "NY",  # seen in stored work-location data
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}

GLOBAL_CHART_ACCOUNT_TITLES = {
    "paycheck_payroll_tax_expense_account": "Cash on Hand",
    "global_wage_account": "Wages",
    "global_contribution_expense_account": "Health Insurance",
    "global_employer_tax_expenses": "Taxes",
}

FEDERAL_TAX_LIABILITY_COMPONENTS = (
    (FEDERAL_TAX_GROUP_941, "Federal Taxes (941/943/944)"),
    (FEDERAL_TAX_GROUP_940, "Federal Unemployment (940)"),
)

STATE_TAX_LIABILITY_COMPONENTS = {
    "NY": (
        ("NYS_INCOME_TAX", "NYS Income Tax"),
        ("NYS_EMPLOYMENT_TAXES", "NYS Employment Taxes"),
    ),
    "MN": (
        ("MN_INCOME_TAX", "MN Income Tax"),
        ("MN_UNEMPLOYMENT_TAXES", "MN Unemployment Taxes"),
        ("MN_PAID_LEAVE", "MN Paid Leave"),
    ),
}

# Auto-create liability COA when missing (chart title per account_type)
TAX_LIABILITY_AUTO_CREATE_CHART = frozenset({"MN_PAID_LEAVE"})

OTHER_CURRENT_LIABILITIES_ACCOUNT_TYPE = "Other Current Liabilities"
OTHER_CURRENT_LIABILITY_DETAIL_TYPE = "Other Current Liability"


def normalize_us_state(state):
    """Return a valid 2-letter USPS code, or None for anything unrecognized."""
    if not state:
        return None
    normalized = str(state).strip().upper()
    normalized = STATE_ALIASES.get(normalized, normalized)
    return normalized if normalized in US_STATE_CODES else None


def resolve_state_from_general_tax_setting(company):
    general_tax_setting = PayrollGeneralTaxSetting.objects.filter(
        company=company
    ).first()
    if not general_tax_setting:
        return None
    return normalize_us_state(general_tax_setting.state)


def get_company_chart_account(company, title):
    """Resolve a payroll chart account, by key where one exists.

    Title-only resolution made two things break silently.

    A **rename** dropped the account: these titles are chosen by the tenant and
    the lookup is exact-ish, so "Federal Taxes (941/943/944)" becoming anything
    else means the component is skipped and the pay run posts short by the whole
    federal withholding -- `assert_entry_balances` logs rather than raising, so
    it commits.

    A **deactivation** did the same, because this filters `status=ACTIVE`. That
    one is recent and self-inflicted: the deactivate endpoint refuses control
    accounts on `system_key`, and these had none, so nothing stopped a tenant
    retiring them.

    Both close the same way. `TITLE_TO_SYSTEM_KEY` now carries the two federal
    titles, so they resolve by identity and COA-153 refuses to deactivate them.
    An existing unkeyed row is adopted on first resolution -- ~33 of 60
    companies have one and none is keyed.

    Deliberately unchanged: an account that genuinely does not exist still
    resolves to None and the caller still skips the component with a warning.
    Auto-creating these is a decision `TAX_LIABILITY_AUTO_CREATE_CHART` already
    took the other way, and it is not this function's to overturn.
    """
    from common.django_rest.helpers.chart_of_account_helpers import (
        TITLE_TO_SYSTEM_KEY,
    )

    system_key = TITLE_TO_SYSTEM_KEY.get(title)
    if system_key:
        keyed = (
            ChartOfAccount.objects.filter(company=company, system_key=system_key)
            .exclude(status=ChartOfAccountStatusChoices.REMOVED)
            .first()
        )
        if keyed:
            return keyed

    account = ChartOfAccount.objects.filter(
        company=company,
        status=ChartOfAccountStatusChoices.ACTIVE,
        title__iexact=title,
    ).first()

    if account and system_key and not account.system_key:
        # Found by title and eligible for a key: stamp it now, so the next
        # lookup is by identity and a later rename cannot lose it.
        account.system_key = system_key
        account.is_fixed = True
        account.save(update_fields=["system_key", "is_fixed", "updated_at"])

    return account


# States with no wage income tax withholding: seed only the unemployment
# component so companies there don't get a dead "Income Tax" liability account.
NO_STATE_INCOME_TAX_STATES = frozenset(
    {"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"}
)


def _generic_state_components(state):
    """Default liability components for a state without a bespoke tuple.

    The account_type strings deliberately match what the journal poster's
    state_income_tax_group_key / state_employment_tax_group_key synthesize for
    unmapped states, so seeded components and journal group keys line up by
    construction.
    """
    components = []
    if state not in NO_STATE_INCOME_TAX_STATES:
        components.append((f"{state}_INCOME_TAX", f"{state} Income Tax"))
    components.append(
        (f"{state}_UNEMPLOYMENT_TAXES", f"{state} Unemployment Taxes")
    )
    return tuple(components)


def _is_generic_state_component(account_type):
    """True for a generated {ST}_INCOME_TAX / {ST}_UNEMPLOYMENT_TAXES key."""
    if not account_type:
        return False
    for suffix in ("_INCOME_TAX", "_UNEMPLOYMENT_TAXES"):
        if account_type.endswith(suffix):
            state = account_type[: -len(suffix)]
            return (
                state in US_STATE_CODES and state not in STATE_TAX_LIABILITY_COMPONENTS
            )
    return False


def _tax_liability_components_for_state(state, *, include_federal=True):
    components = list(FEDERAL_TAX_LIABILITY_COMPONENTS) if include_federal else []
    if state in STATE_TAX_LIABILITY_COMPONENTS:  # NY/MN bespoke tuples
        components.extend(STATE_TAX_LIABILITY_COMPONENTS[state])
    elif state in US_STATE_CODES:
        components.extend(_generic_state_components(state))
    return components


def _resolve_tax_liability_chart_account(company, chart_title, account_type):
    # Generic state components bind only LIABILITY accounts (a user-created
    # expense account that happens to share the title, e.g. a "CA Income Tax"
    # corporate-tax expense, must not receive payroll withholding credits) and
    # auto-create the account when missing: unlike NY/MN, generic states have
    # no seeded chart-of-account titles, so requiring a pre-existing account
    # would silently drop their credits.
    if _is_generic_state_component(account_type):
        account = ChartOfAccount.objects.filter(
            company=company,
            status=ChartOfAccountStatusChoices.ACTIVE,
            title__iexact=chart_title,
            kind=ChartOfAccountKindChoices.LIABILITIES,
        ).first()
        if account:
            return account
        return _create_other_current_liability_chart_account(company, chart_title)

    account = get_company_chart_account(company, chart_title)
    if account:
        return account
    if account_type in TAX_LIABILITY_AUTO_CREATE_CHART:
        return _create_other_current_liability_chart_account(company, chart_title)
    return None


def _chart_title_for_tax_account_type(state, account_type):
    for at, chart_title in STATE_TAX_LIABILITY_COMPONENTS.get(state or "", ()):
        if at == account_type:
            return chart_title
    if state in US_STATE_CODES:
        for at, chart_title in _generic_state_components(state):
            if at == account_type:
                return chart_title
    return None


@transaction.atomic
def ensure_tax_liability_component(settings, company, account_type, *, state=None):
    """Create a missing tax liability component (and COA if configured to auto-create)."""
    liability_type = settings.tax_liability_expense_type
    existing = PayrollAccountExpenseAccountComponent.objects.filter(
        payroll_accounting_preferences=settings,
        payroll_accounting_preferences_type=liability_type,
        account_type=account_type,
    ).first()
    if existing and existing.expense_account:
        return existing.expense_account

    chart_title = _chart_title_for_tax_account_type(state, account_type)
    if not chart_title:
        return None

    expense_account = _resolve_tax_liability_chart_account(
        company, chart_title, account_type
    )
    if not expense_account:
        logger.warning(
            "Cannot ensure tax liability component %s for company %s; "
            "chart account %r not found",
            account_type,
            company.uid,
            chart_title,
        )
        return None

    if existing:
        existing.expense_account = expense_account
        existing.save(update_fields=["expense_account", "updated_at"])
        return expense_account

    PayrollAccountExpenseAccountComponent.objects.create(
        payroll_accounting_preferences=settings,
        payroll_accounting_preferences_type=liability_type,
        account_type=account_type,
        expense_account=expense_account,
    )
    return expense_account


def _create_tax_liability_components(settings, company, components):
    liability_type = settings.tax_liability_expense_type
    created = []
    for account_type, chart_title in components:
        if PayrollAccountExpenseAccountComponent.objects.filter(
            payroll_accounting_preferences=settings,
            payroll_accounting_preferences_type=liability_type,
            account_type=account_type,
        ).exists():
            continue

        expense_account = _resolve_tax_liability_chart_account(
            company, chart_title, account_type
        )
        if not expense_account:
            logger.warning(
                "Skipping tax liability component %s for company %s; "
                "chart account %r not found",
                account_type,
                company.uid,
                chart_title,
            )
            continue

        created.append(
            PayrollAccountExpenseAccountComponent.objects.create(
                payroll_accounting_preferences=settings,
                payroll_accounting_preferences_type=liability_type,
                account_type=account_type,
                expense_account=expense_account,
            )
        )
    return created


@transaction.atomic
def sync_tax_liability_components(
    settings,
    company,
    state,
    *,
    include_federal=True,
):
    components = _tax_liability_components_for_state(
        state,
        include_federal=include_federal,
    )
    return _create_tax_liability_components(settings, company, components)


@transaction.atomic
def setup_payroll_accounting_preferences(company, *, state, created_by=None):
    """Create default payroll accounting preferences and tax liability components."""
    existing = PayrollAccountingPreferencesSetting.objects.filter(
        company=company
    ).first()
    if existing:
        if state:
            sync_tax_liability_components(
                existing,
                company,
                state,
                include_federal=True,
            )
        return existing

    global_accounts = {}
    missing_titles = []
    for field_name, title in GLOBAL_CHART_ACCOUNT_TITLES.items():
        account = get_company_chart_account(company, title)
        if account:
            global_accounts[field_name] = account
        else:
            missing_titles.append(title)

    if missing_titles:
        logger.warning(
            "Skipping payroll accounting preferences for company %s; "
            "missing chart accounts: %s",
            company.uid,
            ", ".join(missing_titles),
        )
        return None

    settings = PayrollAccountingPreferencesSetting.objects.create(
        company=company,
        created_by=created_by,
        paycheck_payroll_tax_expense_account=global_accounts[
            "paycheck_payroll_tax_expense_account"
        ],
        global_wage_account=global_accounts["global_wage_account"],
        global_contribution_expense_account=global_accounts[
            "global_contribution_expense_account"
        ],
        global_employer_tax_expenses=global_accounts["global_employer_tax_expenses"],
        wage_expense_type=AccountingPreferencesExpenseTypeChoices.SINGLE_WAGE_ACCOUNT,
        company_contribution_expense_type=(
            AccountingPreferencesExpenseTypeChoices.COMPANY_CONTRIBUTION_SINGLE_ACCOUNT
        ),
        employer_tax_expense_type=(
            AccountingPreferencesExpenseTypeChoices.SINGLE_EMPLOYER_TAX_ACCOUNT
        ),
        tax_liability_expense_type=(
            AccountingPreferencesExpenseTypeChoices.DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP
        ),
        other_liability_asset_account=(
            AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE
        ),
    )

    _create_tax_liability_components(
        settings,
        company,
        _tax_liability_components_for_state(state, include_federal=True),
    )
    return settings


def account_type_for_deduction(deduction):
    """Journal matching key; same label as the deduction/contribution title."""
    return str(deduction.title or "").strip()[:100]


def _get_other_current_liabilities_categories():
    account_type = Category.objects.filter(
        title=OTHER_CURRENT_LIABILITIES_ACCOUNT_TYPE,
        kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        status=CategoryStatusChoices.ACTIVE,
        parent__title="Liabilities",
    ).first()
    if not account_type:
        return None, None

    detail_type = Category.objects.filter(
        title=OTHER_CURRENT_LIABILITY_DETAIL_TYPE,
        kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        status=CategoryStatusChoices.ACTIVE,
        parent=account_type,
    ).first()
    return account_type, detail_type


def _next_other_current_liability_code(company):
    codes = (
        ChartOfAccount.objects.filter(
            company=company,
            kind=ChartOfAccountKindChoices.LIABILITIES,
        )
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .values_list("code", flat=True)
    )

    max_code = 2899
    for code in codes:
        if code and str(code).isdigit():
            max_code = max(max_code, int(code))
    return str(max_code + 1)


def _create_other_current_liability_chart_account(company, title):
    account_type, detail_type = _get_other_current_liabilities_categories()
    if not account_type or not detail_type:
        logger.warning(
            "Cannot create liability chart account %r for company %s; "
            "Other Current Liabilities categories are missing",
            title,
            company.uid,
        )
        return None

    company_setting, _ = CompanySetting.objects.get_or_create(company=company)

    account = ChartOfAccount.objects.create(
        title=title,
        code=_next_other_current_liability_code(company),
        company=company,
        kind=ChartOfAccountKindChoices.LIABILITIES,
        account_type=account_type,
        detail_type=detail_type,
        opening_balance=0,
        status=ChartOfAccountStatusChoices.ACTIVE,
        currency=company_setting.home_currency,
        description=f"Payroll other liability for {title}",
        is_fixed=False,
    )
    logger.info(
        "Created Other Current Liability chart account %r (%s) for company %s",
        title,
        account.code,
        company.uid,
    )
    return account


def get_or_create_liability_chart_account_for_deduction(company, deduction):
    """
    Match chart account title to deduction title (case-insensitive).
    Create a new active liability account under Other Current Liabilities if missing.
    """
    title = str(deduction.title or "").strip()
    if not title:
        return None

    account = get_company_chart_account(company, title)
    if account:
        return account

    return _create_other_current_liability_chart_account(company, title)


@transaction.atomic
def sync_other_liability_component_for_deduction(
    company,
    deduction,
    *,
    employee=None,
):
    """
    Ensure a PayrollAccountExpenseAccountComponent exists for other-liability
    payroll accounting when a company deduction is assigned to an employee.
    """
    if not deduction or not isinstance(deduction, DeductionAndContributions):
        return None

    settings = PayrollAccountingPreferencesSetting.objects.filter(
        company=company
    ).first()
    if not settings:
        logger.warning(
            "Skipping other-liability component for deduction %s; "
            "no payroll accounting preferences for company %s",
            deduction.uid,
            company.uid,
        )
        return None

    liability_type = settings.other_liability_asset_account
    if (
        liability_type
        != AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE
    ):
        logger.debug(
            "Company %s uses other_liability type %s; skipping auto-sync",
            company.uid,
            liability_type,
        )
        return None

    existing = PayrollAccountExpenseAccountComponent.objects.filter(
        payroll_accounting_preferences=settings,
        payroll_accounting_preferences_type=liability_type,
        deduction_and_contribution=deduction,
    ).first()
    if existing:
        return existing

    account_type = account_type_for_deduction(deduction)
    if not account_type:
        logger.warning(
            "Skipping other-liability component for deduction %s; empty account_type",
            deduction.uid,
        )
        return None

    expense_account = get_or_create_liability_chart_account_for_deduction(
        company, deduction
    )
    if not expense_account:
        logger.warning(
            "Skipping other-liability component for deduction %s; "
            "no liability chart account found for company %s",
            deduction.uid,
            company.uid,
        )
        return None

    return PayrollAccountExpenseAccountComponent.objects.create(
        payroll_accounting_preferences=settings,
        payroll_accounting_preferences_type=liability_type,
        account_type=account_type,
        expense_account=expense_account,
        deduction_and_contribution=deduction,
        employee=employee,
    )
