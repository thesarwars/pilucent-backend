"""Every payroll deduction must reach a liability, or be reported.

Company 184 "Balanzify LTD", payroll process 180, journal 2699, out by 240.840.

    gross_pay 250.32, employee_taxes_deductions 243.71, net_pay 6.61

Its EMPLOYEE_DEDUCTIONS total exactly the imbalance:

    Dental 17.78 + Health 201.60 + HSA 1.54 + Sup Life Ee 12.12 + Vision Plan 7.80
      = 240.84

They are withheld from net pay -- so the wage debit carries them -- and none
reached a liability account. Two of the five HAVE accounts configured:

    account_type='SUP_LIFE_EE' -> ChartOfAccount 9839 "SUP LIFE EE"
    account_type='HEALTH'      -> ChartOfAccount 9794 "Health Insurance"

and never matched them, because the matcher compared 'Health' to 'HEALTH' by
exact string equality. The other three -- 27.12 between them -- have no
configured account at all, so a matcher fix alone would still lose them.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from payrollio.django_rest.helpers.payroll_journal_mappings import (
    normalize_liability_key,
    payroll_type_matches_other_liability,
)

from weapi.django_rest.helpers.salary_process_journal_entry import (
    _post_other_liability_withholding,
)


class Configured:
    """Stands in for a PayrollAccountExpenseAccountComponent row."""

    def __init__(self, account_type, expense_account):
        self.account_type = account_type
        self.expense_account = expense_account


def deduction(payroll_type, current, category="EMPLOYEE_DEDUCTIONS"):
    return {
        "payroll_type": payroll_type,
        "payroll_category": category,
        "current": Decimal(str(current)),
    }


COMPANY_184_DEDUCTIONS = [
    deduction("Dental", "17.78"),
    deduction("Health", "201.60"),
    deduction("HSA", "1.54"),
    deduction("Sup Life Ee", "12.12"),
    deduction("Vision Plan", "7.80"),
]


class MatcherNormalisationTests(TestCase):
    def test_the_two_production_pairs_now_match(self):
        self.assertTrue(payroll_type_matches_other_liability("HEALTH", "Health"))
        self.assertTrue(
            payroll_type_matches_other_liability("SUP_LIFE_EE", "Sup Life Ee")
        )

    def test_distinct_concepts_stay_distinct(self):
        # "Retirement 401k"/"Retirement Plan" are NOT here on purpose: the alias
        # table pairs them deliberately, so they are supposed to match.
        self.assertFalse(
            payroll_type_matches_other_liability("HEALTH", "Health Insurance")
        )
        self.assertFalse(payroll_type_matches_other_liability("DENTAL", "Vision Plan"))
        self.assertFalse(payroll_type_matches_other_liability("HSA", "Health"))
        self.assertFalse(
            payroll_type_matches_other_liability("SUP_LIFE_EE", "Sup Life Er")
        )

    def test_the_existing_alias_pairs_still_match(self):
        self.assertTrue(
            payroll_type_matches_other_liability("Health Insurance", "Health Ins.")
        )
        self.assertTrue(
            payroll_type_matches_other_liability("Retirement 401k", "Retirement 401(k)")
        )

    def test_normalisation_is_what_it_says(self):
        self.assertEqual(normalize_liability_key("Sup Life Ee"), "SUP_LIFE_EE")
        self.assertEqual(normalize_liability_key("Child/Spouse Support"),
                         "CHILD_SPOUSE_SUPPORT")


class OtherLiabilityWithholdingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Balanzify LTD")

    def account(self, title, kind=ChartOfAccountKindChoices.LIABILITIES):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def setUp(self):
        super().setUp()
        # Typed EXPENSES on purpose: that is how production has them.
        self.sup_life = self.account("SUP LIFE EE", ChartOfAccountKindChoices.EXPENSES)
        self.health = self.account(
            "Health Insurance", ChartOfAccountKindChoices.EXPENSES
        )
        self.residual = self.account("Payroll Liabilities")
        self.configured = [
            Configured("SUP_LIFE_EE", self.sup_life),
            Configured("HEALTH", self.health),
        ]

    def run_legs(self, components, configured=None):
        rows = []
        _post_other_liability_withholding(
            rows,
            self.configured if configured is None else configured,
            components,
            self.company,
        )
        return {row[0].title: row[2] for row in rows}

    def test_every_deduction_reaches_an_account(self):
        """The whole 240.84, split between configured and residual."""
        posted = self.run_legs(COMPANY_184_DEDUCTIONS)

        self.assertEqual(posted["Health Insurance"], Decimal("201.60"))
        self.assertEqual(posted["SUP LIFE EE"], Decimal("12.12"))
        # Dental 17.78 + HSA 1.54 + Vision Plan 7.80
        self.assertEqual(posted["Payroll Liabilities"], Decimal("27.12"))
        self.assertEqual(sum(posted.values()), Decimal("240.84"))

    def test_nothing_is_credited_twice(self):
        """The old loop asked each account which components matched it.

        A component matching two configured accounts was credited to both.
        """
        posted = self.run_legs(
            [deduction("Health", "201.60")],
            configured=[
                Configured("HEALTH", self.health),
                Configured("Health", self.health),
            ],
        )

        self.assertEqual(sum(posted.values()), Decimal("201.60"))

    def test_employer_contributions_go_through_the_same_path(self):
        posted = self.run_legs([
            deduction("Health", "50.00", category="COMPANY_PAID_CONTRIBUTIONS"),
        ])

        self.assertEqual(posted["Health Insurance"], Decimal("50.00"))

    def test_unrelated_categories_are_ignored(self):
        posted = self.run_legs([
            deduction("Salary", "250.32", category="PAY"),
            deduction("MEDICARE", "0.34", category="EMPLOYEE_TAXES"),
        ])

        self.assertEqual(posted, {})

    def test_a_missing_residual_account_is_created_rather_than_reported(self):
        """Supersedes "reports rather than swallowing".

        That test recorded a real improvement at the time -- the path had been
        dropping the deduction silently, and it was changed to log loudly. But
        loudly still meant the wage debit carried the deduction with no matching
        credit, and `assert_entry_balances` logs rather than raising, so the
        short entry committed anyway.

        Reporting was never the goal; it was the best available answer while the
        account might not exist. It now always can: the residual account is
        created on demand and resolved by `system_key`. Only 17 of 60 production
        companies had one, so this path could not resolve for the other 43.

        The loud part is kept, and asserted by
        `test_the_unmatched_components_are_named_in_the_log`: an unmapped
        deduction still names itself in the log, because landing in the residual
        account is a thing somebody should go and configure properly.
        """
        self.residual.delete()

        posted = self.run_legs(COMPANY_184_DEDUCTIONS)

        self.assertIn(
            "Payroll Liabilities",
            posted,
            "the deduction had nowhere to go, so the entry posted short",
        )

    def test_the_unmatched_components_are_named_in_the_log(self):
        with self.assertLogs("weapi", level="ERROR") as captured:
            self.run_legs(COMPANY_184_DEDUCTIONS)

        message = "\n".join(captured.output)
        for name in ("Dental", "HSA", "Vision Plan"):
            self.assertIn(name, message)
