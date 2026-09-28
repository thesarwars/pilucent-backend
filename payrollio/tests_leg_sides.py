"""`_post_credit` must credit, and `_post_debit` must debit, on any account kind.

Both used to hard-code the action `"addition"` and differ only in the
`update_opening_balance` argument. `"addition"` resolves to DEBIT on assets and
expenses and CREDIT on liabilities, equity and income, so neither helper did
what its name said once handed an account of the wrong kind -- and the journal
and the stored balance moved in opposite directions.

Company 184's two configured payroll deduction accounts are both
`kind=EXPENSES`:

    id=9794 'Health Insurance'  kind='EXPENSES'  type='Expense'                   lines=0
    id=9839 'SUP LIFE EE'       kind='EXPENSES'  type='Other Current Liabilities' lines=0

so every deduction credit routed to them would have landed on the debit side.
That is why fixing the payroll_type matcher FIRST would have taken company 184
from 240.84 out of balance to roughly 442.44 out.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import get_debit_or_credit

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices

from weapi.django_rest.helpers.salary_process_journal_entry import (
    _post_credit,
    _post_debit,
)


class PayrollLegSideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, kind, opening="1000"):
        return ChartOfAccount.objects.create(
            company=self.company, title=f"Acct {kind}", kind=kind,
            opening_balance=Decimal(opening),
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def side_of(self, account, action):
        return get_debit_or_credit(account.kind)[action]

    def test_credit_lands_on_the_credit_side_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                account = self.account(kind)
                rows = []

                _post_credit(rows, account, Decimal("201.60"))

                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    self.side_of(account, rows[0][1]),
                    JournalEntryConnectorKindChoices.CREDIT,
                )

    def test_debit_lands_on_the_debit_side_for_every_kind(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                account = self.account(kind)
                rows = []

                _post_debit(rows, account, Decimal("250.32"))

                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    self.side_of(account, rows[0][1]),
                    JournalEntryConnectorKindChoices.DEBIT,
                )

    def test_the_expense_typed_deduction_account_is_credited(self):
        """Company 184's exact shape: a deduction account typed as an expense."""
        account = self.account(ChartOfAccountKindChoices.EXPENSES)
        rows = []

        _post_credit(rows, account, Decimal("201.60"))

        self.assertEqual(
            self.side_of(account, rows[0][1]),
            JournalEntryConnectorKindChoices.CREDIT,
        )

    def test_the_stored_balance_moves_with_the_journal_not_against_it(self):
        """The second half: balance and journal used to move opposite ways."""
        account = self.account(ChartOfAccountKindChoices.EXPENSES, opening="1000")
        before = Decimal(str(account.opening_balance))
        rows = []

        _post_credit(rows, account, Decimal("201.60"))

        account.refresh_from_db()
        after = Decimal(str(account.opening_balance))
        # A credit to an expense account reduces it.
        self.assertEqual(after, before - Decimal("201.60"))

    def test_a_liability_account_is_unchanged(self):
        """The ordinary, correctly-typed case must behave exactly as before."""
        account = self.account(ChartOfAccountKindChoices.LIABILITIES, opening="1000")
        rows = []

        _post_credit(rows, account, Decimal("201.60"))

        self.assertEqual(rows[0][1], "addition")
        account.refresh_from_db()
        self.assertEqual(
            Decimal(str(account.opening_balance)), Decimal("1000") + Decimal("201.60")
        )

    def test_zero_and_missing_accounts_are_skipped(self):
        rows = []
        _post_credit(rows, None, Decimal("10"))
        _post_credit(rows, self.account(ChartOfAccountKindChoices.LIABILITIES), 0)
        self.assertEqual(rows, [])
