"""Retiring a customer, without touching their books.

U2 of `CUSTOMER_FIX_PLAN.md`, and the follow-through on a commitment
`COA_FIX_PLAN_V3.md` P1.1 made: *"Build it once. CUSTOMER_FIX_PLAN.md U2 needs
the same concept for customers."*

The product spec lists "Mark Customer as Inactive" as a customer action and
expects the list to offer an "include inactive customers" toggle. Neither
existed, so delete was the only way to retire a customer -- which is what made
the ledger-voiding `perform_destroy` reachable at all, before `c213f2b7` reduced
it to a status change.

**Deliberately weaker than the chart-of-account version, in one way.** There is
no balance precondition. An account holding a balance is refused, because
retiring it carries that figure off the reports. A customer is the opposite --
`CUSTOMER_INDUSTRY_STANDARD.md` §4, and QuickBooks and Xero both: their invoices
stay valid, their balance stays in A/R, and the ageing report still shows them.
A customer who has stopped buying but still owes money is the ordinary reason to
reach for this, so refusing until they have paid would make it useless exactly
when it is wanted.

What does block is a **live mapping** -- something that would keep creating
documents for them. Of the fifteen reverse relations on `Customer`, four qualify:
three recurring-template fields and a bank rule. History never blocks; that is
the entire point.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.models import User

from common.django_rest.helpers.customer_references import (
    HISTORICAL_RELATIONS,
    MAPPING_RELATIONS,
    active_children,
    blocking_references,
)

from companyio.models import Company, CompanyUser

from customerio.choices import CustomerStatusChoices as Status
from customerio.models import Customer

from rest_framework.exceptions import ValidationError


class FakeRequest:
    def __init__(self, user, data=None):
        self.user = user
        self.data = data or {}


class DeactivateCustomerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="A", email="cust@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    _seq = 0

    def customer(self, name="Widgets Ltd", **kwargs):
        type(self)._seq += 1
        kwargs.setdefault("status", Status.ACTIVE)
        return Customer.objects.create(
            company=self.company, first_name=f"{name} {type(self)._seq}",
            display_name=f"{name} {type(self)._seq}", **kwargs
        )

    def view(self, customer, data=None):
        from weapi.django_rest.views.customers import PrivateWeCustomerDeactivate

        view = PrivateWeCustomerDeactivate()
        view.kwargs = {"uid": str(customer.uid)}
        view.request = FakeRequest(self.user, data)
        return view

    def deactivate(self, customer, **data):
        view = self.view(customer, data)
        return view.post(view.request)

    def reactivate(self, customer):
        view = self.view(customer)
        return view.delete(view.request)

    # ------------------------------------------------------------ happy path

    def test_a_customer_can_be_retired(self):
        customer = self.customer()

        self.deactivate(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, Status.INACTIVE)

    def test_they_can_be_brought_back(self):
        customer = self.customer()
        self.deactivate(customer)

        self.reactivate(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, Status.ACTIVE)

    def test_retiring_twice_is_not_an_error(self):
        customer = self.customer()
        self.deactivate(customer)

        self.deactivate(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, Status.INACTIVE)

    def test_reactivating_an_active_customer_is_refused(self):
        with self.assertRaises(ValidationError):
            self.reactivate(self.customer())

    # --------------------------------------------------- the balance question

    def test_a_customer_who_still_owes_money_can_be_retired(self):
        """The deliberate difference from the account version.

        Their balance stays in A/R and the ageing report still shows them --
        `CUSTOMER_INDUSTRY_STANDARD.md` §4. Refusing until they had paid would
        make this useless exactly when it is wanted.
        """
        customer = self.customer(opening_balance=Decimal("2400.00"))

        self.deactivate(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, Status.INACTIVE)
        self.assertEqual(
            Decimal(str(customer.opening_balance)),
            Decimal("2400.00"),
            "retiring a customer moved their balance",
        )

    def test_retiring_leaves_their_history_alone(self):
        """The failure `c213f2b7` fixed must not return by another route."""
        from journalio.choices import (
            JournalEntryConnectorKindChoices,
            JournalEntryKindChoices,
            JournalEntryStatusChoices,
        )
        from journalio.models import JournalEntry, JournalEntryConnector
        from accounts.choices import (
            ChartOfAccountKindChoices,
            ChartOfAccountStatusChoices,
        )
        from accounts.models import ChartOfAccount

        customer = self.customer()
        account = ChartOfAccount.objects.create(
            company=self.company, title="A/R probe", code="1100",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(
            company=self.company, entry_number="JE-C1", amount=Decimal("100"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, customer=customer,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("100"), credit=0, total=Decimal("100"), last_balance=0,
        )

        self.deactivate(customer)

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntryStatusChoices.PUBLISHED)

    # ---------------------------------------------------- CUST-151 references

    def test_a_recurring_template_blocks_it(self):
        from recurringio.models import RecurringTemplate

        customer = self.customer()
        RecurringTemplate.objects.create(company=self.company, customer=customer)

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(customer)

        self.assertIn("CUST-151", str(caught.exception))

    def test_the_refusal_says_what_to_repoint(self):
        from recurringio.models import RecurringTemplate

        customer = self.customer()
        RecurringTemplate.objects.create(company=self.company, customer=customer)

        references = blocking_references(customer)

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["label"], "Recurring template")
        self.assertTrue(references[0]["sample"])

    def test_history_does_not_block(self):
        """Any customer worth retiring has been invoiced."""
        from salesio.models import Sale
        from salesio.choices import SalesStatusChoices

        customer = self.customer()
        Sale.objects.create(
            company=self.company, customer=customer, invoice_id="INV-C1",
            total=Decimal("500"), due_total=Decimal("500"), is_invoice=True,
            status=SalesStatusChoices.OPEN,
        )

        self.assertEqual(blocking_references(customer), [])
        self.deactivate(customer)

        customer.refresh_from_db()
        self.assertEqual(customer.status, Status.INACTIVE)

    # ----------------------------------------------------- CUST-152 hierarchy

    def test_active_sub_customers_block_it(self):
        parent = self.customer("Parent Co")
        self.customer("Department A", parent=parent)

        with self.assertRaises(ValidationError) as caught:
            self.deactivate(parent)

        self.assertIn("CUST-152", str(caught.exception))

    def test_cascade_retires_the_subtree(self):
        parent = self.customer("Parent Co")
        child = self.customer("Department A", parent=parent)
        grandchild = self.customer("Team 1", parent=child)

        response = self.deactivate(parent, cascade=True)

        for customer in (parent, child, grandchild):
            customer.refresh_from_db()
            self.assertEqual(customer.status, Status.INACTIVE)
        self.assertEqual(response.data["deactivated"], 3)

    def test_an_already_retired_child_does_not_block(self):
        parent = self.customer("Parent Co")
        self.customer("Department A", parent=parent, status=Status.INACTIVE)

        self.deactivate(parent)

        parent.refresh_from_db()
        self.assertEqual(parent.status, Status.INACTIVE)


class SelectableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def test_selectable_withholds_only_the_retired(self):
        live = Customer.objects.create(
            company=self.company, first_name="Live", display_name="Live",
            status=Status.ACTIVE,
        )
        inactive = Customer.objects.create(
            company=self.company, first_name="Retired", display_name="Retired",
            status=Status.INACTIVE,
        )
        removed = Customer.objects.create(
            company=self.company, first_name="Gone", display_name="Gone",
            status=Status.REMOVED,
        )
        pending = Customer.objects.create(
            company=self.company, first_name="Pending", display_name="Pending",
            status=Status.PENDING,
        )

        selectable = Customer.objects.filter(company=self.company).selectable()

        self.assertIn(live, selectable)
        self.assertNotIn(inactive, selectable)
        self.assertNotIn(removed, selectable)
        self.assertIn(
            pending, selectable, "production holds 2 PENDING customers today"
        )

    def test_get_status_all_still_includes_inactive(self):
        """Reports and the ageing must keep seeing them."""
        inactive = Customer.objects.create(
            company=self.company, first_name="Retired", display_name="Retired",
            status=Status.INACTIVE,
        )

        self.assertIn(
            inactive,
            Customer.objects.filter(company=self.company).get_status_all(),
        )



class ClassificationCompletenessTests(TestCase):
    def test_every_reverse_relation_is_classified(self):
        mapped = {(a, m, f) for a, m, f, _ in MAPPING_RELATIONS}
        historical = set(HISTORICAL_RELATIONS)

        unclassified = [
            (
                field.related_model._meta.app_label,
                field.related_model.__name__,
                field.field.name,
            )
            for field in Customer._meta.get_fields()
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
            "new reverse relation(s) on Customer -- decide whether each routes "
            "FUTURE documents (blocks) or is history (does not)",
        )

    def test_every_mapping_relation_exists(self):
        from django.apps import apps

        for app_label, model_name, field, _label in MAPPING_RELATIONS:
            with self.subTest(relation=f"{model_name}.{field}"):
                model = apps.get_model(app_label, model_name)
                self.assertIn(field, {f.name for f in model._meta.get_fields()})


class PickerSweepTests(TestCase):
    def test_every_customer_picker_is_narrowed(self):
        import re
        from pathlib import Path

        pattern = re.compile(r"queryset=Customer\.objects\.")
        offenders = []
        for path in sorted(Path(".").rglob("*.py")):
            text = str(path)
            if any(k in text for k in ("migrations", "/benv/", "/tests", "test_")):
                continue
            source = path.read_text(errors="ignore")
            for match in pattern.finditer(source):
                snippet = source[match.start(): match.start() + 70]
                if ".selectable()" not in snippet:
                    offenders.append(
                        f"{path}:{source[: match.start()].count(chr(10)) + 1}"
                    )

        self.assertEqual(offenders, [], "\n".join(offenders))
