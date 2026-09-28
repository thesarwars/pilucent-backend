"""Deleting a credit note gave back neither the credit, the stock, nor the ledger.

`perform_destroy` set the document's status to REMOVED and did nothing else. The
note's A/R or A/P leg stayed PUBLISHED, so a credit that no longer existed went
on reducing what a customer owed or what was owed to a supplier; the goods it
moved stayed moved; and the customer or supplier balance kept the figure the
posting put there.

It cannot simply reuse `reverse_credit_note_postings`, which looks like the
answer but ends in `JournalEntry.delete()` -- erasing the original rather than
reversing it, which is the defect the expense delete was fixed for, and taking
the reconciliation markers on those legs with it.

Two refusals rather than a reversal, and each has a test class:

* **an applied credit** -- applying writes no journal leg at all, so there is
  nothing to flip; unwinding means rewriting a second posted document
* **consumed stock** -- a sale note's returned goods become spendable again, and
  once something has spent them there is no honest reversal
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from creditnoteio.choices import (
    CreditNoteItemStatusChoices,
    CreditNoteKindChoices,
    CreditNoteStatusChoices,
)
from creditnoteio.models import CreditNote, CreditNoteItem

from customerio.models import Customer

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

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
)
from salesio.models import SalePaymentReceive, SalePaymentReceiveItem

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import (
    ledger_layers,
    ledger_on_hand,
    record_stock_movement,
)
from stockio.models import StockMovement

from supplierio.models import Supplier

from weapi.django_rest.helpers.credit_note_void import (
    CreditNoteApplied,
    CreditNoteStockConsumed,
    applied_allocations,
    credited_layers,
    void_credit_note_postings,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class CreditNoteDeleteTestCase(TestCase):
    """A 500 sale credit note: 5 widgets back from the customer at 20 cost."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="C", email="cndel@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="Nusrat", last_name="Chowdhury",
            opening_balance=Decimal("1500"),
        )
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders",
            opening_balance=Decimal("0"),
        )
        self.receivable = self.account(
            "Accounts Receivable (A/R)", ChartOfAccountKindChoices.ASSETS, "2000"
        )
        self.income = self.account(
            "Sales of Product Income", ChartOfAccountKindChoices.INCOMES, "0"
        )
        self.widget = self.product("Widget")

        self.note = CreditNote.objects.create(
            company=self.company, kind=CreditNoteKindChoices.SALE,
            credit_note_number="CN-1", status=CreditNoteStatusChoices.OPEN,
            date=date(2026, 3, 1), total=Decimal("500"), customer=self.customer,
        )
        self.line = CreditNoteItem.objects.create(
            credit_note=self.note, product=self.widget, quantity=5,
            status=CreditNoteItemStatusChoices.ACTIVE,
        )

        # An earlier purchase lot of 20 at 20.000, 5 of which a sale consumed.
        self.lot = record_stock_movement(
            company=self.company, product=self.widget, date=date(2026, 1, 5),
            movement_type=StockMovementTypeChoices.PURCHASE,
            signed_quantity=20, rate=Decimal("20.000"),
        )
        self.sale_movement = record_stock_movement(
            company=self.company, product=self.widget, date=date(2026, 2, 1),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-5, rate=Decimal("100.000"),
            layer_slices=[(self.lot, Decimal("5"), Decimal("20.000"))],
        )
        # The note returns them: on hand rises, the lot is un-spent.
        self.widget.quantity = 20
        self.widget.save()
        self.returned = record_stock_movement(
            company=self.company, product=self.widget, date=self.note.date,
            movement_type=StockMovementTypeChoices.SALE_RETURN,
            signed_quantity=5, rate=Decimal("20.000"),
            layer_slices=[(self.lot, Decimal("-5"), Decimal("20.000"))],
            credit_note_item=self.line,
        )

        self.entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.CREDIT_NOTE,
            status=JournalEntryStatusChoices.PUBLISHED, date=self.note.date,
            amount=Decimal("500"), credit_note=self.note,
        )
        self.ar_leg = self.leg(
            self.receivable, credit="500",
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        self.income_leg = self.leg(
            self.income, debit="500", kind=JournalEntryConnectorKindChoices.DEBIT,
            item=self.line,
        )
        self.receivable.opening_balance = Decimal("1500")
        self.receivable.save()
        self.income.opening_balance = Decimal("-500")
        self.income.save()

    # -- fixtures ---------------------------------------------------------
    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def product(self, title):
        return Product.objects.create(
            company=self.company, title=title, sku=title.upper(), quantity=15,
            date=date(2026, 1, 1), kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, is_inventory=True, is_stock=True,
        )

    def leg(self, account, debit="0", credit="0", kind=None, item=None):
        return JournalEntryConnector.objects.create(
            journal=self.entry, account=account, date="2026-03-01",
            debit=Decimal(debit), credit=Decimal(credit), kind=kind,
            credit_note_item=item,
        )

    # -- helpers ----------------------------------------------------------
    def delete(self):
        from weapi.django_rest.views.creditnotes import PrivateWeCreditNoteDetails

        view = PrivateWeCreditNoteDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.note)

    def on_hand(self):
        self.widget.refresh_from_db()
        return self.widget.quantity

    def balances(self):
        self.receivable.refresh_from_db()
        self.income.refresh_from_db()
        self.customer.refresh_from_db()
        return (
            self.receivable.opening_balance,
            self.income.opening_balance,
            self.customer.opening_balance,
        )

    def spend_it(self, amount="200"):
        payment = SalePaymentReceive.objects.create(
            company=self.company, customer=self.customer,
            payment_method=PaymentMethod.objects.create(
                company=self.company, title="Bank Transfer"
            ),
            deposit_to=self.receivable,
            status=SalePaymentReceiveStatusChoices.COMPLETED,
        )
        SalePaymentReceiveItem.objects.create(
            sale_payment_receive=payment, credit_note=self.note,
            model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE,
            total=Decimal(amount), used_total=Decimal(amount),
        )
        return payment


