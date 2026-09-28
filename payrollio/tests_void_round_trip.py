"""Posting a payroll and voiding it must leave every balance where it started.

Two defects, both found by auditing the plan against the code.

**The bank leg moved the journal and the balance opposite ways.** The net-pay
line was written out rather than going through `_post_credit`:

    update_opening_balance(bank_account, "credit", net_pay, 0)   # add
    _append_connector_line(..., "substraction", net_pay)         # CREDIT on an asset

`"substraction"` is a CREDIT on an asset -- money leaving the bank, correct --
and its matching balance operation is "debit", subtract. The call said "credit",
add. Journal down, stored balance up, every run.

**Voiding doubled instead of reversing.** `void_payroll` computed the opposite
accounting SIDE and passed it to `update_opening_balance`, whose CREDIT/DEBIT
argument means add/subtract. A wage expense posts DEBIT and ADDS; its inverse
side is CREDIT, which adds again.

Together they make the round trip the honest test: post, void, and every account
must be back where it began.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from accounts.models import User

from common.django_rest.helpers.balance_helpers import (
    get_debit_or_credit,
    get_migration_undo_balance_operation,
    update_opening_balance,
)

from companyio.models import Company

from employeeio.models import Employee

from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.django_rest.helpers.void_payroll import reverse_payroll_entries
from payrollio.models import PayrollSalaryProcess

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.salary_process_journal_entry import (
    _post_credit,
    _post_debit,
)


class LegRoundTripTests(TestCase):
    """Post a leg, then undo it the way `void_payroll` now does."""

    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Balanzify LTD")

    _seq = 0

    def account(self, kind):
        # Unique per call -- see unique_title_per_company_ci.
        type(self)._seq += 1
        return ChartOfAccount.objects.create(
            company=self.company, title=f"Acct {kind} #{type(self)._seq}", kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def post_then_void(self, kind, poster):
        account = self.account(kind)
        rows = []
        poster(rows, account, Decimal("250.32"))
        account.refresh_from_db()

        # What void_payroll does per connector: resolve the side the leg
        # actually landed on, then undo that.
        from common.django_rest.helpers.balance_helpers import get_debit_or_credit

        posted_side = get_debit_or_credit(account.kind)[rows[0][1]]
        update_opening_balance(
            account,
            get_migration_undo_balance_operation(account, posted_side),
            Decimal("250.32"),
            0,
        )
        account.refresh_from_db()
        return Decimal(str(account.opening_balance))

    def test_a_credit_leg_round_trips_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.post_then_void(kind, _post_credit), self.BASELINE
                )

    def test_a_debit_leg_round_trips_for_every_kind(self):
        """Wages are the case that doubled: an expense posted DEBIT."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.post_then_void(kind, _post_debit), self.BASELINE
                )

    def test_the_bank_leg_takes_money_out(self):
        """Net pay leaves the bank: journal CREDIT, stored balance down."""
        from common.django_rest.helpers.balance_helpers import get_debit_or_credit

        bank = self.account(ChartOfAccountKindChoices.ASSETS)
        rows = []

        _post_credit(rows, bank, Decimal("250.32"))

        self.assertEqual(
            get_debit_or_credit(bank.kind)[rows[0][1]],
            JournalEntryConnectorKindChoices.CREDIT,
        )
        bank.refresh_from_db()
        self.assertEqual(
            Decimal(str(bank.opening_balance)), self.BASELINE - Decimal("250.32")
        )

    def test_the_bank_leg_goes_through_the_paired_helper(self):
        """A source check, and it is standing in for something.

        Driving `post_payroll_entries` end to end needs accounting
        preferences, a component set and an employee. The defect was not in the
        arithmetic but in the bank leg being written out by hand -- its own
        `update_opening_balance` and `_append_connector_line`, which is how the
        two halves came to disagree. So what has to hold is that it routes
        through the helper whose pairing the tests above verify.
        """
        import inspect

        from weapi.django_rest.helpers import salary_process_journal_entry as module

        source = inspect.getsource(module.post_payroll_entries)
        self.assertIn("_post_credit(connector_data, bank_account, net_pay)", source)
        self.assertNotIn("_append_connector_line(connector_data, bank_account", source)

    def test_the_inverse_side_is_not_the_inverse_operation(self):
        """The confusion the void bug rested on, stated directly.

        `update_opening_balance` reads CREDIT/DEBIT as add/subtract, not as an
        accounting side. For an expense posted DEBIT, the inverse SIDE is
        CREDIT -- and CREDIT means add, which is the same direction the posting
        went.
        """
        expense = self.account(ChartOfAccountKindChoices.EXPENSES)
        rows = []
        _post_debit(rows, expense, Decimal("100"))
        expense.refresh_from_db()
        after_post = Decimal(str(expense.opening_balance))
        self.assertEqual(after_post, self.BASELINE + Decimal("100"))

        # The old code's undo: inverse side of DEBIT is CREDIT -> adds again.
        update_opening_balance(
            expense, JournalEntryConnectorKindChoices.CREDIT, Decimal("100"), 0
        )
        expense.refresh_from_db()
        self.assertEqual(
            Decimal(str(expense.opening_balance)), self.BASELINE + Decimal("200"),
            "the old inverse-side undo should double, which is the bug",
        )


