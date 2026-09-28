"""Bank reconciliation resolved records by `uid` alone, across tenants.

Three holes, and they only close together.

**The summary endpoint read any reconciliation.** `get_object_or_404(
BankReconciliation, uid=recon_uid)` with no company filter returned another
tenant's beginning balance, statement balance and date, cleared balance,
difference, and both transaction lists in full.

**The match endpoint closed any reconciliation.** `BankReconciliation.objects.get(
uid=...)` was likewise unscoped, and the guard beside it --
`if trx.company != reconciliation.company` -- compares the two *arguments* to
each other, never to the caller. It therefore passed for someone with no
relationship to either, and `save()` went on to clear ledger legs on their
transactions and close their reconciliation.

**And `bank_account_uid` accepted any company's account.** This is the one that
makes the other two insufficient on their own: `create()` stamps `company` from
the request, so a caller could open a reconciliation whose company is *theirs*
and whose bank account is *somebody else's*. That row passes a company-scoped
lookup, and the summary reads transactions by `chart_of_account` -- so the leak
would have survived a fix that only scoped the two lookups.

Gap #40 of `CHART_OF_ACCOUNTS_GAPS.md`; P0.1 of `COA_FIX_PLAN_V3.md`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from transactionio.choices import BankReconciliationStatusChoices

from transactionio.models import BankReconciliation, TransactionInformation


class FakeRequest:
    """Enough request for `serializer.context["request"].user`."""

    def __init__(self, user):
        self.user = user


class ReconcileScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Acme Books")
        cls.company_b = Company.objects.create(name="Beta Ledger")

        cls.user_a = User.objects.create_user(
            name="A", email="a@example.com", password="pass1234!"
        )
        cls.user_b = User.objects.create_user(
            name="B", email="b@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user_a, company=cls.company_a)
        CompanyUser.objects.create(user=cls.user_b, company=cls.company_b)

        cls.bank_a = cls.bank(cls.company_a, "Acme Operating")
        cls.bank_b = cls.bank(cls.company_b, "Beta Operating")

    @classmethod
    def bank(cls, company, title):
        return ChartOfAccount.objects.create(
            company=company, title=title, code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def reconciliation(self, company, account):
        return BankReconciliation.objects.create(
            company=company, bank_account=account,
            beginning_balance=Decimal("0"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 8, 1),
        )

    def txn(self, company, account, received=Decimal("100")):
        """A posted document with a leg on `account`.

        Was a `TransactionInformation` row. Phase 3 made the ledger the
        candidate set, so a statement row is no longer tickable -- and the
        cross-tenant question this suite asks is now asked of journal entries,
        which is the more important place to ask it.
        """
        from journalio.choices import (
            JournalEntryConnectorKindChoices,
            JournalEntryConnectorRequestKindChoices,
            JournalEntryKindChoices,
            JournalEntryStatusChoices,
        )
        from journalio.models import JournalEntry, JournalEntryConnector

        entry = JournalEntry.objects.create(
            company=company, date=date(2026, 7, 1), amount=received,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.BANK_DEPOSIT,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, date=entry.date,
            debit=received, credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            total=received,
        )
        return entry


    def is_cleared(self, entry, account):
        """Did any leg of `entry` on `account` get ticked by a session?

        The tick moved from `TransactionInformation.is_matched` to
        `JournalEntryConnector.reconciliation` in Phase 3, so the cross-tenant
        question is asked of the ledger now.
        """
        from journalio.models import JournalEntryConnector

        return JournalEntryConnector.objects.filter(
            journal=entry, account=account, reconciliation__isnull=False
        ).exists()

    # ------------------------------------------------------------------ match

    def match(self, user, reconciliation, transactions):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        return PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(reconciliation.uid),
                "journal_entry_ids": [str(t.uid) for t in transactions],
            },
            context={"request": FakeRequest(user)},
        )

    def test_b_cannot_close_a_reconciliation_belonging_to_a(self):
        recon = self.reconciliation(self.company_a, self.bank_a)
        txn = self.txn(self.company_a, self.bank_a)

        serializer = self.match(self.user_b, recon, [txn])

        self.assertFalse(serializer.is_valid())
        recon.refresh_from_db()
        txn.refresh_from_db()
        self.assertNotEqual(
            recon.status, BankReconciliationStatusChoices.CLOSED,
            "B closed A's reconciliation",
        )
        self.assertFalse(
            self.is_cleared(txn, self.bank_a), "B cleared A's document"
        )

    def test_a_cannot_match_bs_transactions_onto_their_own_reconciliation(self):
        """The old guard compared the two arguments, never the caller."""
        recon = self.reconciliation(self.company_a, self.bank_a)
        foreign = self.txn(self.company_b, self.bank_b)

        serializer = self.match(self.user_a, recon, [foreign])

        self.assertFalse(serializer.is_valid())
        foreign.refresh_from_db()
        self.assertFalse(self.is_cleared(foreign, self.bank_b))

    def test_a_can_close_their_own(self):
        """The guard must not break the legitimate path."""
        recon = self.reconciliation(self.company_a, self.bank_a)
        txn = self.txn(self.company_a, self.bank_a)

        serializer = self.match(self.user_a, recon, [txn])

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        recon.refresh_from_db()
        txn.refresh_from_db()
        self.assertEqual(recon.status, BankReconciliationStatusChoices.CLOSED)
        self.assertTrue(self.is_cleared(txn, self.bank_a))

    # ---------------------------------------------------------------- summary

    def test_the_summary_lookup_is_company_scoped(self):
        from django.http import Http404
        from rest_framework.generics import get_object_or_404

        recon = self.reconciliation(self.company_a, self.bank_a)

        with self.assertRaises(Http404):
            get_object_or_404(
                BankReconciliation, uid=recon.uid, company=self.company_b
            )
        self.assertEqual(
            get_object_or_404(
                BankReconciliation, uid=recon.uid, company=self.company_a
            ).pk,
            recon.pk,
        )

    def test_the_summary_view_scopes_by_company(self):
        import inspect

        from weapi.django_rest.views.transactions import bank_reconcile

        source = inspect.getsource(bank_reconcile.PrivateWeBankReconciliationSummaryView)
        self.assertIn("company=company", source)
        self.assertNotIn("get_object_or_404(BankReconciliation, uid=recon_uid)", source)

    # ------------------------------------------------- the third hole (create)

    def test_bank_account_uid_rejects_another_companys_account(self):
        """Without this, the two fixes above still leak.

        A reconciliation with `company=A` and `bank_account=B's` passes every
        company-scoped lookup, and the summary reads its transactions by
        account.
        """
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            BankReconciliationListCreateSerializer,
        )

        serializer = BankReconciliationListCreateSerializer(
            context={"request": FakeRequest(self.user_a)}
        )
        allowed = serializer.fields["bank_account_uid"].queryset

        self.assertIn(self.bank_a, allowed)
        self.assertNotIn(self.bank_b, allowed, "A can reconcile B's bank account")

    def test_the_scoping_mixin_is_applied(self):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            BankReconciliationListCreateSerializer as S,
        )
        from common.django_rest.helpers.serializer_scoping import (
            CompanyScopedRelatedFieldsMixin,
        )

        self.assertTrue(issubclass(S, CompanyScopedRelatedFieldsMixin))
