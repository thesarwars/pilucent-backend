from decimal import Decimal
from collections import defaultdict

from rest_framework.exceptions import ValidationError

from payrollio.models import (
    PayrollAccountingPreferencesSetting,
    PayrollAccountExpenseAccountComponent,
)
from payrollio.choicess import AccountingPreferencesExpenseTypeChoices
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    _is_generic_state_component,
    ensure_tax_liability_component,
    normalize_us_state,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAX_GROUP_940,
    FEDERAL_TAX_GROUP_941,
    FEDERAL_TAXES_941_943_944_PAYROLL_TYPES,
    FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES,
    net_pay_from_components,
    payroll_type_matches_other_liability,
    payroll_types_for_group,
    quantize_money,
    state_employment_tax_group_key,
    state_income_tax_group_key,
    sum_payroll_components,
    uses_default_payroll_accounting_strategies,
)

from journalio.django_rest.services.journals import JournalEntryService
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    get_migration_undo_balance_operation,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

import logging

logger = logging.getLogger(__name__)


def group_payroll_amounts(payroll_data):
    totals = defaultdict(Decimal)
    for comp in payroll_data["payroll_components"]:
        payroll_type = comp["payroll_type"]
        current = Decimal(comp["current"])
        totals[payroll_type] += current
    return totals


def _append_connector_line(connector_data, account, action_type, amount):
    amount = quantize_money(amount)
    if not account or amount <= 0:
        return
    connector_data.append(
        (
            account,
            action_type,
            amount,
            account.opening_balance,
        )
    )


def _post_side(connector_data, account, amount, side):
    """Post `amount` to `account` on `side`, whatever kind the account is.

    Both callers used to hard-code the action `"addition"` and differ only in
    the `update_opening_balance` argument, which meant neither did what its
    name said. `"addition"` resolves through `get_debit_or_credit` to DEBIT on
    assets and expenses and CREDIT on liabilities, equity and income -- so
    `_post_credit` wrote a genuine credit only when handed a liability, and on
    anything else wrote a DEBIT while subtracting from the stored balance. The
    journal and the balance moved in opposite directions.

    That is not hypothetical. Company 184's two configured payroll deduction
    accounts -- 9794 "Health Insurance" and 9839 "SUP LIFE EE" -- are both
    `kind=EXPENSES`, so every deduction credit routed to them would have landed
    on the wrong side. `audit_account_integrity` already flags 9839 for having
    a `kind` its account type contradicts.

    Resolving the action from the side is the same correction applied to the
    purchase and importer paths in a1407806 and f4a0dc62.
    """
    amount = quantize_money(amount)
    if not account or amount <= 0:
        return
    action = action_for_side(account.kind, side)
    update_opening_balance(
        account, balance_operation_for_action(action), amount, 0
    )
    _append_connector_line(connector_data, account, action, amount)


def _post_debit(connector_data, account, amount):
    _post_side(
        connector_data, account, amount, JournalEntryConnectorKindChoices.DEBIT
    )


def _post_credit(connector_data, account, amount):
    _post_side(
        connector_data, account, amount, JournalEntryConnectorKindChoices.CREDIT
    )


def unwind_existing_payroll_posting(payroll_instance):
    """Undo whatever this run has already written to the ledger.

    Two callers need this and they needed it for the same reason.

    `create_journal_entry` is a `get_or_create` keyed on `payroll_salary`, so
    re-posting a run does not replace its entry -- it finds the same one and
    appends another full set of legs. Both sides get appended together, so the
    entry stays balanced and the write-time check never fires; what doubles is
    the number of legs and every account's stored balance. The salary-process
    endpoint is an upsert, so every save of an existing run did that.

    Deleting a run has the mirror problem: `JournalEntry.payroll_salary` is
    SET_NULL, so the entries survive with their balances still applied and
    nothing to say what produced them.

    The undo direction comes from each connector's stored `kind` rather than
    being assumed, so rows written before the side fixes unwind the way they
    actually posted rather than the way today's code would post them.

    Returns the number of entries removed.
    """
    from journalio.models import JournalEntry

    removed = 0
    for entry in JournalEntry.objects.filter(payroll_salary=payroll_instance):
        rows = entry.journalentryconnector_set.select_related("account")
        for row in rows:
            amount = row.debit or row.credit or 0
            if not amount or row.account is None:
                continue
            update_opening_balance(
                row.account,
                get_migration_undo_balance_operation(row.account, row.kind),
                amount,
                0,
            )
        rows.delete()
        entry.delete()
        removed += 1

    if removed:
        logger.info(
            "payroll run %s: unwound %s existing journal entry(ies) before "
            "re-posting", payroll_instance.pk, removed,
        )
    return removed


