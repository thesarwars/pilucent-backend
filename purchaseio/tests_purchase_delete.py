"""Deleting a bill took back neither the goods nor the ledger.

`perform_destroy` set the document's status to REMOVED and did nothing else. The
A/P leg stayed PUBLISHED, so a bill that no longer existed went on saying money
was owed; the goods stayed received; the cost layer it created stayed spendable;
and the supplier's own balance kept the figure the posting put there.

The last of the five delete paths, and the one that says no most often. A bill
sits at the head of two chains later documents attach to -- payments (through
`PurchasePaymentItem` and `PayBillApplication`) and stock (a `PURCHASE` movement
IS a cost layer, and buying in order to sell is the ordinary case). Neither can
be unwound from here without rewriting a second posted document, so the honest
answer is usually to refuse and point at what to delete first.

The sign on the supplier balance is the trap this file pins hardest: raising a
bill ADDS to what the vendor is owed, so undoing it SUBTRACTS -- the opposite of
the payment helper of the same name, which is the obvious thing to copy.
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

from paymentio.models import PaymentMethod

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from purchaseio.choices import (
    PayBillItemStatusChoices,
    PayBillStatusChoices,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
    PurchaseStatus,
)
from purchaseio.models import (
    PayBill,
    PayBillApplication,
    PayBillItem,
    Purchase,
    PurchaseItem,
    PurchasePayment,
    PurchasePaymentItem,
)

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import (
    ledger_layers,
    ledger_on_hand,
    record_stock_movement,
)
from stockio.models import StockMovement

from supplierio.models import Supplier

from weapi.django_rest.helpers.purchase_void import (
    BillAlreadyPaid,
    BillStockConsumed,
    consumed_layers,
    live_payments,
    void_purchase_postings,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class PurchaseDeleteTestCase(TestCase):
    """A 200 bill: 10 widgets received at 20.000 each, unpaid."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="B", email="billdel@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders",
            opening_balance=Decimal("200"),
        )
        self.payable = self.account(
            "Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES, "200"
        )
        self.inventory = self.account(
            "Inventory Asset", ChartOfAccountKindChoices.ASSETS, "1200"
        )
        self.widget = self.product("Widget")

        self.purchase = Purchase.objects.create(
            company=self.company, supplier=self.supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date=date(2026, 3, 1),
            total=Decimal("200"), due_total=Decimal("200"), deposit=Decimal("0"),
        )
        self.item = PurchaseItem.objects.create(
            purchase=self.purchase, product=self.widget,
            status=PurchaseItemStatus.PUBLISHED, kind=PurchaseItemkind.PRODUCT,
            quantity=10, opening_quantity=10,
            purchase_price=Decimal("20"), total=Decimal("200"),
        )
        self.movement = record_stock_movement(
            company=self.company, product=self.widget, date=self.purchase.date,
            movement_type=StockMovementTypeChoices.PURCHASE,
            signed_quantity=10, rate=Decimal("20.000"),
            purchase_item=self.item,
        )

        self.entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.PURCHASE,
            status=JournalEntryStatusChoices.PUBLISHED, date=self.purchase.date,
            amount=Decimal("200"), purchase=self.purchase,
        )
        self.payable_leg = self.leg(
            self.payable, credit="200",
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        self.inventory_leg = self.leg(
            self.inventory, debit="200",
            kind=JournalEntryConnectorKindChoices.DEBIT, item=self.item,
        )

    # -- fixtures ---------------------------------------------------------
    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def product(self, title):
        return Product.objects.create(
            company=self.company, title=title, sku=title.upper(), quantity=10,
            date=date(2026, 1, 1), kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, is_inventory=True, is_stock=True,
        )

    def leg(self, account, debit="0", credit="0", kind=None, item=None):
        return JournalEntryConnector.objects.create(
            journal=self.entry, account=account, date="2026-03-01",
            debit=Decimal(debit), credit=Decimal(credit), kind=kind,
            purchase_item=item,
        )

    # -- helpers ----------------------------------------------------------
    def delete(self):
        from weapi.django_rest.views.purchases import PrivateWePurchaseDetails

        view = PrivateWePurchaseDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.purchase)

    def on_hand(self):
        self.widget.refresh_from_db()
        return self.widget.quantity

    def balances(self):
        self.payable.refresh_from_db()
        self.inventory.refresh_from_db()
        self.supplier.refresh_from_db()
        return (
            self.payable.opening_balance,
            self.inventory.opening_balance,
            self.supplier.opening_balance,
        )

    def pay_it_with_a_supplier_payment(self, amount="200"):
        payment = PurchasePayment.objects.create(
            company=self.company, supplier=self.supplier,
            payment_method=PaymentMethod.objects.create(
                company=self.company, title="Bank Transfer"
            ),
            payment_account=self.payable,
            status=PurchasePaymentStatusChoices.COMPLETED,
        )
        PurchasePaymentItem.objects.create(
            purchase_payment=payment, purchase=self.purchase,
            model_kind=PurchasePaymentItemModelKindChoices.PURCHASE,
            total=Decimal(amount), used_total=Decimal(amount),
        )
        return payment

    def pay_it_with_pay_bills(self, amount="200"):
        bill_run = PayBill.objects.create(
            company=self.company, payment_account=self.payable,
            status=PayBillStatusChoices.PUBLISHED, total=Decimal(amount),
        )
        item = PayBillItem.objects.create(
            pay_bill=bill_run, supplier=self.supplier,
            status=PayBillItemStatusChoices.PUBLISHED, total=Decimal(amount),
        )
        PayBillApplication.objects.create(
            company=self.company, pay_bill_item=item, purchase=self.purchase,
            amount=Decimal(amount),
        )
        return item


