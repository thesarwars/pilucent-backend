"""Deleting a supplier payment left it on the books, the bill paid, the credit used.

`perform_destroy` set the document's status to REMOVED and did nothing else.
`get_status_all()` excludes REMOVED so the payment vanished from its list, while
`JournalEntry.status` was never touched -- so both legs stayed PUBLISHED and the
payment stayed in the bank register, in its running balance, and in the set
`/reconcile/complete` offers to tick.

The twin of `salesio/tests_payment_delete.py`, plus the two things that make a
supplier payment different: a line can point at a **Purchase or a CreditNote**,
and a **credit-note-only payment posts an entry with no legs at all** -- the
ledger half of that branch is commented out while the entry is created
unconditionally.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from creditnoteio.choices import CreditNoteStatusChoices
from creditnoteio.models import CreditNote

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from purchaseio.choices import (
    PurchasePaymentItemModelKindChoices,
    PurchasePaymentStatusChoices,
    PurchaseStatus,
)
from purchaseio.models import Purchase, PurchasePayment, PurchasePaymentItem

from supplierio.models import Supplier

from weapi.django_rest.helpers.purchase_payment_posting import (
    unapply_purchase_payment_items,
    void_purchase_payment_postings,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class PaymentDeleteTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="P", email="purchpay@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Acme", display_name="Acme Ltd",
            opening_balance=Decimal("0"),
        )
        self.bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "500")
        self.payable = self.account(
            "Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES, "0"
        )
        # A bill for 300, fully settled.
        self.bill = Purchase.objects.create(
            company=self.company, supplier=self.supplier,
            status=PurchaseStatus.COMPLETED,
            total=Decimal("300"), due_total=Decimal("0"), deposit=Decimal("300"),
        )
        self.payment = PurchasePayment.objects.create(
            company=self.company, supplier=self.supplier,
            status=PurchasePaymentStatusChoices.COMPLETED,
            total=Decimal("300"), payment_account=self.bank,
        )
        PurchasePaymentItem.objects.create(
            purchase_payment=self.payment,
            model_kind=PurchasePaymentItemModelKindChoices.PURCHASE,
            purchase=self.bill, total=Decimal("300"), used_total=Decimal("300"),
        )
        self.entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.PURCHASE_PAYMENT,
            status=JournalEntryStatusChoices.PUBLISHED,
            amount=Decimal("300"), purchase_payment=self.payment,
        )
        # A/P debited (the bill is settled), bank credited (money left).
        self.payable_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.payable, date="2026-03-01",
            debit=Decimal("300"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        self.bank_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.bank, date="2026-03-01",
            debit=Decimal("0"), credit=Decimal("300"),
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        # Balances as the posting would have left them: A/P paid down, bank out.
        self.payable.opening_balance = Decimal("-300")
        self.payable.save()
        self.bank.opening_balance = Decimal("200")
        self.bank.save()
        self.supplier.opening_balance = Decimal("-300")
        self.supplier.save()

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def delete(self):
        from weapi.django_rest.views.purchases import PrivateWePurchasePaymentDetails

        view = PrivateWePurchasePaymentDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.payment)

    def balances(self):
        self.bank.refresh_from_db()
        self.payable.refresh_from_db()
        self.supplier.refresh_from_db()
        return (
            self.bank.opening_balance,
            self.payable.opening_balance,
            self.supplier.opening_balance,
        )


class TheOldDeleteLeftEverythingBehindTests(PaymentDeleteTestCase):
    def test_the_legs_stayed_published(self):
        self.payment.status = PurchasePaymentStatusChoices.REMOVED
        self.payment.save()

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntryStatusChoices.PUBLISHED)

    def test_and_the_bill_stayed_settled(self):
        self.payment.status = PurchasePaymentStatusChoices.REMOVED
        self.payment.save()

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.due_total, Decimal("0.000"))
        self.assertEqual(self.bill.status, PurchaseStatus.COMPLETED)


class DeletingNowReversesTests(PaymentDeleteTestCase):
    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.filter(
            purchase_payment=self.payment
        ).exclude(pk=self.entry.pk).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_every_account_nets_to_zero(self):
        self.delete()

        for account in (self.bank, self.payable):
            with self.subTest(account=account.title):
                legs = JournalEntryConnector.objects.filter(account=account)
                self.assertEqual(
                    sum(l.debit for l in legs), sum(l.credit for l in legs)
                )

    def test_the_stored_balances_move_back(self):
        self.delete()
        self.assertEqual(
            self.balances(),
            (Decimal("500.000"), Decimal("0.000"), Decimal("0.000")),
        )

    def test_the_bill_owes_again(self):
        self.delete()

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.due_total, Decimal("300.000"))
        self.assertEqual(self.bill.deposit, Decimal("0.000"))
        self.assertEqual(self.bill.status, PurchaseStatus.OPEN)

    def test_the_payment_is_retired(self):
        self.delete()
        self.payment.refresh_from_db()
        self.assertEqual(
            self.payment.status, PurchasePaymentStatusChoices.REMOVED
        )

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = self.balances()
        self.delete()
        self.assertEqual(self.balances(), after)


class SupplierBalanceTests(PaymentDeleteTestCase):
    """Paying subtracts from what the vendor is owed; undoing adds it back."""

    def test_the_supplier_is_credited_back(self):
        self.delete()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.opening_balance, Decimal("0.000"))

    def test_no_ap_leg_means_no_supplier_move(self):
        """The posting gates the supplier on A/P existing, so the reversal must
        gate it the same way -- otherwise a payment posted without an A/P
        account credits a supplier who was never debited."""
        JournalEntryConnector.objects.filter(pk=self.payable_leg.pk).delete()
        self.supplier.opening_balance = Decimal("0")
        self.supplier.save()

        _, amount = void_purchase_payment_postings(self.payment)

        self.assertEqual(amount, Decimal("0.000"))


class CreditNoteLinesTests(PaymentDeleteTestCase):
    """A payment line can settle a bill or consume a credit note."""

    def setUp(self):
        super().setUp()
        self.note = CreditNote.objects.create(
            company=self.company, supplier=self.supplier,
            status=CreditNoteStatusChoices.CLOSE, total=Decimal("0"),
        )
        PurchasePaymentItem.objects.create(
            purchase_payment=self.payment,
            model_kind=PurchasePaymentItemModelKindChoices.CREDIT_NOTE,
            credit_note=self.note, total=Decimal("50"), used_total=Decimal("50"),
        )

    def test_the_credit_note_gets_its_remaining_credit_back(self):
        restored = unapply_purchase_payment_items(self.payment)

        self.note.refresh_from_db()
        self.assertEqual(self.note.total, Decimal("50.000"))
        self.assertEqual(restored["credit_notes_restored"], Decimal("50.000"))

    def test_a_reopened_note_is_open_again(self):
        unapply_purchase_payment_items(self.payment)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, CreditNoteStatusChoices.OPEN)

    def test_a_removed_note_is_not_resurrected(self):
        """Undoing a payment does not undelete a note somebody removed."""
        CreditNote.objects.filter(pk=self.note.pk).update(
            status=CreditNoteStatusChoices.REMOVED
        )

        unapply_purchase_payment_items(self.payment)

        self.note.refresh_from_db()
        self.assertEqual(self.note.status, CreditNoteStatusChoices.REMOVED)
        self.assertEqual(self.note.total, Decimal("50.000"))

    def test_a_credit_note_only_payment_posts_no_reversal(self):
        """That branch's ledger half is commented out, so its entry has no
        legs. Reversing nothing would add a second empty entry."""
        JournalEntryConnector.objects.filter(journal=self.entry).delete()

        reversal, amount = void_purchase_payment_postings(self.payment)

        self.assertIsNone(reversal)
        self.assertEqual(amount, Decimal("0.000"))
        self.assertEqual(
            JournalEntry.objects.filter(purchase_payment=self.payment).count(), 1
        )


class AggregationTests(PaymentDeleteTestCase):
    """Two lines against one bill restore the whole amount, not the last."""

    def test_two_lines_on_one_bill_are_summed_before_unapplying(self):
        """`unapply_purchase_payment` caps each call at the remaining deposit,
        so two half-sized calls would restore less than one full-sized one."""
        PurchasePaymentItem.objects.filter(
            purchase_payment=self.payment
        ).update(used_total=Decimal("150"))
        PurchasePaymentItem.objects.create(
            purchase_payment=self.payment,
            model_kind=PurchasePaymentItemModelKindChoices.PURCHASE,
            purchase=self.bill, total=Decimal("150"), used_total=Decimal("150"),
        )

        restored = unapply_purchase_payment_items(self.payment)

        self.bill.refresh_from_db()
        self.assertEqual(restored["bills_restored"], Decimal("300.000"))
        self.assertEqual(self.bill.due_total, Decimal("300.000"))

    def test_a_retired_payment_line_is_still_unapplied(self):
        """Deleting a line retires it without unapplying, so the bill is still
        carrying its effect and this is the last chance to give it back."""
        from purchaseio.choices import PurchasePaymentItemStatusChoices

        PurchasePaymentItem.objects.filter(
            purchase_payment=self.payment
        ).update(status=PurchasePaymentItemStatusChoices.REMOVED)

        restored = unapply_purchase_payment_items(self.payment)

        self.assertEqual(restored["bills_restored"], Decimal("300.000"))


class ReconciledPaymentsAreRefusedTests(PaymentDeleteTestCase):
    def test_a_closed_reconciliation_blocks_the_delete(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"),
            beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=self.bank_leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        before = self.balances()

        with self.assertRaises(ReconciledLineLocked):
            self.delete()

        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.bill.due_total, Decimal("0.000"))
        self.assertNotEqual(
            self.payment.status, PurchasePaymentStatusChoices.REMOVED
        )