OTHER_LIABILITY_CATEGORIES = ("EMPLOYEE_DEDUCTIONS", "COMPANY_PAID_CONTRIBUTIONS")
PAYROLL_RESIDUAL_TITLE = "Payroll Liabilities"


def get_or_create_payroll_residual_account(company):
    """The account an unconfigured deduction lands in, made on first need.

    Resolved by `system_key`, so renaming it is safe -- it was looked up by the
    literal title on every pay run, which made the account one rename away from
    breaking the entry.

    Created rather than reported missing. Only 15 of 20 industry templates ship
    a "Payroll Liabilities" row and only 17 of 60 companies have one, so for the
    remaining 43 this path resolved to None, logged "the journal entry will not
    balance", and posted short -- and `assert_entry_balances` logs rather than
    raises, so the short entry committed. A residual account that does not exist
    is not a reason to write a broken journal entry.

    Takes the row from the company's own industry template where there is one,
    so the account lands with the code and taxonomy that industry would have
    given it; falls back to a plain Other Current Liability otherwise.
    """
    from accounts.choices import (
        ChartOfAccountKindChoices,
        ChartOfAccountStatusChoices,
        ChartOfAccountSystemKeyChoices,
    )
    from accounts.models import ChartOfAccount
    from common.django_rest.helpers.chart_of_account_helpers import (
        resolve_taxonomy_category,
    )
    from companyio.django_rest.helpers.signal_helpers import (
        create_control_account,
        template_for,
    )

    key = ChartOfAccountSystemKeyChoices.PAYROLL_LIABILITIES
    existing = (
        ChartOfAccount.objects.filter(company=company, system_key=key)
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .first()
    )
    if existing:
        return existing

    # Not yet keyed but already present -- the common case on the 17 companies
    # whose template shipped the row. Adopt it rather than minting a second.
    unkeyed = (
        ChartOfAccount.objects.filter(
            company=company, title=PAYROLL_RESIDUAL_TITLE, system_key__isnull=True
        )
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .first()
    )
    if unkeyed:
        unkeyed.system_key = key
        unkeyed.is_fixed = True
        unkeyed.save(update_fields=["system_key", "is_fixed", "updated_at"])
        return unkeyed

    if any(r.get("title") == PAYROLL_RESIDUAL_TITLE for r in template_for(company.kind)):
        created = create_control_account(company, key)
        if created is not None:
            return created

    account_type = resolve_taxonomy_category("Other Current Liabilities")
    return ChartOfAccount.objects.create(
        company=company,
        title=PAYROLL_RESIDUAL_TITLE,
        code="2300",
        kind=ChartOfAccountKindChoices.LIABILITIES,
        status=ChartOfAccountStatusChoices.ACTIVE,
        account_type=account_type,
        detail_type=resolve_taxonomy_category(
            "Payroll Liabilities", parent=account_type
        ),
        system_key=key,
        is_fixed=True,
        description=(
            "Holds payroll deductions that reached no configured liability "
            "account. A balance here means an item needs mapping under payroll "
            "accounting preferences."
        ),
    )


