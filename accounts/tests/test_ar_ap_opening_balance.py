"""An opening balance typed onto A/R or A/P has nobody behind it.

Spec BLZ-FIN-COA-SPEC-001 §9.8 and COA-171: *"Not permitted for A/R and A/P:
open customer and vendor balances must arrive as open invoices and bills so
subledgers reconcile to control accounts."*

The guard covered income and expense accounts and stopped there. A receivable
balance is the **sum of the documents behind it**, and those documents are what
the subledger and the ageing report read. Typing a figure straight onto the
control account puts a number there that no customer owns, so the control
account and its subledger disagree by exactly that amount from the moment it is
entered.

That is not hypothetical. `CUSTOMER_GAPS.md` measures company 165's A/R at
**4,752,073 stored against 2,352,078 in the ledger** — a 2,399,995 gap, with the
customer subledger tying to the ledger exactly and the stored control figure
being the outlier. Every route that moves A/R without a document behind it feeds
that number.

The remedy the specification gives is the one the customer-creation path already
takes: enter the open invoices. So the two agree, and neither invents a
receivable from nothing.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User

from categoryio.models import Category

from companyio.choices import CompanyKindChoices
from companyio.models import Company, CompanyUser

from rest_framework.exceptions import ValidationError


class OpeningBalanceOnControlAccountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="A", email="ob@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def account_type(self, title):
        return Category.objects.filter(
            title=title, kind="CHART_OF_ACCOUNT", parent__isnull=False
        ).first()

    def detail_type(self, parent, title=None):
        queryset = Category.objects.filter(parent=parent)
        return (queryset.filter(title=title).first() if title else queryset.first())

    def create(self, account_type_title, opening_balance):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as S,
        )

        account_type = self.account_type(account_type_title)
        self.assertIsNotNone(account_type, f"taxonomy missing {account_type_title!r}")
        detail = self.detail_type(account_type)
        self.assertIsNotNone(detail, f"no detail type under {account_type_title!r}")

        return S(
            data={
                "title": f"Probe {account_type_title} {opening_balance}",
                "code": "1199",
                "account_type_slug": account_type.slug,
                "detail_type_slug": detail.slug,
                "opening_balance": str(opening_balance),
            },
            context={"request": type("R", (), {"user": self.user})()},
        )

    # ------------------------------------------------------------- refusals

    def test_a_receivable_opening_balance_is_refused(self):
        serializer = self.create("Accounts Receivable (A/R)", Decimal("2400"))

        with self.assertRaises(ValidationError) as caught:
            serializer.is_valid(raise_exception=True)

        self.assertIn("opening_balance", caught.exception.detail)
        self.assertIn("open invoices", str(caught.exception).lower())

    def test_a_payable_opening_balance_is_refused(self):
        serializer = self.create("Accounts Payable (A/P)", Decimal("900"))

        with self.assertRaises(ValidationError) as caught:
            serializer.is_valid(raise_exception=True)

        self.assertIn("opening_balance", caught.exception.detail)

    def test_the_income_and_expense_refusals_still_work(self):
        """The guard this extends, not replaces."""
        for account_type in ("Income", "Expense"):
            with self.subTest(account_type=account_type):
                serializer = self.create(account_type, Decimal("100"))
                with self.assertRaises(ValidationError):
                    serializer.is_valid(raise_exception=True)

    # ------------------------------------------------------------- allowed

    def test_zero_is_allowed_on_a_receivable(self):
        """The refusal is about a figure, not about the account type."""
        serializer = self.create("Accounts Receivable (A/R)", Decimal("0"))

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_an_ordinary_asset_may_still_take_one(self):
        """Only the two control accounts are refused."""
        serializer = self.create("Bank", Decimal("5000"))

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_a_similarly_named_type_is_not_caught(self):
        """`Trust Accounts - Liabilities` contains 'ccounts' and must pass."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            _is_receivable_or_payable,
        )

        trust = self.account_type("Other Current Liabilities")
        self.assertIsNotNone(trust)
        self.assertFalse(_is_receivable_or_payable(trust))

    def test_every_receivable_and_payable_spelling_is_caught(self):
        """The taxonomy carries four, and the type could be any of them."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            _is_receivable_or_payable,
        )

        for title in (
            "Accounts Receivable (A/R)",
            "Accounts Payable (A/P)",
            "Accounts Receivable",
            "Accounts Payable",
        ):
            with self.subTest(title=title):
                self.assertTrue(
                    _is_receivable_or_payable(type("C", (), {"title": title})())
                )

    def test_it_tolerates_a_missing_title(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            _is_receivable_or_payable,
        )

        self.assertFalse(_is_receivable_or_payable(None))
        self.assertFalse(_is_receivable_or_payable(type("C", (), {"title": None})()))