class VoidPayrollRoundTripTests(TestCase):
    """Drive `reverse_payroll_entries` for real and check it lands on zero."""

    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Balanzify LTD")
        cls.user = User.objects.create_user(
            name="Michael olyse", email="void-round-trip@example.com",
            password="pass1234!",
        )
        cls.employee = Employee.objects.create(user=cls.user, name="Michael olyse")
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def finalized_run(self):
        return PayrollSalaryProcess.objects.create(
            employee=self.employee, title="monthly salary process",
            pay_date=date(2026, 7, 21), payment_account=self.bank,
            status=PayrollSalaryProcessStatusChoices.FINALIZED,
        )

    def posted(self, kind, poster, amount=Decimal("250.32")):
        """A run whose journal carries one leg, posted the way payroll posts."""
        # Unique per call: this runs once per (kind, leg) subtest, so a
        # kind-only title collides under `unique_title_per_company_ci`.
        type(self)._posted_seq = getattr(type(self), "_posted_seq", 0) + 1
        account = ChartOfAccount.objects.create(
            company=self.company,
            title=f"Acct {kind} posted #{type(self)._posted_seq}",
            kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        run = self.finalized_run()
        entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS,
            payroll_salary=run,
        )
        rows = []
        poster(rows, account, amount)
        account.refresh_from_db()

        posted_side = get_debit_or_credit(account.kind)[rows[0][1]]
        JournalEntryConnector.objects.create(
            journal=entry, account=account, kind=posted_side,
            debit=amount if posted_side == JournalEntryConnectorKindChoices.DEBIT else 0,
            credit=amount if posted_side == JournalEntryConnectorKindChoices.CREDIT else 0,
        )
        return run, account

    def test_voiding_a_wage_expense_clears_it(self):
        """The case that doubled: an expense posted DEBIT."""
        run, account = self.posted(ChartOfAccountKindChoices.EXPENSES, _post_debit)

        reverse_payroll_entries(run)

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_voiding_round_trips_for_every_kind_and_side(self):
        for kind in ChartOfAccountKindChoices.values:
            for poster, label in ((_post_debit, "debit"), (_post_credit, "credit")):
                with self.subTest(kind=kind, leg=label):
                    run, account = self.posted(kind, poster)

                    reverse_payroll_entries(run)

                    account.refresh_from_db()
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )

    def test_the_reversing_connector_takes_the_opposite_side(self):
        """The half `inverse_kind` is still right for."""
        run, account = self.posted(ChartOfAccountKindChoices.EXPENSES, _post_debit)

        reverse_payroll_entries(run)

        rows = JournalEntryConnector.objects.filter(account=account)
        self.assertEqual(rows.count(), 2)
        sides = {r.kind for r in rows}
        self.assertEqual(
            sides,
            {
                JournalEntryConnectorKindChoices.DEBIT,
                JournalEntryConnectorKindChoices.CREDIT,
            },
        )
