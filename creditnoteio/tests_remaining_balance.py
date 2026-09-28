"""A deleted payment went on consuming the credit note it had spent.

Deleting a payment retires the document but leaves its payment-item rows, and
both remaining-balance accessors counted those rows regardless. So a customer
receipt that had spent a credit note kept spending it after it was deleted --
the receipt was gone from every list and the credit never came back.

That mattered beyond the number on screen. There was no way to free a sale
credit note at all: the purchase side gets its credit back because
`unapply_purchase_payment_items` adds to the stored `total`, but the sale side
has no stored figure to add to, so nothing released it.

The two sides are not mirrors, and this file pins the difference:

* **SALE** never mutates `CreditNote.total`. Remaining is derived, so the
  release has to happen in the derivation.
* **PURCHASE** decrements `total` in place. The stored figure IS the remaining
  balance -- and `get_purchase_remaining_balance` subtracted the applications
  from it a second time, reporting 40 on a 100 credit with 30 applied.
  `ap_aging_detail` had been documenting that defect and routing around it.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNote

from customerio.models import Customer

from paymentio.models import PaymentMethod

from purchaseio.choices import (
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
)
from purchaseio.models import PurchasePayment, PurchasePaymentItem

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
)
from salesio.models import SalePaymentReceive, SalePaymentReceiveItem

from supplierio.models import Supplier


class RemainingBalanceTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.customer = Customer.objects.create(
            company=self.company, first_name="Nusrat", last_name="Chowdhury"
        )
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders"
        )
        self.method = PaymentMethod.objects.create(
            company=self.company, title="Bank Transfer"
        )
        self.bank = ChartOfAccount.objects.create(
            company=self.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )

    def note(self, kind, total, number):
        return CreditNote.objects.create(
            company=self.company, kind=kind, credit_note_number=number,
            status=CreditNoteStatusChoices.OPEN, date=date(2026, 3, 1),
            total=Decimal(total),
            customer=self.customer if kind == CreditNoteKindChoices.SALE else None,
            supplier=self.supplier if kind == CreditNoteKindChoices.PURCHASE else None,
        )

    def spend_on_a_receipt(self, note, amount):
        payment = SalePaymentReceive.objects.create(
            company=self.company, customer=self.customer,
            payment_method=self.method, deposit_to=self.bank,
            status=SalePaymentReceiveStatusChoices.COMPLETED,
        )
        SalePaymentReceiveItem.objects.create(
            sale_payment_receive=payment, credit_note=note,
            model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE,
            total=Decimal(amount), used_total=Decimal(amount),
        )
        return payment

    def spend_on_a_bill_payment(self, note, amount):
        payment = PurchasePayment.objects.create(
            company=self.company, supplier=self.supplier,
            payment_method=self.method, payment_account=self.bank,
            status=PurchasePaymentStatusChoices.COMPLETED,
        )
        PurchasePaymentItem.objects.create(
            purchase_payment=payment, credit_note=note,
            model_kind=PurchasePaymentItemModelKindChoices.CREDIT_NOTE,
            total=Decimal(amount), used_total=Decimal(amount),
        )
        # The apply flow decrements the stored total in place.
        note.total = Decimal(note.total) - Decimal(amount)
        note.save()
        return payment


class TheSaleSideDerivesRemainingTests(RemainingBalanceTestCase):
    def test_an_unspent_credit_is_whole(self):
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-1")
        self.assertEqual(note.get_sale_remaining_balance(), Decimal("100.000"))

    def test_spending_it_reduces_what_is_left(self):
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-2")
        self.spend_on_a_receipt(note, "30")
        self.assertEqual(note.get_sale_remaining_balance(), Decimal("70.000"))

    def test_the_face_value_is_not_touched(self):
        """The sale side derives; it must never mutate `total`."""
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-3")
        self.spend_on_a_receipt(note, "30")
        note.refresh_from_db()
        self.assertEqual(note.total, Decimal("100.000"))

    def test_deleting_the_receipt_gives_the_credit_back(self):
        """The whole point: there was no way to free a sale credit note."""
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-4")
        payment = self.spend_on_a_receipt(note, "30")

        payment.status = SalePaymentReceiveStatusChoices.REMOVED
        payment.save()

        self.assertEqual(note.get_sale_remaining_balance(), Decimal("100.000"))
        self.assertFalse(note.get_is_fully_used_sale())

    def test_only_the_deleted_receipt_is_released(self):
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-5")
        gone = self.spend_on_a_receipt(note, "30")
        self.spend_on_a_receipt(note, "25")

        gone.status = SalePaymentReceiveStatusChoices.REMOVED
        gone.save()

        self.assertEqual(note.get_sale_remaining_balance(), Decimal("75.000"))

    def test_a_fully_spent_credit_is_reported_as_used(self):
        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-S-6")
        self.spend_on_a_receipt(note, "100")
        self.assertTrue(note.get_is_fully_used_sale())


class ThePurchaseSideStoresRemainingTests(RemainingBalanceTestCase):
    def test_the_stored_total_is_what_is_left(self):
        note = self.note(CreditNoteKindChoices.PURCHASE, "100", "CN-P-1")
        self.spend_on_a_bill_payment(note, "30")

        note.refresh_from_db()
        self.assertEqual(note.total, Decimal("70.000"))
        self.assertEqual(note.get_purchase_remaining_balance(), Decimal("70.000"))

    def test_the_applications_are_not_subtracted_a_second_time(self):
        """This reported 40 on a 100 credit with 30 applied."""
        note = self.note(CreditNoteKindChoices.PURCHASE, "100", "CN-P-2")
        self.spend_on_a_bill_payment(note, "30")

        note.refresh_from_db()
        self.assertNotEqual(note.get_purchase_remaining_balance(), Decimal("40.000"))
        self.assertEqual(note.get_purchase_remaining_balance(), Decimal("70.000"))

    def test_it_agrees_with_what_the_ap_aging_report_reads(self):
        """The report read the stored total precisely to dodge this method."""
        from weapi.django_rest.helpers.reports.ap_aging_detail import credit_amounts

        note = self.note(CreditNoteKindChoices.PURCHASE, "100", "CN-P-3")
        self.spend_on_a_bill_payment(note, "30")
        note.refresh_from_db()

        _amount, open_balance = credit_amounts(note.total, Decimal("30"))
        self.assertEqual(-open_balance, note.get_purchase_remaining_balance())

    def test_giving_the_credit_back_is_not_taken_off_again(self):
        """`unapply_purchase_payment_items` restores the stored total."""
        note = self.note(CreditNoteKindChoices.PURCHASE, "100", "CN-P-4")
        payment = self.spend_on_a_bill_payment(note, "30")

        payment.status = PurchasePaymentStatusChoices.REMOVED
        payment.save()
        note.refresh_from_db()
        note.total = Decimal(note.total) + Decimal("30")
        note.save()

        self.assertEqual(note.get_purchase_remaining_balance(), Decimal("100.000"))


class TheAgingReportsDropDeletedPaymentsTests(RemainingBalanceTestCase):
    def test_ar_aging_stops_netting_a_deleted_receipt(self):
        from weapi.django_rest.helpers.reports.ar_aging_detail import _credit_rows

        note = self.note(CreditNoteKindChoices.SALE, "100", "CN-AR-1")
        payment = self.spend_on_a_receipt(note, "30")

        before = self.credit_row(_credit_rows(self.company, None, None), note)
        self.assertEqual(before["open_balance"], Decimal("-70.00"))

        payment.status = SalePaymentReceiveStatusChoices.REMOVED
        payment.save()

        after = self.credit_row(_credit_rows(self.company, None, None), note)
        self.assertEqual(after["open_balance"], Decimal("-100.00"))

    def test_ap_aging_does_not_inflate_amount_after_the_credit_is_given_back(self):
        """The regression the supplier-payment delete introduced.

        `Amount` is rebuilt as stored_total + applied_total. Deleting the
        payment adds the credit back to the stored total, so counting the
        removed payment's items too reported the original as 130, not 100.
        """
        from weapi.django_rest.helpers.reports.ap_aging_detail import _credit_rows

        note = self.note(CreditNoteKindChoices.PURCHASE, "100", "CN-AP-1")
        payment = self.spend_on_a_bill_payment(note, "30")

        payment.status = PurchasePaymentStatusChoices.REMOVED
        payment.save()
        note.refresh_from_db()
        note.total = Decimal(note.total) + Decimal("30")
        note.save()

        row = self.credit_row(_credit_rows(self.company, None, None), note)
        self.assertEqual(row["amount"], Decimal("-100.00"))
        self.assertEqual(row["open_balance"], Decimal("-100.00"))

    def credit_row(self, rows, note):
        for row in rows:
            if row.get("uid") == str(note.uid):
                return row
        self.fail(f"credit note {note.uid} not in the report")
