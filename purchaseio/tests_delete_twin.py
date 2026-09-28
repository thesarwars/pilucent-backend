"""Deleting a purchase line must unwind the direction the leg actually posted.

Making the posting kind-aware is only half a fix. `perform_destroy` used to
hard-code `update_opening_balance(account, DEBIT, ...)` -- always subtract --
which was the exact inverse of an always-add posting. Once a line coded to a
liability, equity or income account SUBTRACTS at post time, an unconditional
subtract on delete subtracts a second time.

So the unwind is now derived from the connector's stored `kind`, which also
means rows written before the posting fix unwind correctly.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.models import ChartOfAccount, User

from adminio.models import CompanyRole

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)

from companyio.models import Company, CompanyUser

from journalio.choices import JournalEntryConnectorKindChoices, JournalEntryKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.choices import PurchaseItemkind
from purchaseio.models import Purchase, PurchaseItem

from supplierio.models import Supplier

from weapi.django_rest.views.purchases import PrivateWePurchaseItemDetails


class DeleteTwinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="Tester", email="deltwin@example.com", password="pass1234!"
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

    BASELINE = Decimal("1000")

    def scenario(self, kind, connector_kind):
        """A posted expense line and the connector the posting left behind.

        The balance is moved with the same helpers the posting uses, so this is
        a genuine round trip: post, then delete, and land back on BASELINE.
        Asserting against a balance that was never moved would only prove the
        unwind runs, not that it unwinds by the right amount in the right
        direction.
        """
        account = ChartOfAccount.objects.create(
            company=self.company, title=f"Coded {kind}-{connector_kind}", kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        posted_action = action_for_side(kind, connector_kind)
        update_opening_balance(
            account, balance_operation_for_action(posted_action), Decimal("147"), 0
        )
        account.refresh_from_db()
        purchase = Purchase.objects.create(
            company=self.company, supplier=self.supplier, is_bill=True,
            total=Decimal("147"), due_total=Decimal("147"),
        )
        item = PurchaseItem.objects.create(
            purchase=purchase, kind=PurchaseItemkind.EXPENSE,
            charter_account=account, total=Decimal("147"),
        )
        entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.PURCHASE,
            purchase=purchase,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account, purchase_item=item,
            kind=connector_kind,
            debit=Decimal("147") if connector_kind == JournalEntryConnectorKindChoices.DEBIT else 0,
            credit=Decimal("147") if connector_kind == JournalEntryConnectorKindChoices.CREDIT else 0,
        )
        return account, item

    def destroy(self, item):
        view = PrivateWePurchaseItemDetails()
        request = APIRequestFactory().delete("/")
        request.user = self.user
        view.request = request
        view.perform_destroy(item)

    def test_a_debit_posted_leg_unwinds_to_zero(self):
        """A liability-coded line posts as a DEBIT, so deleting must add back."""
        account, item = self.scenario(
            ChartOfAccountKindChoices.LIABILITIES,
            JournalEntryConnectorKindChoices.DEBIT,
        )

        self.destroy(item)

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_a_credit_posted_legacy_row_also_unwinds_to_zero(self):
        """Rows written before the posting fix must still unwind correctly.

        A liability-coded line posted as a CREDIT under the old code. Deriving
        the undo from the stored kind is what lets those rows net out; an
        unconditional subtract would take the balance the wrong way instead of back to BASELINE.
        """
        account, item = self.scenario(
            ChartOfAccountKindChoices.LIABILITIES,
            JournalEntryConnectorKindChoices.CREDIT,
        )

        self.destroy(item)

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_expense_coded_line_is_unchanged(self):
        """The ordinary case must behave exactly as it always did."""
        account, item = self.scenario(
            ChartOfAccountKindChoices.EXPENSES,
            JournalEntryConnectorKindChoices.DEBIT,
        )

        self.destroy(item)

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), self.BASELINE)

    def test_every_kind_round_trips(self):
        for kind in ChartOfAccountKindChoices.values:
            for connector_kind in (
                JournalEntryConnectorKindChoices.DEBIT,
                JournalEntryConnectorKindChoices.CREDIT,
            ):
                with self.subTest(kind=kind, posted=connector_kind):
                    account, item = self.scenario(kind, connector_kind)

                    self.destroy(item)

                    account.refresh_from_db()
                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )
