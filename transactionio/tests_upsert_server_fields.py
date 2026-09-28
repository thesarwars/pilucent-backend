"""A CSV upload must not be able to tick its own reconciliation lines.

Item 4 of `NEXT_MODULE_ASSESSMENT.md` section 2.

`TransactionWrapperSerializer` listed `is_matched`, `journal_entry` and
`transaction_status` in `Meta.fields` with none of them in `read_only_fields`.

The reachability is the part worth writing down, because reading the views
alone says the opposite: that serializer's only `serializer_class` is a
`ListAPIView`, and `TransactionDataUpdateSerializer` beside it was imported and
never used at all. Both look read-only. But `UpsertCSVTransactionsSerializer`
nests it --

    transactions = TransactionWrapperSerializer(many=True)

-- and then splats the validated result straight into the model:

    TransactionInformation(**trx, company=company, chart_of_account=...)

so every field it accepts is written on the create path.

**Why `is_matched` in particular.** `reconciliation.cleared_totals()` sums
`received`/`spent` over rows where `is_matched=True`, and
`reconciliation_difference()` reads that -- which is the figure the finish guard
shipped in `9e34c473` refuses to close on when it is nonzero. So a client could
not bypass that guard by calling somewhere else; they could pre-cook the input
it reads until the difference came out zero. A control is only as good as the
data it is computed from.

All three fields default safely -- False, FOR_REVIEW, null -- so an import that
stops sending them behaves identically.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from rest_framework.exceptions import ValidationError

from transactionio.choices import TransactionStatusChoices
from transactionio.models import TransactionInformation


class UpsertCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Feed Co", kind="ECOMMERCE")
        self.other = Company.objects.create(name="Other Co", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="A", email="feed@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)

        self.bank = ChartOfAccount.objects.create(
            company=self.company, title="Checking", code="1010",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.their_bank = ChartOfAccount.objects.create(
            company=self.other, title="Their Checking", code="1010",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def upsert(self, rows, account=None):
        from weapi.django_rest.serializers.transactions.csv_transactions import (
            UpsertCSVTransactionsSerializer,
        )

        serializer = UpsertCSVTransactionsSerializer(
            data={
                "chart_of_account": str((account or self.bank).uid),
                "transactions": rows,
            },
            context={"company": self.company},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()


class ServerManagedFieldsAreNotClientWritableTests(UpsertCase):

    def row(self, **extra):
        base = {
            "date": "2026-05-01",
            "description": "ACME PAYMENT",
            "received": "500.00",
            "spent": "0.00",
        }
        base.update(extra)
        return base

    def test_a_row_claiming_it_is_matched_is_not(self):
        """The guard's input cannot be supplied by the thing it guards."""
        self.upsert([self.row(is_matched=True)])

        written = TransactionInformation.objects.get(company=self.company)
        self.assertFalse(
            written.is_matched,
            "a CSV row ticked itself as reconciled",
        )

    def test_transaction_status_falls_back_to_for_review(self):
        self.upsert([self.row(transaction_status="CATEGORIZED")])

        written = TransactionInformation.objects.get(company=self.company)
        self.assertEqual(
            written.transaction_status, TransactionStatusChoices.FOR_REVIEW
        )

    def test_a_row_cannot_attach_itself_to_a_journal_entry(self):
        self.upsert([self.row()])

        written = TransactionInformation.objects.get(company=self.company)
        self.assertIsNone(written.journal_entry_id)

    def test_the_ordinary_columns_still_import(self):
        """The fix must not make the CSV importer useless."""
        self.upsert([self.row(description="RENT", received="0.00", spent="1200.00")])

        written = TransactionInformation.objects.get(company=self.company)
        self.assertEqual(written.description, "RENT")
        self.assertEqual(Decimal(str(written.spent)), Decimal("1200.00"))


class TheAccountLookupIsScopedTests(UpsertCase):
    """`ChartOfAccount.objects.get(uid=...)` -- unscoped, and a 500 on a miss."""

    def test_another_companys_bank_account_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.upsert(
                [{"date": "2026-05-01", "description": "X",
                  "received": "1.00", "spent": "0.00"}],
                account=self.their_bank,
            )

        self.assertIn("chart_of_account", caught.exception.detail)

    def test_an_unknown_uid_is_a_400_not_a_500(self):
        """`.get()` raised DoesNotExist, which nothing converts."""
        from weapi.django_rest.serializers.transactions.csv_transactions import (
            UpsertCSVTransactionsSerializer,
        )

        serializer = UpsertCSVTransactionsSerializer(
            data={
                "chart_of_account": "11111111-1111-1111-1111-111111111111",
                "transactions": [],
            },
            context={"company": self.company},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("chart_of_account", serializer.errors)

    def test_a_retired_bank_account_is_not_offered(self):
        """Importing rows into an account is data entry.

        A retired account keeps its balance, its history and its place on every
        report -- it is withheld from new activity and nothing else. The picker
        sweep in `accounts/tests/test_inactive_not_offered.py` caught this call
        site the moment it was added and made the classification explicit:
        picker, so narrow it.
        """
        from accounts.choices import ChartOfAccountStatusChoices as Status

        ChartOfAccount.objects.filter(pk=self.bank.pk).update(
            status=Status.INACTIVE
        )

        with self.assertRaises(ValidationError) as caught:
            self.upsert(
                [{"date": "2026-05-01", "description": "X",
                  "received": "1.00", "spent": "0.00"}]
            )

        self.assertIn("chart_of_account", caught.exception.detail)

    def test_the_companys_own_account_still_resolves(self):
        self.upsert([{"date": "2026-05-01", "description": "X",
                      "received": "1.00", "spent": "0.00"}])

        self.assertEqual(
            TransactionInformation.objects.filter(company=self.company).count(), 1
        )
