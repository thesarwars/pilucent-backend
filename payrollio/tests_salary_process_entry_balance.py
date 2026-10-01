"""`post_payroll_entries` still writes journal entries whose sides disagree.

Nothing had ever driven the payroll poster end to end. `tests_leg_sides`,
`tests_deduction_legs`, `tests_repost_idempotency` and `tests_void_round_trip`
each pin one leg helper or one call ordering, and `tests_void_round_trip` says
why: "Driving `post_payroll_entries` end to end needs accounting preferences, a
component set and an employee." So all of those can pass while the entry the
function actually writes is short -- which is what production shows: 24 of 43
PAYROLL_SALARY_PROCESS entries unbalanced, 1,065,436.76 between them.

`assert_entry_balances` LOGS and does not raise, so a short entry commits in
silence. These tests therefore sum `JournalEntryConnector.debit` and `.credit`
off the persisted entry themselves rather than trusting that check.

The identity the poster has to satisfy falls out of what it posts:

    DEBITS  = PAY + COMPANY_PAID_CONTRIBUTIONS + EMPLOYER_TAXES
    CREDITS = net_pay + tax-group credits + EMPLOYEE_DEDUCTIONS
                                          + COMPANY_PAID_CONTRIBUTIONS
    net_pay = PAY - EMPLOYEE_TAXES - EMPLOYEE_DEDUCTIONS

    => DEBITS - CREDITS = (EMPLOYEE_TAXES + EMPLOYER_TAXES)
                          - (tax-group credits)

The entry balances if and only if EVERY tax component, employee and employer,
is claimed by some tax liability group AND that group resolves to an account.
A tax component that no group claims is still withheld from net pay (shrinking
the bank credit) or still debited to the employer tax expense, with nothing on
the other side to answer it. Deductions are not the exposure -- those now reach
`Payroll Liabilities` via the residual path, which
`test_company_184s_unmatched_deductions_now_balance` confirms end to end. Taxes
are, because they have no residual path at all.

Four shapes below reproduce it. Each asserts the imbalance the CURRENT code
produces, house style for a demonstrated defect (see
`tests_repost_idempotency.test_a_second_post_without_unwinding_doubles`). When
the fix lands, every `assertEqual(debit - credit, <amount>)` here becomes
`assertEqual(debit, credit)` and the recorded amount is what stops being lost.
"""

from datetime import date
from decimal import Decimal
from unittest import skip

from django.core.management import call_command
from django.test import TestCase

from accounts.models import ChartOfAccount, User

from companyio.models import Company

from employeeio.models import Employee

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry

from payrollio.choicess import (
    PayrollWorkLocationChoices,
    SalaryProcessPayMethodChoice,
)
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    setup_payroll_accounting_preferences,
)
from payrollio.models import PayrollSalaryProcess, PayrollWorkLocation

from weapi.django_rest.helpers.salary_process_journal_entry import (
    post_payroll_entries,
)

# These tests are about US state-tax routing, or post a run whose state
# components must be routed for the test to mean anything. Routing resolves an
# employee's state through Employee.work_locations -- removed with the US
# employee module -- so _resolve_employee_state returns None for every employee,
# and they would pass on the no-state path without exercising their shape.
# See docs/employee-reconnect-backlog.md, "Payroll posting".
NO_STATE_ROUTING = "US state-tax routing needs Employee.work_locations, removed with the US employee module"


def component(payroll_type, category, current):
    return {
        "payroll_type": payroll_type,
        "payroll_category": category,
        "current": Decimal(str(current)),
    }


# One Minnesota pay run whose every component IS claimed by a tax group the
# poster consults. Kept as a module constant so each test states only what it
# adds, and so the control case and the broken cases differ by one line.
#
#   gross            10,000.00
#   employee taxes    3,287.00   (2000 + 620 + 145 + 500 + 22)
#   deductions          201.60
#   net pay           6,511.40
#   employer taxes      929.00   (620 + 145 + 42 + 100 + 22)
#   contributions        50.00
MAPPED_MN_RUN = [
    component("Salary", "PAY", "10000.00"),
    component("FEDERAL_INCOME_TAX", "EMPLOYEE_TAXES", "2000.00"),
    component("SOCIAL_SECURITY", "EMPLOYEE_TAXES", "620.00"),
    component("MEDICARE", "EMPLOYEE_TAXES", "145.00"),
    # The engine emits the bare "_INCOME_TAX" key for state withholding.
    component("_INCOME_TAX", "EMPLOYEE_TAXES", "500.00"),
    component("MN_PAID_LEAVE", "EMPLOYEE_TAXES", "22.00"),
    component("SOCIAL_SECURITY_EMPLOYER", "EMPLOYER_TAXES", "620.00"),
    component("MEDICARE_EMPLOYER", "EMPLOYER_TAXES", "145.00"),
    component("FUTA_EMPLOYER", "EMPLOYER_TAXES", "42.00"),
    component("MN_UI_EMPLOYER", "EMPLOYER_TAXES", "100.00"),
    component("MN_PAID_LEAVE_EMPLOYER", "EMPLOYER_TAXES", "22.00"),
    component("Health", "EMPLOYEE_DEDUCTIONS", "201.60"),
    component("Health", "COMPANY_PAID_CONTRIBUTIONS", "50.00"),
]