def _post_other_liability_withholding(
    connector_data, other_liability, components, company
):
    """Credit every deduction and employer contribution to a liability.

    Iterates the COMPONENTS once and resolves each to at most one configured
    account. The old shape was the other way round -- for each configured
    account, sum the components matching it -- which had two consequences.

    A component matching two configured accounts was credited **twice**, and
    nothing anywhere noticed.

    And a component matching none was dropped in silence. That is the whole of
    company 184's 240.84 imbalance: its five EMPLOYEE_DEDUCTIONS (Dental 17.78,
    Health 201.60, HSA 1.54, Sup Life Ee 12.12, Vision Plan 7.80) are withheld
    from net pay, so the wage debit carries them, and none reached a liability.
    Two of the five have accounts configured and never matched them -- see
    `normalize_liability_key` -- and the other three, 27.12 between them, have
    no configured account at all. A matcher fix alone would still lose those.

    Whatever reaches no configured account now goes to `Payroll Liabilities`,
    with an ERROR naming the components. That is a mis-attribution rather than
    an unbalanced entry, and it is deliberately loud: the right fix is for the
    company to configure the account, and this makes it visible instead of
    letting the ledger absorb it.
    """
    configured = [
        (liability.account_type, liability.expense_account)
        for liability in other_liability
        if liability.account_type and liability.expense_account
    ]

    per_account = {}
    unmatched_total = Decimal("0.00")
    unmatched_names = []

    for pc in components:
        if pc.get("payroll_category") not in OTHER_LIABILITY_CATEGORIES:
            continue
        amount = quantize_money(pc.get("current") or 0)
        if amount <= 0:
            continue

        payroll_type = pc.get("payroll_type")
        account = next(
            (
                expense_account
                for account_type_name, expense_account in configured
                if payroll_type_matches_other_liability(
                    account_type_name, payroll_type
                )
            ),
            None,
        )
        if account is None:
            unmatched_total += amount
            unmatched_names.append(str(payroll_type))
            continue
        per_account[account.pk] = (
            account,
            per_account.get(account.pk, (account, Decimal("0.00")))[1] + amount,
        )

    for account, total in per_account.values():
        _post_credit(connector_data, account, total)

    if not unmatched_total:
        return

    residual_account = get_or_create_payroll_residual_account(company)

    logger.error(
        "payroll: %s withheld for %s has no configured liability account -- "
        "posting it to %r so the entry balances. Configure an account for "
        "each of these under the company's payroll accounting preferences.",
        unmatched_total, ", ".join(unmatched_names), PAYROLL_RESIDUAL_TITLE,
    )
    _post_credit(connector_data, residual_account, unmatched_total)


def _post_tax_liability_credit(
    connector_data,
    account_map,
    group_key,
    components,
    *,
    payroll_category=None,
):
    payroll_types = payroll_types_for_group(group_key)
    total = sum_payroll_components(
        components,
        payroll_types=payroll_types,
        payroll_category=payroll_category,
    )

    account = account_map.get(group_key)
    if not account:
        if total > 0:
            # Money was withheld but has no liability account: the journal
            # entry would post unbalanced. Loud so it gets fixed, not buried.
            logger.error(
                "Unposted payroll tax credit %s for group %s; no liability "
                "account configured — journal entry is missing this credit",
                total,
                group_key,
            )
        else:
            logger.warning(
                "Skipping tax liability credit for %s; not in account_map",
                group_key,
            )
        return Decimal("0")

    logger.info("tax group %s total: %s", group_key, total)
    _post_credit(connector_data, account, total)
    return total


def _resolve_employee_state(employee):
    """State code from Employee.work_locations (PayrollWorkLocation FK).

    Stored values may be full names ("New York") or already codes; normalize so
    group keys are synthesized from the 2-letter code. Unrecognized values pass
    through raw (as before), so a withheld-but-unpostable state credit still
    reaches the loud path in _post_tax_liability_credit instead of being
    silently skipped.
    """
    if employee is None:
        return None
    work_location = getattr(employee, "work_locations", None)
    if work_location is None:
        return None
    raw_state = getattr(work_location, "location_state", None)
    return normalize_us_state(raw_state) or raw_state


def _validate_default_settings(settings_instance):
    if not settings_instance:
        raise ValidationError(
            {"detail": "Payroll accounting preferences are not configured for this company."}
        )
    if not uses_default_payroll_accounting_strategies(settings_instance):
        raise ValidationError(
            {
                "detail": (
                    "Payroll journal posting supports default accounting preferences only. "
                    "Update preferences to the default strategies or contact support."
                )
            }
        )
    required_accounts = {
        "paycheck_payroll_tax_expense_account": settings_instance.paycheck_payroll_tax_expense_account,
        "global_wage_account": settings_instance.global_wage_account,
        "global_contribution_expense_account": settings_instance.global_contribution_expense_account,
        "global_employer_tax_expenses": settings_instance.global_employer_tax_expenses,
    }
    missing = [name for name, account in required_accounts.items() if not account]
    if missing:
        raise ValidationError(
            {
                "detail": (
                    "Payroll accounting preferences are incomplete; missing: "
                    + ", ".join(missing)
                )
            }
        )