class TheOldDeleteGaveNothingBackTests(CreditNoteDeleteTestCase):
    """What `status = REMOVED` alone did, shown rather than described."""

    def test_the_credit_stayed_on_the_customers_account(self):
        self.note.status = CreditNoteStatusChoices.REMOVED
        self.note.save()

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntryStatusChoices.PUBLISHED)
        self.assertEqual(self.balances()[0], Decimal("1500.000"))

    def test_and_the_returned_goods_stayed_on_the_shelf(self):
        self.note.status = CreditNoteStatusChoices.REMOVED
        self.note.save()

        self.assertEqual(self.on_hand(), 20)
        self.assertEqual(ledger_on_hand(self.widget), 20)


class DeletingNowReversesTests(CreditNoteDeleteTestCase):
    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.filter(credit_note=self.note).exclude(
            pk=self.entry.pk
        ).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_the_reversal_legs_keep_their_line_attribution(self):
        """Credit-note legs are line-attributed; the payment reversals are not."""
        self.delete()

        reversal = JournalEntry.objects.filter(credit_note=self.note).exclude(
            pk=self.entry.pk
        ).get()
        attributed = JournalEntryConnector.objects.filter(
            journal=reversal, credit_note_item=self.line
        )
        self.assertEqual(attributed.count(), 1)

    def test_the_receivable_nets_to_zero(self):
        self.delete()

        legs = JournalEntryConnector.objects.filter(account=self.receivable)
        self.assertEqual(sum(l.debit for l in legs), sum(l.credit for l in legs))

    def test_the_stored_balances_move_back(self):
        self.delete()
        self.assertEqual(
            self.balances(),
            (Decimal("2000.000"), Decimal("0.000"), Decimal("2000.000")),
        )

    def test_the_customer_owes_the_credit_again(self):
        """Taken from the A/R leg, not from `credit_note.total`."""
        self.delete()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.opening_balance, Decimal("2000.000"))

    def test_the_returned_goods_come_back_off_the_shelf(self):
        self.delete()
        self.assertEqual(self.on_hand(), 15)
        self.assertEqual(ledger_on_hand(self.widget), 15)

    def test_the_lot_is_spent_again_rather_than_left_looking_full(self):
        """Undo the units without undoing the attribution and FIFO resells them."""
        self.delete()

        layers = ledger_layers(self.widget)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0][1], Decimal("15"))

    def test_the_reversal_movement_names_its_line(self):
        self.delete()

        reversal = StockMovement.objects.get(
            movement_type=StockMovementTypeChoices.REVERSAL
        )
        self.assertEqual(reversal.credit_note_item_id, self.line.pk)
        self.assertEqual(reversal.signed_quantity, -5)

    def test_the_reversal_is_dated_to_the_note_not_to_today(self):
        self.delete()

        reversal = JournalEntry.objects.filter(credit_note=self.note).exclude(
            pk=self.entry.pk
        ).get()
        self.assertEqual(reversal.date, date(2026, 3, 1))

    def test_the_note_is_retired(self):
        self.delete()
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, CreditNoteStatusChoices.REMOVED)

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = (self.balances(), self.on_hand())
        self.delete()
        self.assertEqual((self.balances(), self.on_hand()), after)

    def test_a_note_that_posted_nothing_is_not_an_error(self):
        JournalEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertEqual(
            void_credit_note_postings(self.note), (None, Decimal("0.000"))
        )