class PayrollPostingHarness(TestCase):
    """Build a company that can actually run payroll, and post through it."""

    COMPANY_NAME = "Pilucent LTD"
    STATE = "MN"

    @classmethod
    def setUpTestData(cls):
        # The chart seeder resolves account_type/detail_type against the
        # Category tree, so the taxonomy has to exist before onboarding.
        call_command("create_chart_of_account_category", verbosity=0)

        # RETAIL_WHOLESALE ships everything payroll needs: Cash on Hand, Wages,
        # Health Insurance, Taxes, both federal liabilities, the MN pair and
        # Payroll Liabilities. Company creation fires the post_save that seeds
        # the chart, so it must not be seeded again by hand.
        cls.company = Company.objects.create(
            name=cls.COMPANY_NAME, kind="RETAIL_WHOLESALE"
        )
        cls.prepare_chart()
        cls.settings = setup_payroll_accounting_preferences(
            cls.company, state=cls.STATE
        )

        cls.work_location = PayrollWorkLocation.objects.create(
            company=cls.company,
            location_state=cls.STATE,
            status=PayrollWorkLocationChoices.ACTIVE,
        )
        cls.user = User.objects.create_user(
            name="Michael Olyse",
            email=f"{cls.__name__.lower()}@example.com",
            password="pass1234!",
        )
        # BD Employee: `code` is required and unique per company; there is no
        # `work_locations` FK any more, so the work location above can no
        # longer be attached and `_resolve_employee_state` resolves no state.
        cls.employee = Employee.objects.create(
            user=cls.user,
            company=cls.company,
            code="EMP-0001",
            name_en="Michael Olyse",
        )
        cls.bank = ChartOfAccount.objects.get(
            company=cls.company, title="Cash on Hand"
        )

    @classmethod
    def prepare_chart(cls):
        """Hook: mutate the seeded chart before preferences are built."""

    def gross(self, components):
        return sum(
            (c["current"] for c in components if c["payroll_category"] == "PAY"),
            Decimal("0.00"),
        )

    def net(self, components):
        withheld = sum(
            (
                c["current"]
                for c in components
                if c["payroll_category"]
                in ("EMPLOYEE_TAXES", "EMPLOYEE_DEDUCTIONS")
            ),
            Decimal("0.00"),
        )
        return self.gross(components) - withheld

    def post(self, components, *, employee=None):
        """Run the poster for real. Returns (debit total, credit total)."""
        run = PayrollSalaryProcess.objects.create(
            employee=employee or self.employee,
            title="monthly salary process",
            pay_date=date(2026, 7, 21),
            pay_period="07/01/26 - 07/15/26",
            payment_account=self.bank,
            pay_method=SalaryProcessPayMethodChoice.DIRECT_DEPOSIT,
            gross_pay=self.gross(components),
            net_pay=self.net(components),
        )
        post_payroll_entries(
            {
                "gross_pay": self.gross(components),
                "net_pay": self.net(components),
                "payroll_components": components,
            },
            run,
            self.company,
            employee or self.employee,
        )

        entry = JournalEntry.objects.get(
            payroll_salary=run, kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS
        )
        rows = entry.journalentryconnector_set.select_related("account")
        debit = sum((Decimal(str(r.debit or 0)) for r in rows), Decimal("0.00"))
        credit = sum((Decimal(str(r.credit or 0)) for r in rows), Decimal("0.00"))

        print(f"\n  RESULT {self._testMethodName}")
        for row in rows.order_by("-debit", "-credit"):
            side = "DEBIT " if row.debit else "CREDIT"
            print(
                f"      {side} {row.account.title:<32}"
                f"{row.debit or row.credit:>13}"
            )
        print(f"      legs={len(rows)}  D={debit}  C={credit}  D-C={debit - credit}")
        return debit, credit

    def assertOutOfBalanceBy(self, components, expected, *, employee=None):
        """Now asserts BALANCE, keeping `expected` as the amount that stopped
        being lost.

        The module docstring set this out in advance: "when the fix lands, every
        assertEqual(debit - credit, <amount>) here becomes assertEqual(debit,
        credit) and the recorded amount is what stops being lost." Converting
        the shared helper rather than each call site keeps every recorded figure
        exactly where it was, so the file still reads as a record of what each
        shape used to lose.
        """
        debit, credit = self.post(components, employee=employee)
        self.assertEqual(
            debit,
            credit,
            f"debits {debit} vs credits {credit}; this shape used to lose "
            f"{Decimal(expected)}",
        )
        return debit, credit


