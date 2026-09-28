"""Amending or deleting a hand-keyed journal entry moved no stored balance.

`update_opening_balance` appeared exactly once in the manual journal-entry
serializer -- in `create`. So of the three paths on the one document a bookkeeper
writes by hand:

* **create** moved the balance, correctly, since `6aed4300` fixed its direction
* **update** rewrote the legs and left every account asserting the pre-edit figure
* **delete** set `status = REMOVED` and left the balance where the posting put it

That is the posting-leg mirror rule stated as plainly as it gets: the create
path's direction bug was fixed and its two mirrors were left alone, so two of the
three paths stayed wrong. Both are live sources of exactly the drift
`repair_account_balances` measures.

The delete posts a REVERSAL rather than simply moving the balance back, and the
reversal is REMOVED rather than PUBLISHED. Both choices are load-bearing and each
has a test here: the legs of a REMOVED entry stay in the table and every balance
derivation sums them regardless of status, so backing the balance out without
cancelling the legs would make the account newly disagree with its own journal --
and a PUBLISHED half of the pair would put the deleted entry back in the journal
list, which reads `get_status_all()`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector


class FakeRequest:
    def __init__(self, user):
        self.user = user


class ManualEntryTestCase(TestCase):
    """A hand-keyed entry: DEBIT Rent 400, CREDIT City Bank 400."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="J", email="jedel@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)

        self.bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "1600")
        self.rent = self.account("Rent", ChartOfAccountKindChoices.EXPENSES, "400")
        self.other = self.account(
            "Utilities", ChartOfAccountKindChoices.EXPENSES, "0"
        )

        self.entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.JOURNAL_ENTRY,
            status=JournalEntryStatusChoices.PUBLISHED, date=date(2026, 3, 1),
            amount=Decimal("400"), entry_number="#JE-1",
        )
        self.debit_leg = self.leg(
            self.rent, debit="400", kind=JournalEntryConnectorKindChoices.DEBIT
        )
        self.credit_leg = self.leg(
            self.bank, credit="400", kind=JournalEntryConnectorKindChoices.CREDIT
        )

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def leg(self, account, debit="0", credit="0", kind=None):
        return JournalEntryConnector.objects.create(
            journal=self.entry, account=account, date=date(2026, 3, 1),
            debit=Decimal(debit), credit=Decimal(credit), kind=kind,
        )

    def balances(self):
        for account in (self.bank, self.rent, self.other):
            account.refresh_from_db()
        return (
            self.bank.opening_balance,
            self.rent.opening_balance,
            self.other.opening_balance,
        )

    def delete(self):
        from weapi.django_rest.views.journals import PrivateWeJournalEntryDetails

        view = PrivateWeJournalEntryDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.entry)

    def derived(self, account):
        """The all-legs total, the way `account_balance_as_of` computes it."""
        from common.django_rest.helpers.ledger_balances import account_balance_as_of

        return account_balance_as_of(account)


class TheOldDeleteLeftTheBalanceBehindTests(ManualEntryTestCase):
    def test_status_alone_moved_nothing(self):
        self.entry.status = JournalEntryStatusChoices.REMOVED
        self.entry.save()

        self.assertEqual(
            self.balances(),
            (Decimal("1600.000"), Decimal("400.000"), Decimal("0.000")),
        )


