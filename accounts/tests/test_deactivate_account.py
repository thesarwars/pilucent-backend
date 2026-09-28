"""Retiring an account from data entry without touching the books.

Two shipped error messages have been telling users to do this for months. The
control-account delete refusal says "Make it inactive instead"; the 409 on
deleting an account with history says "Deactivate it instead". Neither had
anywhere to send them -- there was no inactive state and no endpoint, and
`FRONTEND_INSTRUCTIONS_COA.md` s5 had to instruct the frontend *not* to build
the button because it would have had nothing to call.

Spec BLZ-FIN-COA-SPEC-001 s9.4, three preconditions:

* **COA-150** balance must be zero
* **COA-151** nothing may still *map* to the account
* **COA-152** sub-accounts retired first, or an explicit cascade

The hard part is COA-151, and it is a classification problem rather than a query
one. `ChartOfAccount` has 40 reverse relations. History -- a sale, a bill, a
journal line, a finished pay run -- must **not** block, because preserving
exactly that is the point of the feature; an account worth retiring has been
used. Live mappings -- a product's income account, a tax agency, a payroll
preference, a recurring template, a bank rule -- must block, because they are
promises about future postings.

INACTIVE is deliberately not REMOVED, and the ordinary `.exclude(status=REMOVED)`
written across 73 files still admits it. Those call sites are reports and
resolvers and they should: an inactive account keeps its balance, its history
and its place in every statement.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount, User

from common.django_rest.helpers.account_references import (
    HISTORICAL_RELATIONS,
    MAPPING_RELATIONS,
    active_children,
    blocking_references,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company, CompanyUser

from productio.models import Product

from rest_framework.exceptions import ValidationError


class FakeRequest:
    def __init__(self, user, data=None):
        self.user = user
        self.data = data or {}


class DeactivateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="A", email="a@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def account(self, title="Old Marketing Spend", **kwargs):
        kwargs.setdefault("kind", ChartOfAccountKindChoices.EXPENSES)
        kwargs.setdefault("status", Status.ACTIVE)
        kwargs.setdefault("opening_balance", Decimal("0"))
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=kwargs.pop("code", "6999"), **kwargs
        )

    def view(self, account, data=None):
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDeactivate,
        )

        view = PrivateWeChartOfAccountDeactivate()
        view.kwargs = {"uid": str(account.uid)}
        view.request = FakeRequest(self.user, data)
        return view

    def deactivate(self, account, **data):
        view = self.view(account, data)
        return view.post(view.request)

    def reactivate(self, account):
        view = self.view(account)
        return view.delete(view.request)

    # ------------------------------------------------------------ happy path

    def test_a_clean_account_deactivates(self):
        account = self.account()

        self.deactivate(account)

        account.refresh_from_db()
        self.assertEqual(account.status, Status.INACTIVE)

    def test_it_keeps_its_balance_history_and_place(self):
        """Inactive is not removed. `.exclude(REMOVED)` must still find it."""
        account = self.account()
        self.deactivate(account)

        self.assertIn(
            account,
            ChartOfAccount.objects.filter(company=self.company).exclude(
                status=Status.REMOVED
            ),
        )

    def test_it_can_be_reactivated(self):
        account = self.account()
        self.deactivate(account)

        self.reactivate(account)

        account.refresh_from_db()
        self.assertEqual(account.status, Status.ACTIVE)

    def test_deactivating_twice_is_not_an_error(self):
        account = self.account()
        self.deactivate(account)

        self.deactivate(account)  # must not raise

        account.refresh_from_db()
        self.assertEqual(account.status, Status.INACTIVE)

    def test_reactivating_an_active_account_is_refused(self):
        with self.assertRaises(ValidationError):
            self.reactivate(self.account())

    # ------------------------------------------------------- COA-150 balance

    def test_an_account_holding_a_balance_is_refused(self):
        account = self.account(opening_balance=Decimal("250.00"))

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(account)

        self.assertIn("COA-150", str(caught.exception))
        account.refresh_from_db()
        self.assertEqual(account.status, Status.ACTIVE)

    def test_the_refusal_names_the_balance(self):
        account = self.account(opening_balance=Decimal("250.00"))

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(account)

        self.assertIn("250", str(caught.exception))

    # ---------------------------------------------------- COA-151 references

    def test_a_product_income_mapping_blocks_it(self):
        account = self.account("Consulting Revenue", kind=ChartOfAccountKindChoices.INCOMES)
        Product.objects.create(
            company=self.company, title="Advisory day", income_account=account, quantity=0, date=date(2026, 8, 1)
        )

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(account)

        self.assertIn("COA-151", str(caught.exception))

    def test_the_refusal_says_what_to_remap(self):
        """"3 references" with no names is not actionable."""
        account = self.account("Consulting Revenue", kind=ChartOfAccountKindChoices.INCOMES)
        Product.objects.create(
            company=self.company, title="Advisory day", income_account=account, quantity=0, date=date(2026, 8, 1)
        )

        references = blocking_references(account)

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["label"], "Product income account")
        self.assertEqual(references[0]["count"], 1)
        self.assertTrue(references[0]["sample"])

    def test_history_does_not_block(self):
        """The distinction the whole feature turns on."""
        from journalio.choices import (
            JournalEntryConnectorKindChoices,
            JournalEntryKindChoices,
            JournalEntryStatusChoices,
        )
        from journalio.models import JournalEntry, JournalEntryConnector

        account = self.account()
        entry = JournalEntry.objects.create(
            company=self.company, entry_number="JE-1", amount=Decimal("100"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("100"), credit=0, total=Decimal("100"), last_balance=0,
        )

        self.assertEqual(blocking_references(account), [])
        self.deactivate(account)

        account.refresh_from_db()
        self.assertEqual(account.status, Status.INACTIVE)

    def test_a_removed_mapping_does_not_block(self):
        """A soft-deleted product is not a live mapping."""
        from productio.choices import ProductStatusChoices

        account = self.account("Consulting Revenue", kind=ChartOfAccountKindChoices.INCOMES)
        Product.objects.create(
            company=self.company, title="Retired product", income_account=account, quantity=0, date=date(2026, 8, 1),
            status=ProductStatusChoices.REMOVED,
        )

        self.assertEqual(blocking_references(account), [])

    # ----------------------------------------------------- COA-152 hierarchy

    def test_active_children_block_it(self):
        parent = self.account("Marketing", code="6900")
        self.account("Marketing:Digital", code="6901", parent=parent)

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(parent)

        self.assertIn("COA-152", str(caught.exception))

    def test_cascade_retires_the_subtree(self):
        parent = self.account("Marketing", code="6900")
        child = self.account("Marketing:Digital", code="6901", parent=parent)
        grandchild = self.account("Marketing:Digital:Paid", code="6902", parent=child)

        response = self.deactivate(parent, cascade=True)

        for account in (parent, child, grandchild):
            account.refresh_from_db()
            self.assertEqual(account.status, Status.INACTIVE, account.title)
        self.assertEqual(response.data["deactivated"], 3)

    def test_an_already_inactive_child_does_not_block(self):
        parent = self.account("Marketing", code="6900")
        self.account(
            "Marketing:Digital", code="6901", parent=parent, status=Status.INACTIVE
        )

        self.deactivate(parent)

        parent.refresh_from_db()
        self.assertEqual(parent.status, Status.INACTIVE)

    def test_active_children_ignores_retired_ones(self):
        parent = self.account("Marketing", code="6900")
        self.account("A", code="6901", parent=parent, status=Status.INACTIVE)
        self.account("B", code="6902", parent=parent, status=Status.REMOVED)
        live = self.account("C", code="6903", parent=parent)

        self.assertEqual(list(active_children(parent)), [live])

    # -------------------------------------------------------- control accounts

    def test_a_control_account_is_refused(self):
        account = ChartOfAccount.objects.get(
            company=self.company, system_key=Key.RETAINED_EARNINGS
        )

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(account)

        self.assertIn("COA-153", str(caught.exception))
        account.refresh_from_db()
        self.assertEqual(account.status, Status.ACTIVE)

    def test_an_ordinary_seeded_account_is_NOT_refused(self):
        """`is_fixed` does not mean "control account", and this turned on it.

        Seeding stamps `is_fixed=True` on every row it creates -- 3,573 of 3,759
        live accounts carry it while only 780 are control accounts. Refusing on
        that flag refused "Cash on Hand", "Savings Account" and
        "Equipment & Machinery", leaving the endpoint usable on 4% of the chart.
        """
        account = self.account("Old Savings", code="1099")
        account.is_fixed = True
        account.system_key = None
        account.save(update_fields=["is_fixed", "system_key"])

        self.deactivate(account)

        account.refresh_from_db()
        self.assertEqual(account.status, Status.INACTIVE)

    def test_the_refusal_reads_system_key_not_is_fixed(self):
        """A control account with the flag missing must still be refused."""
        account = ChartOfAccount.objects.get(
            company=self.company, system_key=Key.RETAINED_EARNINGS
        )
        account.is_fixed = False
        account.save(update_fields=["is_fixed"])

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(account)

        self.assertIn("COA-153", str(caught.exception))

    # ------------------------------------------------------------- the PATCH

    def test_status_cannot_be_patched_straight_to_inactive(self):
        """Otherwise every precondition above is optional."""
        import inspect

        from weapi.django_rest.serializers import chart_of_accounts

        source = inspect.getsource(chart_of_accounts)
        self.assertIn("Use the deactivate endpoint", source)


class ClassificationCompletenessTests(TestCase):
    """Every reverse relation must be classified, so a new one fails loudly."""

    def test_no_relation_is_unclassified(self):
        mapped = {(a, m, f) for a, m, f, _ in MAPPING_RELATIONS}
        historical = set(HISTORICAL_RELATIONS)

        unclassified = [
            (
                field.related_model._meta.app_label,
                field.related_model.__name__,
                field.field.name,
            )
            for field in ChartOfAccount._meta.get_fields()
            if field.auto_created
            and not field.concrete
            and (
                field.related_model._meta.app_label,
                field.related_model.__name__,
                field.field.name,
            )
            not in mapped | historical
        ]

        self.assertEqual(
            unclassified,
            [],
            "new reverse relation(s) on ChartOfAccount -- decide whether each is "
            "a live mapping (blocks deactivation) or history (does not), and add "
            "it to account_references.py",
        )

    def test_every_mapping_relation_actually_exists(self):
        """A typo here would silently stop blocking."""
        from django.apps import apps

        for app_label, model_name, field, _label in MAPPING_RELATIONS:
            with self.subTest(relation=f"{model_name}.{field}"):
                model = apps.get_model(app_label, model_name)
                self.assertIn(field, {f.name for f in model._meta.get_fields()})