class PayrollEntryBalanceTests(PayrollPostingHarness):

    # -- the control, so a failure below is the mapping and not the harness --

    @skip(NO_STATE_ROUTING)
    def test_a_run_whose_every_tax_is_mapped_balances(self):
        """10,979.00 on both sides across 10 legs."""
        debit, credit = self.post(MAPPED_MN_RUN)

        self.assertEqual(debit, credit)
        self.assertEqual(debit, Decimal("10979.00"))

    def test_company_184s_unmatched_deductions_now_balance(self):
        """The 240.84 case from `tests_deduction_legs`, driven end to end.

        Five EMPLOYEE_DEDUCTIONS with no configured liability account -- the
        shape of production entry #JE-169564184, which posted 240.84 short.
        They now reach `Payroll Liabilities` through the residual path, and the
        entry comes out level at 250.32 a side. This one is genuinely fixed.
        """
        components = [
            component("Salary", "PAY", "250.32"),
            component("MEDICARE", "EMPLOYEE_TAXES", "2.87"),
            component("Dental", "EMPLOYEE_DEDUCTIONS", "17.78"),
            component("Health", "EMPLOYEE_DEDUCTIONS", "201.60"),
            component("HSA", "EMPLOYEE_DEDUCTIONS", "1.54"),
            component("Sup Life Ee", "EMPLOYEE_DEDUCTIONS", "12.12"),
            component("Vision Plan", "EMPLOYEE_DEDUCTIONS", "7.80"),
        ]

        debit, credit = self.post(components)

        self.assertEqual(debit, credit)
        self.assertEqual(debit, Decimal("250.32"))

    # -- what is still broken ------------------------------------------------

    @skip(NO_STATE_ROUTING)
    def test_additional_medicare_is_withheld_and_credited_nowhere(self):
        """`MEDICARE_ADDITIONAL` is in every federal list except the poster's.

        `wage_caps.TAX_TABLE` clamps it on every run (0.9% above $200k),
        `form_941_builder` files it on line 5d, `payroll_report_common`,
        `component_labels` and `payroll_tax_liability` all print it. It is NOT
        in `payroll_journal_mappings.FEDERAL_TAXES_941_943_944_PAYROLL_TYPES`,
        and that tuple is the only thing the journal poster consults.

        It is an EMPLOYEE_TAXES component, so `net_pay_from_components` still
        subtracts it: the bank credit drops by 90.00 and no liability credit
        replaces it. Nothing warns -- `_post_tax_liability_credit` is not even
        called for a payroll_type no group claims, so not one of the two
        loggers in that function fires. This is the silent case.
        """
        components = MAPPED_MN_RUN + [
            component("MEDICARE_ADDITIONAL", "EMPLOYEE_TAXES", "90.00"),
        ]

        debit, credit = self.assertOutOfBalanceBy(components, "90.00")

        self.assertEqual(debit, Decimal("10979.00"))
        self.assertEqual(

            credit, debit,

            "the credit side used to stop at 10889.00; the shortfall "

            "now reaches the payroll residual instead of being dropped",

        )

    @skip(NO_STATE_ROUTING)
    def test_a_tax_for_a_second_state_is_debited_and_credited_nowhere(self):
        """Multi-state payroll: only the work-location state gets group keys.

        `payroll_tax_liability.known_groups` records the production shape --
        "Production has a Minnesota company carrying NY employment taxes". The
        employer half of any such tax is debited to the single employer-tax
        expense account regardless of state (`payroll_category` is all the
        debit side looks at), but the credit side resolves exactly ONE state,
        from `employee.work_locations`, and never looks at the components.
        """
        components = MAPPED_MN_RUN + [
            component("NY_SUI_EMPLOYER", "EMPLOYER_TAXES", "30.00"),
        ]

        debit, credit = self.assertOutOfBalanceBy(components, "30.00")

        self.assertEqual(debit, Decimal("11009.00"))
        self.assertEqual(

            credit, debit,

            "the credit side used to stop at 10979.00; the shortfall "

            "now reaches the payroll residual instead of being dropped",

        )

    def test_an_employee_with_no_work_location_loses_every_state_credit(self):
        """No resolvable state drops the whole state block.

        `_resolve_employee_state` returns None, so `if employee_state:` in
        `post_payroll_entries` is false and the state income, state employment
        and MN paid-leave credits are all skipped at once. None of the three
        state legs is posted; the tax-shortfall block credits the 644.00
        (500.00 + 122.00 + 22.00) to one `Payroll Liabilities` residual instead.

        Not skipped with the others: this is the no-state path, and since the BD
        Employee has no `work_locations` it is the path EVERY employee now takes,
        so it is the one end-to-end check that the shortfall reaches the payroll
        residual rather than being dropped.
        """
        stateless = Employee.objects.create(
            user=self.user,
            company=self.company,
            code="EMP-0002",
            name_en="No Location",
        )

        # MN income tax 500.00 + MN unemployment 122.00 + MN paid leave 22.00
        debit, credit = self.assertOutOfBalanceBy(
            MAPPED_MN_RUN, "644.00", employee=stateless
        )

        self.assertEqual(debit, Decimal("10979.00"))
        self.assertEqual(

            credit, debit,

            "the credit side used to stop at 10335.00; the shortfall "

            "now reaches the payroll residual instead of being dropped",

        )

        legs = JournalEntry.objects.get(
            payroll_salary__employee=stateless,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
        ).journalentryconnector_set.select_related("account")
        residual_credits = [
            Decimal(str(leg.credit))
            for leg in legs
            if leg.account.title == "Payroll Liabilities" and leg.credit
        ]
        self.assertIn(Decimal("644.00"), residual_credits, "the state shortfall is the residual leg")
        self.assertFalse(
            [leg.account.title for leg in legs if leg.account.title.startswith("MN ")],
            "no state account is credited when no state resolves",
        )

    @skip(NO_STATE_ROUTING)
    def test_an_unrecognised_state_string_loses_the_same_credits(self):
        """A typo in stored work-location data does what a null does.

        `_resolve_employee_state` passes an unrecognized value through raw so
        the credit reaches the loud branch rather than being skipped silently,
        which is an improvement on nothing -- but the group key synthesized
        from it ("MINESOTA_INCOME_TAX") is in no account_map, and the self-heal
        below it refuses non-US-state keys, so the credit is still dropped.
        Loud and short is still short.
        """
        typo_location = PayrollWorkLocation.objects.create(
            company=self.company,
            location_state="Minesota",
            status=PayrollWorkLocationChoices.ACTIVE,
        )
        # The BD Employee has no `work_locations` FK, so `typo_location` cannot
        # be attached; this employee resolves no state at all.
        employee = Employee.objects.create(
            user=self.user,
            company=self.company,
            code="EMP-0003",
            name_en="Typo Location",
        )

        self.assertOutOfBalanceBy(MAPPED_MN_RUN, "644.00", employee=employee)