class DeletingNowMovesTheBalanceBackTests(ManualEntryTestCase):
    def test_the_stored_balances_return_to_where_they_started(self):
        self.delete()
        self.assertEqual(
            self.balances(),
            (Decimal("2000.000"), Decimal("0.000"), Decimal("0.000")),
        )

    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.exclude(pk=self.entry.pk).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_the_reversal_is_removed_so_the_journal_list_shows_neither(self):
        """The list reads `get_status_all()`, which excludes REMOVED only."""
        self.delete()

        visible = JournalEntry.objects.get_status_all().filter(company=self.company)
        self.assertEqual(visible.count(), 0)

    def test_the_delete_introduces_no_new_disagreement(self):
        """Moving the balance back WITHOUT cancelling the legs would drift.

        The legs of a REMOVED entry stay in the table and every balance
        derivation sums them whatever their status. Backing the balance out on
        its own would leave the stored column lower than the legs still say, so
        the reversal is what keeps the two moving together.

        Stated as drift preservation rather than as equality, because these
        accounts carry a real opening balance that no journal leg represents --
        `City Bank` stands at 2,000 before this entry exists. The invariant a
        delete owes is not "stored equals the ledger", which was never true
        here; it is "deleting changes the gap between them by nothing".
        """
        before = {
            account.pk: Decimal(account.opening_balance) - self.derived(account)
            for account in (self.bank, self.rent)
        }

        self.delete()

        for account in (self.bank, self.rent):
            account.refresh_from_db()
            self.assertEqual(
                Decimal(account.opening_balance) - self.derived(account),
                before[account.pk],
                f"{account.title} drifted as a result of the delete",
            )

    def test_the_reversal_is_dated_to_the_entry_not_to_today(self):
        self.delete()
        reversal = JournalEntry.objects.exclude(pk=self.entry.pk).get()
        self.assertEqual(reversal.date, date(2026, 3, 1))

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = self.balances()
        self.delete()
        self.assertEqual(self.balances(), after)

    def test_a_reconciled_entry_is_refused(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"), beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=self.credit_leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        before = self.balances()

        with self.assertRaises(ReconciledLineLocked):
            self.delete()

        self.entry.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertNotEqual(self.entry.status, JournalEntryStatusChoices.REMOVED)


class AmendingNowMovesTheBalanceTests(ManualEntryTestCase):
    """`update_opening_balance` was absent from `update` entirely."""

    def amend(self, items):
        from weapi.django_rest.serializers.journals import (
            PrivateWeJournalEntryDetailsSerializer,
        )

        serializer = PrivateWeJournalEntryDetailsSerializer()
        serializer.context["request"] = FakeRequest(self.user)
        return serializer.update(self.entry, {"journal_items": items})

    def test_changing_an_amount_moves_both_accounts(self):
        self.amend([
            {
                "uid": str(self.debit_leg.uid),
                "account_uid": str(self.rent.uid),
                "debit": "500", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            },
        ])

        self.rent.refresh_from_db()
        self.assertEqual(self.rent.opening_balance, Decimal("500.000"))

    def test_moving_a_line_to_another_account_takes_it_off_the_first(self):
        """The old leg is backed out against its OLD account."""
        self.amend([
            {
                "uid": str(self.debit_leg.uid),
                "account_uid": str(self.other.uid),
                "debit": "400", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            },
        ])

        self.rent.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.rent.opening_balance, Decimal("0.000"))
        self.assertEqual(self.other.opening_balance, Decimal("400.000"))

    def test_flipping_a_side_moves_the_balance_the_other_way(self):
        self.amend([
            {
                "uid": str(self.credit_leg.uid),
                "account_uid": str(self.bank.uid),
                "debit": "400", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            },
        ])

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.opening_balance, Decimal("2400.000"))

    def test_an_amend_introduces_no_new_disagreement(self):
        before = {
            account.pk: Decimal(account.opening_balance) - self.derived(account)
            for account in (self.bank, self.rent, self.other)
        }

        self.amend([
            {
                "uid": str(self.debit_leg.uid),
                "account_uid": str(self.rent.uid),
                "debit": "500", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            },
        ])

        for account in (self.bank, self.rent, self.other):
            account.refresh_from_db()
            self.assertEqual(
                Decimal(account.opening_balance) - self.derived(account),
                before[account.pk],
                f"{account.title} drifted as a result of the amend",
            )

    def test_adding_a_line_moves_its_account_too(self):
        self.amend([
            {
                "account_uid": str(self.other.uid),
                "debit": "75", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            },
        ])

        self.other.refresh_from_db()
        self.assertEqual(self.other.opening_balance, Decimal("75.000"))
        self.assertEqual(self.other.opening_balance, self.derived(self.other))

    def test_a_line_from_another_entry_is_still_refused(self):
        """The scoping fix must survive the balance work."""
        from rest_framework.serializers import ValidationError

        other_entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.JOURNAL_ENTRY,
            status=JournalEntryStatusChoices.PUBLISHED, amount=Decimal("10"),
        )
        stranger = JournalEntryConnector.objects.create(
            journal=other_entry, account=self.other, date=date(2026, 3, 1),
            debit=Decimal("10"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        before = self.balances()

        with self.assertRaises(ValidationError):
            self.amend([
                {
                    "uid": str(stranger.uid),
                    "account_uid": str(self.other.uid),
                    "debit": "999", "credit": "0",
                    "kind": JournalEntryConnectorKindChoices.DEBIT,
                },
            ])

        self.assertEqual(self.balances(), before)


class ItRefusesToGuessASideTests(ManualEntryTestCase):
    """`action_for_side` defaults to "addition", which is a wrong answer."""

    def test_a_line_with_no_posting_side_moves_no_balance(self):
        """Reachable: `JournalEntryConnector.kind` has no model default.

        A line added through the amend path without a `kind` lands with an empty
        string. Deriving an action from that gives "addition" -- correct for
        assets and expenses, backwards for liabilities, equity and income, and
        silent either way.
        """
        from weapi.django_rest.helpers.journal_entry_posting import move_leg_balance

        before = self.other.opening_balance
        moved = move_leg_balance(self.other, "", Decimal("50"))

        self.other.refresh_from_db()
        self.assertEqual(moved, Decimal("0.000"))
        self.assertEqual(self.other.opening_balance, before)

    def test_a_real_side_still_moves(self):
        from weapi.django_rest.helpers.journal_entry_posting import move_leg_balance

        move_leg_balance(
            self.other, JournalEntryConnectorKindChoices.DEBIT, Decimal("50")
        )

        self.other.refresh_from_db()
        self.assertEqual(self.other.opening_balance, Decimal("50.000"))