class SpentCreditsAreRefusedTests(CreditNoteDeleteTestCase):
    """Applying writes no leg, so there is nothing to flip."""

    def test_a_live_payment_is_reported_as_an_allocation(self):
        payment = self.spend_it("200")

        applied = applied_allocations(self.note)
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0][1], str(payment.uid))
        self.assertEqual(applied[0][2], Decimal("200.000"))

    def test_the_delete_is_refused_and_names_the_payment(self):
        payment = self.spend_it("200")

        with self.assertRaises(CreditNoteApplied) as caught:
            self.delete()

        self.assertIn(str(payment.uid), str(caught.exception))

    def test_nothing_moved_when_it_refused(self):
        self.spend_it("200")
        before = self.balances()

        with self.assertRaises(CreditNoteApplied):
            self.delete()

        self.note.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.on_hand(), 20)
        self.assertNotEqual(self.note.status, CreditNoteStatusChoices.REMOVED)

    def test_deleting_the_payment_first_unblocks_it(self):
        """The refusal has to leave the user somewhere to go."""
        payment = self.spend_it("200")
        payment.status = SalePaymentReceiveStatusChoices.REMOVED
        payment.save()

        self.assertEqual(applied_allocations(self.note), [])
        self.delete()

        self.note.refresh_from_db()
        self.assertEqual(self.note.status, CreditNoteStatusChoices.REMOVED)


class ResoldStockIsRefusedTests(CreditNoteDeleteTestCase):
    """The returned goods went back out again; they cannot come off twice."""

    def test_the_layer_the_note_credited_is_identified(self):
        credited = credited_layers(self.note)
        self.assertEqual(len(credited), 1)
        self.assertEqual(credited[0][0].pk, self.lot.pk)
        self.assertEqual(credited[0][1], Decimal("5"))

    def resell_the_returned_units(self):
        record_stock_movement(
            company=self.company, product=self.widget, date=date(2026, 4, 1),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-18, rate=Decimal("100.000"),
            layer_slices=[(self.lot, Decimal("18"), Decimal("20.000"))],
        )
        self.widget.quantity = 2
        self.widget.save()

    def test_the_delete_is_refused_and_names_the_product(self):
        self.resell_the_returned_units()

        with self.assertRaises(CreditNoteStockConsumed) as caught:
            self.delete()

        self.assertIn("Widget", str(caught.exception))

    def test_nothing_moved_when_it_refused(self):
        self.resell_the_returned_units()
        before = self.balances()

        with self.assertRaises(CreditNoteStockConsumed):
            self.delete()

        self.note.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.on_hand(), 2)
        self.assertNotEqual(self.note.status, CreditNoteStatusChoices.REMOVED)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovementTypeChoices.REVERSAL
            ).exists()
        )

    def test_on_hand_short_of_the_return_is_refused_rather_than_a_500(self):
        """`Product.quantity` is a PositiveIntegerField; do not let it raise."""
        self.widget.quantity = 3
        self.widget.save()

        with self.assertRaises(CreditNoteStockConsumed):
            self.delete()

        self.assertEqual(self.on_hand(), 3)


class ReconciledNotesAreRefusedTests(CreditNoteDeleteTestCase):
    def close_a_session_over_the_ar_leg(self):
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.receivable,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"), beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=self.ar_leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        return session

    def test_the_delete_is_refused_and_names_the_session(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )

        session = self.close_a_session_over_the_ar_leg()

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.delete()

        self.assertIn(str(session.uid), str(caught.exception))

    def test_the_stock_is_untouched_when_it_refused(self):
        """The cheap guards run before the inventory pass, not after it."""
        self.close_a_session_over_the_ar_leg()

        with self.assertRaises(Exception):
            self.delete()

        self.assertEqual(self.on_hand(), 20)