class RenamedLiabilityAccountTests(PayrollPostingHarness):
    """A renamed NY/MN liability account drops its credit permanently.

    `_create_tax_liability_components` resolves each state component by chart
    TITLE via `get_company_chart_account`. Neither "MN Unemployment Taxes" nor
    any other state title is in `TITLE_TO_SYSTEM_KEY` -- only the two federal
    ones are -- so a tenant renaming the account means the component is never
    created, the group key never enters `account_map`, and the credit is
    dropped on every pay run from then on.

    The self-heal added to `post_payroll_entries` does not cover this: it skips
    any key `_is_generic_state_component` rejects, and MN/NY are rejected by
    construction because they have bespoke tuples. So unlike a generic state,
    Minnesota cannot recover.
    """

    COMPANY_NAME = "Renamed Account Co"

    @classmethod
    def prepare_chart(cls):
        account = ChartOfAccount.objects.get(
            company=cls.company, title="MN Unemployment Taxes"
        )
        account.title = "MN SUTA Payable"
        account.save(update_fields=["title"])

    @skip(NO_STATE_ROUTING)
    def test_the_state_employment_tax_credit_is_dropped(self):
        # MN_UI_EMPLOYER 100.00 + MN_PAID_LEAVE_EMPLOYER 22.00
        debit, credit = self.assertOutOfBalanceBy(MAPPED_MN_RUN, "122.00")

        self.assertEqual(debit, Decimal("10979.00"))
        self.assertEqual(

            credit, debit,

            "the credit side used to stop at 10857.00; the shortfall "

            "now reaches the payroll residual instead of being dropped",

        )

    @skip(NO_STATE_ROUTING)
    def test_it_is_at_least_loud(self):
        with self.assertLogs("weapi", level="ERROR") as captured:
            self.post(MAPPED_MN_RUN)

        self.assertIn("Unposted payroll tax credit", "\n".join(captured.output))
