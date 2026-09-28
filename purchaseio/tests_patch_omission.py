"""A PATCH that omits a money field must not treat it as zero.

`PrivateWePurchaseDetailsSerializer.update` reads

    validated_data.get("due_total", 0)

and every balance guard below it is `if requested != current:`. All four money
fields are `DecimalField(default=0.00)` on the model, so DRF makes them
`required=False` -- which means a PATCH changing only the memo read them all as
0, fired every guard, and drove the supplier balance, Accounts Payable, Sales
Tax Payable and the deposit account to zero.

Two failure modes, depending on the tenant. Where the account exists the balance
is silently zeroed. Where it does not -- a company with no Sales Tax Payable, of
which production had several before the control-account backfill -- the guard
fires anyway and `update_opening_balance` raises
`AttributeError: 'NoneType' object has no attribute 'opening_balance'`, so a
memo-only PATCH is a 500. That is what this test hits against the old code.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from adminio.models import CompanyRole

from companyio.models import Company, CompanyUser

from purchaseio.models import Purchase

from supplierio.models import Supplier

from weapi.django_rest.serializers.purchases import (
    PrivateWePurchaseDetailsSerializer,
)


class PatchOmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="Tester", email="patch@example.com", password="pass1234!"
        )
        membership = CompanyUser.objects.create(user=cls.user, company=cls.company)
        membership.roles.add(
            CompanyRole.objects.create(
                company=cls.company, name="admin", is_system=True
            )
        )
        cls.supplier = Supplier.objects.create(
            company=cls.company, first_name="Widgets", display_name="Widgets Ltd"
        )

    def setUp(self):
        super().setUp()
        self.company.refresh_from_db()

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind, opening_balance=balance,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def bill(self):
        return Purchase.objects.create(
            company=self.company,
            supplier=self.supplier,
            is_bill=True,
            total=Decimal("1000"),
            total_tax=Decimal("100"),
            due_total=Decimal("1100"),
            deposit=Decimal("0"),
        )

    def patch(self, instance, payload):
        factory = APIRequestFactory()
        request = factory.patch("/", payload, format="json")
        request.user = self.user
        serializer = PrivateWePurchaseDetailsSerializer(
            instance, data=payload, partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_changing_only_the_memo_moves_no_balance(self):
        """The landmine: absent must mean unchanged, not zero."""
        payable = self.account(
            "Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES,
            Decimal("1100"),
        )
        supplier_before = self.supplier.opening_balance
        instance = self.bill()

        self.patch(instance, {"memo": "just a note"})

        payable.refresh_from_db()
        self.supplier.refresh_from_db()
        self.assertEqual(
            Decimal(str(payable.opening_balance)), Decimal("1100"),
            "A/P was driven to zero by a PATCH that never mentioned due_total",
        )
        self.assertEqual(
            Decimal(str(self.supplier.opening_balance)),
            Decimal(str(supplier_before)),
        )

    def test_the_money_fields_are_optional_which_is_why_this_bites(self):
        serializer = PrivateWePurchaseDetailsSerializer()
        for name in ("total", "total_tax", "due_total", "deposit"):
            field = serializer.fields.get(name)
            if field is not None:
                self.assertFalse(
                    field.required,
                    f"{name} is required -- if that changed, this guard can relax",
                )
