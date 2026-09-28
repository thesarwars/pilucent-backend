"""A PATCH that omits a product's account fields must not null them.

`PrivateWeProductDetailsSerializer.update` assigned two of the three
unconditionally:

    validated_data["asset_account"]  = validated_data.pop("asset_account_uid", None)
    validated_data["income_account"] = validated_data.pop("income_account_uid", None)
    if "cogs_account_uid" in validated_data:                    # guarded
        validated_data["cogs_account"] = validated_data.pop("cogs_account_uid")

so a PATCH changing only the title wrote None over `asset_account` and
`income_account`. `cogs_account` -- added later, in 7cc3134c -- was guarded from
the start, which is what makes the other two visible as an oversight rather than
a decision.

What it costs: a product with no income account posts a receivable with no
revenue credit, and one with no asset account relieves no inventory. Both leave
the sale's journal entry short.

Same shape as 557b565f (the money fields on a bill) and the warehouse and
charter-account fields on the sale serializer.
"""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from adminio.models import CompanyRole

from companyio.models import Company, CompanyUser

from productio.models import Product

from weapi.django_rest.serializers.products import (
    PrivateWeProductDetailsSerializer,
)


class ProductPatchAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="Tester", email="product-patch@example.com", password="pass1234!"
        )
        membership = CompanyUser.objects.create(user=cls.user, company=cls.company)
        membership.roles.add(
            CompanyRole.objects.create(
                company=cls.company, name="admin", is_system=True
            )
        )

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def setUp(self):
        super().setUp()
        self.asset = self.account("Inventory Asset", ChartOfAccountKindChoices.ASSETS)
        self.income = self.account(
            "Sales of Product Income", ChartOfAccountKindChoices.INCOMES
        )
        self.cogs = self.account(
            "Cost of Goods Sold (COGS)", ChartOfAccountKindChoices.EXPENSES
        )
        self.product = Product.objects.create(
            company=self.company, title="Widget", quantity=0,
            date=date(2026, 8, 8),
            asset_account=self.asset,
            income_account=self.income,
            cogs_account=self.cogs,
        )

    def patch(self, payload):
        request = APIRequestFactory().patch("/", payload, format="json")
        request.user = self.user
        serializer = PrivateWeProductDetailsSerializer(
            self.product, data=payload, partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_changing_only_the_title_keeps_every_account(self):
        """The defect: two of the three were nulled."""
        self.patch({"title": "Widget renamed"})

        self.product.refresh_from_db()
        self.assertEqual(self.product.asset_account, self.asset)
        self.assertEqual(self.product.income_account, self.income)
        self.assertEqual(self.product.cogs_account, self.cogs)

    def test_the_title_still_changes(self):
        self.patch({"title": "Widget renamed"})

        self.product.refresh_from_db()
        self.assertEqual(self.product.title, "Widget renamed")

    def test_an_account_sent_explicitly_is_still_applied(self):
        other = self.account("Other Income", ChartOfAccountKindChoices.INCOMES)

        self.patch({"income_account_uid": str(other.uid)})

        self.product.refresh_from_db()
        self.assertEqual(self.product.income_account, other)
        # And the ones not sent are untouched.
        self.assertEqual(self.product.asset_account, self.asset)
        self.assertEqual(self.product.cogs_account, self.cogs)