class TheOldDeleteTookNothingBackTests(PurchaseDeleteTestCase):
    """What `status = REMOVED` alone did, shown rather than described."""

    def test_the_bill_stayed_on_the_books_as_owed(self):
        self.purchase.status = PurchaseStatus.REMOVED
        self.purchase.save()

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntryStatusChoices.PUBLISHED)
        self.assertEqual(self.balances()[0], Decimal("200.000"))

    def test_and_the_goods_stayed_received(self):
        self.purchase.status = PurchaseStatus.REMOVED
        self.purchase.save()

        self.assertEqual(self.on_hand(), 10)
        self.assertEqual(ledger_on_hand(self.widget), 10)
        self.assertEqual(len(ledger_layers(self.widget)), 1)


class DeletingNowReversesTests(PurchaseDeleteTestCase):
    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.filter(purchase=self.purchase).exclude(
            pk=self.entry.pk
        ).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_the_reversal_legs_keep_their_line_attribution(self):
        self.delete()

        reversal = JournalEntry.objects.filter(purchase=self.purchase).exclude(
            pk=self.entry.pk
        ).get()
        self.assertEqual(
            JournalEntryConnector.objects.filter(
                journal=reversal, purchase_item=self.item
            ).count(),
            1,
        )

    def test_the_payable_nets_to_zero(self):
        self.delete()

        legs = JournalEntryConnector.objects.filter(account=self.payable)
        self.assertEqual(sum(l.debit for l in legs), sum(l.credit for l in legs))

    def test_the_stored_balances_move_back(self):
        self.delete()
        self.assertEqual(
            self.balances(),
            (Decimal("0.000"), Decimal("1000.000"), Decimal("0.000")),
        )

    def test_the_vendor_is_no_longer_owed(self):
        """Raising a bill ADDS to the vendor; undoing it SUBTRACTS.

        The payment helper of the same name goes the other way, for the
        opposite reason. Copying it would leave the vendor owed twice.
        """
        self.delete()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.opening_balance, Decimal("0.000"))

    def test_the_goods_come_back_off(self):
        self.delete()
        self.assertEqual(self.on_hand(), 0)
        self.assertEqual(ledger_on_hand(self.widget), 0)

    def test_the_layer_it_created_is_gone(self):
        self.delete()
        self.assertEqual(ledger_layers(self.widget), [])

    def test_the_line_stops_offering_stock_to_legacy_fifo(self):
        """`PurchaseItem.quantity` is what `fifo_product_deduction` walks."""
        self.delete()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
        self.assertEqual(self.item.opening_quantity, 0)

    def test_the_reversal_movement_names_its_line(self):
        self.delete()

        reversal = StockMovement.objects.get(
            movement_type=StockMovementTypeChoices.REVERSAL
        )
        self.assertEqual(reversal.purchase_item_id, self.item.pk)
        self.assertEqual(reversal.signed_quantity, -10)

    def test_the_reversal_is_dated_to_the_bill_not_to_today(self):
        self.delete()

        reversal = JournalEntry.objects.filter(purchase=self.purchase).exclude(
            pk=self.entry.pk
        ).get()
        self.assertEqual(reversal.date, date(2026, 3, 1))

    def test_the_bill_is_retired(self):
        self.delete()
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PurchaseStatus.REMOVED)

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = (self.balances(), self.on_hand())
        self.delete()
        self.assertEqual((self.balances(), self.on_hand()), after)

    def test_a_bill_that_posted_nothing_is_not_an_error(self):
        JournalEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertEqual(
            void_purchase_postings(self.purchase), (None, Decimal("0.000"))
        )