def post_payroll_entries(payroll_data, payroll_instance, company, employee):
    logger.info(
        "payroll_data: %s, gross_pay: %s", payroll_data, payroll_data["gross_pay"]
    )
    components = payroll_data.get("payroll_components") or []
    net_pay = net_pay_from_components(components)
    submitted_net_pay = quantize_money(payroll_data.get("net_pay"))
    if submitted_net_pay != net_pay:
        logger.warning(
            "net_pay %s differs from component-derived %s; using component-derived "
            "amount for journal bank credit",
            submitted_net_pay,
            net_pay,
        )
    total_amount = quantize_money(payroll_data.get("gross_pay"))

    settings_instance = PayrollAccountingPreferencesSetting.objects.filter(
        company=company
    ).first()
    _validate_default_settings(settings_instance)

    connector_data = []

    # Bank — net pay (default: credit paycheck bank / cash on hand).
    #
    # Went through _post_credit rather than being written out, because written
    # out it was wrong twice. `"substraction"` is a CREDIT on an asset -- money
    # leaving the bank, which is right -- but its matching balance operation is
    # "debit", subtract, and the call said "credit", add. So the journal took
    # the bank down while the stored balance took it up, on every payroll run.
    # And the action was fixed at `"substraction"` on an account the company
    # chooses, which lands on the wrong side for anything but an asset or
    # expense.
    bank_account = settings_instance.paycheck_payroll_tax_expense_account
    _post_credit(connector_data, bank_account, net_pay)

    # Wages expense (all PAY lines → single wage account)
    if (
        settings_instance.wage_expense_type
        == AccountingPreferencesExpenseTypeChoices.SINGLE_WAGE_ACCOUNT
    ):
        wage_total = sum_payroll_components(components, payroll_category="PAY")
        logger.info("wage_total: %s", wage_total)
        _post_debit(connector_data, settings_instance.global_wage_account, wage_total)

    # Company contribution expense
    if (
        settings_instance.company_contribution_expense_type
        == AccountingPreferencesExpenseTypeChoices.COMPANY_CONTRIBUTION_SINGLE_ACCOUNT
    ):
        contrib_total = sum_payroll_components(
            components, payroll_category="COMPANY_PAID_CONTRIBUTIONS"
        )
        logger.info("contrib_total: %s", contrib_total)
        _post_debit(
            connector_data,
            settings_instance.global_contribution_expense_account,
            contrib_total,
        )

    # Employer tax expense (all employer tax lines → single expense account)
    if (
        settings_instance.employer_tax_expense_type
        == AccountingPreferencesExpenseTypeChoices.SINGLE_EMPLOYER_TAX_ACCOUNT
    ):
        tax_total = sum_payroll_components(components, payroll_category="EMPLOYER_TAXES")
        logger.info("tax_total: %s", tax_total)
        _post_debit(
            connector_data,
            settings_instance.global_employer_tax_expenses,
            tax_total,
        )

    # Tax liabilities by group
    if (
        settings_instance.tax_liability_expense_type
        == AccountingPreferencesExpenseTypeChoices.DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP
    ):
        tax_liability_expense = PayrollAccountExpenseAccountComponent.objects.filter(
            payroll_accounting_preferences=settings_instance,
            payroll_accounting_preferences_type=settings_instance.tax_liability_expense_type,
        )
        account_map = {
            acc.account_type: acc.expense_account
            for acc in tax_liability_expense
            if acc.account_type and acc.expense_account
        }
        logger.info("account_map: %s", account_map)

        posted_tax = _post_tax_liability_credit(
            connector_data, account_map, FEDERAL_TAX_GROUP_941, components
        )
        posted_tax += _post_tax_liability_credit(
            connector_data, account_map, FEDERAL_TAX_GROUP_940, components
        )

        employee_state = _resolve_employee_state(employee)
        logger.info("employee_state: %s", employee_state)

        if employee_state:
            income_key = state_income_tax_group_key(employee_state)
            employment_key = state_employment_tax_group_key(employee_state)

            # Self-heal: companies onboarded before their state was supported
            # have no seeded state components. When this run actually withholds
            # state tax, create the component (and its liability account) now —
            # same pattern as MN_PAID_LEAVE below. Generic states only: NY/MN
            # component wiring stays exactly as it was (a deliberately unmapped
            # NY/MN component must not be silently re-linked).
            for group_key in (income_key, employment_key):
                if group_key in account_map:
                    continue
                if not _is_generic_state_component(group_key):
                    continue
                group_total = sum_payroll_components(
                    components, payroll_types=payroll_types_for_group(group_key)
                )
                if group_total > 0:
                    healed_account = ensure_tax_liability_component(
                        settings_instance,
                        company,
                        group_key,
                        state=employee_state,
                    )
                    if healed_account:
                        account_map[group_key] = healed_account

            posted_tax += _post_tax_liability_credit(
                connector_data, account_map, income_key, components
            )
            posted_tax += _post_tax_liability_credit(
                connector_data, account_map, employment_key, components
            )

            if str(employee_state).strip().upper() == "MN":
                paid_leave_total = sum_payroll_components(
                    components,
                    payroll_types=("MN_PAID_LEAVE",),
                    payroll_category="EMPLOYEE_TAXES",
                )
                if paid_leave_total > 0 and "MN_PAID_LEAVE" not in account_map:
                    paid_leave_account = ensure_tax_liability_component(
                        settings_instance,
                        company,
                        "MN_PAID_LEAVE",
                        state="MN",
                    )
                    if paid_leave_account:
                        account_map["MN_PAID_LEAVE"] = paid_leave_account
                posted_tax += _post_tax_liability_credit(
                    connector_data,
                    account_map,
                    "MN_PAID_LEAVE",
                    components,
                    payroll_category="EMPLOYEE_TAXES",
                )

    # --- Whatever the tax credits did not reach --------------------------
    #
    # The debit side carries gross wages plus employer taxes, and gross is net
    # pay plus employee taxes plus deductions. So the tax credits have to total
    # exactly the employee taxes plus the employer taxes; any part of that the
    # groups above did not post is a hole in the entry, and the withholding has
    # already been taken off the employee either way.
    #
    # Three separate ways it went short, all of them shapes that reach this
    # code, and all of them answered by the same shortfall rather than by three
    # more special cases:
    #
    #   * `Employee.work_locations` is nullable, and every state credit sits
    #     inside `if employee_state:` -- so one missing FK dropped the whole
    #     state block while the tax stayed withheld.
    #   * The credit side resolves exactly ONE state, from the work location,
    #     and never looks at the components. A Minnesota company carrying a New
    #     York employment tax -- which production has -- debits the employer
    #     half by category and credits it nowhere.
    #   * `_post_tax_liability_credit` logs and returns 0 when a group has no
    #     configured account, so a withholding whose account was never set up
    #     was already being dropped loudly rather than posted.
    #
    # Same answer the sale and credit-note paths reached for their own declared
    # tax: post the shortfall so the entry balances, and name what to configure.
    # A residual is a worse answer than the right account and a much better one
    # than a hole.
    withheld_tax = sum_payroll_components(
        components, payroll_category="EMPLOYEE_TAXES"
    ) + sum_payroll_components(components, payroll_category="EMPLOYER_TAXES")
    tax_shortfall = quantize_money(withheld_tax - posted_tax)

    if tax_shortfall > 0:
        logger.error(
            "payroll: %s of tax was withheld or accrued and reached no "
            "liability account -- posting it to %r so the pay run balances. "
            "Employee %s, state %r. Check the employee's work location and the "
            "company's payroll tax liability accounts.",
            tax_shortfall, PAYROLL_RESIDUAL_TITLE,
            getattr(employee, "pk", employee), employee_state,
        )
        _post_credit(
            connector_data,
            get_or_create_payroll_residual_account(company),
            tax_shortfall,
        )
    elif tax_shortfall < 0:
        logger.error(
            "payroll: tax credits total %s, MORE than the %s withheld. "
            "Refusing to post a negative leg, so this entry will not balance.",
            posted_tax, withheld_tax,
        )

    # Other liabilities: employee deductions + employer contribution payables
    if (
        settings_instance.other_liability_asset_account
        == AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE
    ):
        other_liability = PayrollAccountExpenseAccountComponent.objects.filter(
            payroll_accounting_preferences=settings_instance,
            payroll_accounting_preferences_type=settings_instance.other_liability_asset_account,
        )

        _post_other_liability_withholding(
            connector_data, other_liability, components, company
        )

    journal_entry = JournalEntryService.create_journal_entry(
        amount=total_amount,
        status=JournalEntryStatusChoices.PUBLISHED,
        kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
        is_transaction=True,
        is_journal_entry=False,
        company=company,
        object=payroll_instance,
    )
    JournalEntryService.create_journal_entry_connector(
        connector_data=connector_data,
        total=net_pay,
        request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
        journal_entry=journal_entry,
        employee=employee,
    )

    return []