class PaidBillsAreRefusedTests(PurchaseDeleteTestCase):
    """A payment against a bill writes no leg, so there is nothing to flip."""

    def test_a_supplier_payment_is_reported(self):
        payment = self.pay_it_with_a_supplier_payment()

        settled = live_payments(self.purchase)
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0][1], str(payment.uid))

    def test_a_pay_bills_run_is_reported_too(self):
        item = self.pay_it_with_pay_bills()

        settled = live_payments(self.purchase)
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0][0], "pay bill")
        self.assertEqual(settled[0][1], str(item.uid))

    def test_the_delete_is_refused_and_names_the_payment(self):
        payment = self.pay_it_with_a_supplier_payment()

        with self.assertRaises(BillAlreadyPaid) as caught:
            self.delete()

        self.assertIn(str(payment.uid), str(caught.exception))

    def test_nothing_moved_when_it_refused(self):
        self.pay_it_with_a_supplier_payment()
        before = self.balances()

        with self.assertRaises(BillAlreadyPaid):
            self.delete()

        self.purchase.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.on_hand(), 10)
        self.assertNotEqual(self.purchase.status, PurchaseStatus.REMOVED)

    def test_deleting_the_payment_first_unblocks_it(self):
        """The refusal has to leave the user somewhere to go."""
        payment = self.pay_it_with_a_supplier_payment()
        payment.status = PurchasePaymentStatusChoices.REMOVED
        payment.save()

        self.assertEqual(live_payments(self.purchase), [])
        self.delete()

        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PurchaseStatus.REMOVED)

    def test_a_removed_pay_bill_line_does_not_block_either(self):
        item = self.pay_it_with_pay_bills()
        item.status = PayBillItemStatusChoices.REMOVED
        item.save()

        self.assertEqual(live_payments(self.purchase), [])


class SoldGoodsAreRefusedTests(PurchaseDeleteTestCase):
    """Buying in order to sell is the ordinary case, so this fires often."""

    def sell_six(self):
        record_stock_movement(
            company=self.company, product=self.widget, date=date(2026, 4, 1),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-6, rate=Decimal("50.000"),
            layer_slices=[(self.movement, Decimal("6"), Decimal("20.000"))],
        )
        self.widget.quantity = 4
        self.widget.save()

    def test_the_layer_is_reported_as_consumed(self):
        self.sell_six()

        consumed = consumed_layers(self.purchase)
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0][1], Decimal("6"))

    def test_the_delete_is_refused_and_names_the_product(self):
        self.sell_six()

        with self.assertRaises(BillStockConsumed) as caught:
            self.delete()

        self.assertIn("Widget", str(caught.exception))

    def test_nothing_moved_when_it_refused(self):
        self.sell_six()
        before = self.balances()

        with self.assertRaises(BillStockConsumed):
            self.delete()

        self.purchase.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.on_hand(), 4)
        self.assertNotEqual(self.purchase.status, PurchaseStatus.REMOVED)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovementTypeChoices.REVERSAL
            ).exists()
        )

    def test_on_hand_short_of_the_receipt_is_refused_rather_than_a_500(self):
        """`Product.quantity` is a PositiveIntegerField; do not let it raise."""
        self.widget.quantity = 3
        self.widget.save()

        with self.assertRaises(BillStockConsumed):
            self.delete()

        self.assertEqual(self.on_hand(), 3)


class ReconciledBillsAreRefusedTests(PurchaseDeleteTestCase):
    def close_a_session_over_the_payable_leg(self):
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.payable,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"), beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=self.payable_leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        return session

    def test_the_delete_is_refused_and_names_the_session(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )

        session = self.close_a_session_over_the_payable_leg()

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.delete()

        self.assertIn(str(session.uid), str(caught.exception))

    def test_the_stock_is_untouched_when_it_refused(self):
        self.close_a_session_over_the_payable_leg()

        with self.assertRaises(Exception):
            self.delete()

        self.assertEqual(self.on_hand(), 10)
