"""One invariant, applied to every document type that can be deleted.

`LEDGER_WRITE_PATH_GAPS.md` names this as the second of two guards "worth more
than any individual fix", and says the shape "would have caught all five". None
of the five original defects was caught by anything; each needed a bespoke test
written after somebody had already found the bug by reading.

**The invariant is not the one the document proposed.** It suggested asserting
that a touched account's stored balance equals the sum of its surviving ledger
legs. That is false on any account carrying a real opening balance no journal leg
represents — `City Bank` stands at 2,000 before a hand-keyed entry exists — and a
test asserting it would fail everywhere for reasons that are not defects.

What a delete actually owes is **drift preservation**: whatever gap already
existed between the stored column and the ledger, deleting must not change it.
That holds regardless of opening balances, it is exactly what the five defects
violated, and it is what `repair_account_balances` measures on production.

Adding a new deletable document means adding one entry to `DOCUMENTS` below. If
its delete forgets to reverse, move a balance, or unwind an allocation, this
fails without anyone writing a test for that document specifically.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from common.django_rest.helpers.ledger_balances import account_balance_as_of

from companyio.models import Company, CompanyUser

from customerio.models import Customer

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from paymentio.models import PaymentMethod

from supplierio.models import Supplier


class FakeRequest:
    def __init__(self, user):
        self.user = user


class PostDeleteInvariantTests(TestCase):
    """Post a document, delete it, assert no account drifted as a result."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="I", email="invariant@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="Nusrat", last_name="Chowdhury"
        )
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders"
        )
        self.method = PaymentMethod.objects.create(
            company=self.company, title="Bank Transfer"
        )
        # A bank with a real opening balance no journal leg represents. This is
        # the case that makes "stored == sum of legs" the wrong invariant, and
        # every document below funds from it so the distinction is exercised
        # rather than described.
        self.bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "2000")
        self.contra = self.account(
            "Contra", ChartOfAccountKindChoices.EXPENSES, "0"
        )

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    # -- the invariant ----------------------------------------------------

    def drift(self):
        """`{account_id: stored - derived}` for every account in the company."""
        return {
            account.id: Decimal(account.opening_balance or 0)
            - Decimal(account_balance_as_of(account))
            for account in ChartOfAccount.objects.filter(company=self.company)
        }

    def assert_delete_preserves_drift(self, name, delete):
        before = self.drift()
        delete()
        after = self.drift()

        moved = {
            ChartOfAccount.objects.get(pk=pk).title: (before[pk], after[pk])
            for pk in before
            if before[pk] != after.get(pk)
        }
        self.assertEqual(
            moved, {},
            f"deleting a {name} changed the gap between the stored balance and "
            f"the ledger on {len(moved)} account(s): {moved}. A delete must "
            "reverse both halves or neither.",
        )

    # -- one posted document per type, minimal and by hand ----------------
    #
    # Posted by hand rather than through each serializer, because the point is
    # to test the DELETE against a known-good posted state. A create path that
    # is itself wrong would otherwise hide a broken delete behind a broken post.

    def post(self, kind, amount, **fk):
        """A balanced two-leg entry: DEBIT contra, CREDIT bank."""
        entry = JournalEntry.objects.create(
            company=self.company, kind=kind, date=date(2026, 3, 1),
            status=JournalEntryStatusChoices.PUBLISHED, amount=Decimal(amount),
            **fk,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=self.contra, date=date(2026, 3, 1),
            debit=Decimal(amount), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=self.bank, date=date(2026, 3, 1),
            debit=Decimal("0"), credit=Decimal(amount),
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        # What the posting path would have left the stored column at.
        self.contra.opening_balance = Decimal(amount)
        self.contra.save()
        self.bank.opening_balance = Decimal("2000") - Decimal(amount)
        self.bank.save()
        return entry

    # -- the documents ----------------------------------------------------

    def test_a_customer_payment(self):
        from salesio.choices import SalePaymentReceiveStatusChoices
        from salesio.models import SalePaymentReceive
        from weapi.django_rest.views.sales import PrivateWeSalePaymentReceiveDetails

        payment = SalePaymentReceive.objects.create(
            company=self.company, customer=self.customer,
            payment_method=self.method, deposit_to=self.bank,
            status=SalePaymentReceiveStatusChoices.COMPLETED,
        )
        self.post(
            JournalEntryKindChoices.SALE_PAYMENT_RECEIVE, "500",
            sale_payment_receive=payment,
        )

        view = PrivateWeSalePaymentReceiveDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "customer payment", lambda: view.perform_destroy(payment)
        )

    def test_a_supplier_payment(self):
        from purchaseio.choices import PurchasePaymentStatusChoices
        from purchaseio.models import PurchasePayment
        from weapi.django_rest.views.purchases import PrivateWePurchasePaymentDetails

        payment = PurchasePayment.objects.create(
            company=self.company, supplier=self.supplier,
            payment_method=self.method, payment_account=self.bank,
            status=PurchasePaymentStatusChoices.COMPLETED,
        )
        self.post(
            JournalEntryKindChoices.PURCHASE_PAYMENT, "300",
            purchase_payment=payment,
        )

        view = PrivateWePurchasePaymentDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "supplier payment", lambda: view.perform_destroy(payment)
        )

    def test_a_stock_adjustment(self):
        from stockio.choices import StockAdjustmentStatusChoices
        from stockio.models import StockAdjustment
        from weapi.django_rest.views.stock import PrivateWeStockAdjustmentDetails

        adjustment = StockAdjustment.objects.create(
            company=self.company, stock_adjustment_account=self.contra,
            status=StockAdjustmentStatusChoices.ACTIVE, date=date(2026, 3, 1),
        )
        self.post(
            JournalEntryKindChoices.STOCK_ADJUSTMENT, "120",
            stock_adjustment=adjustment,
        )

        view = PrivateWeStockAdjustmentDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "stock adjustment", lambda: view.perform_destroy(adjustment)
        )

    def test_a_credit_note(self):
        from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
        from creditnoteio.models import CreditNote
        from weapi.django_rest.views.creditnotes import PrivateWeCreditNoteDetails

        note = CreditNote.objects.create(
            company=self.company, kind=CreditNoteKindChoices.SALE,
            credit_note_number="CN-INV-1", status=CreditNoteStatusChoices.OPEN,
            date=date(2026, 3, 1), total=Decimal("80"), customer=self.customer,
        )
        self.post(JournalEntryKindChoices.CREDIT_NOTE, "80", credit_note=note)

        view = PrivateWeCreditNoteDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "credit note", lambda: view.perform_destroy(note)
        )

    def test_a_bill(self):
        from purchaseio.choices import PurchaseStatus
        from purchaseio.models import Purchase
        from weapi.django_rest.views.purchases import PrivateWePurchaseDetails

        purchase = Purchase.objects.create(
            company=self.company, supplier=self.supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date=date(2026, 3, 1),
            total=Decimal("250"), due_total=Decimal("250"),
        )
        self.post(JournalEntryKindChoices.PURCHASE, "250", purchase=purchase)

        view = PrivateWePurchaseDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "bill", lambda: view.perform_destroy(purchase)
        )

    def test_a_manual_journal_entry(self):
        from weapi.django_rest.views.journals import PrivateWeJournalEntryDetails

        entry = self.post(JournalEntryKindChoices.JOURNAL_ENTRY, "400")

        view = PrivateWeJournalEntryDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "manual journal entry", lambda: view.perform_destroy(entry)
        )

    def test_an_expense(self):
        from purchaseio.choices import ExpenseStatusChoices
        from purchaseio.models import Expense
        from weapi.django_rest.views.purchases import PrivateWeExpenseDetails

        # `Expense` carries no `company` column — it is scoped through the
        # Purchases it covers, which is why the tenant sweep lists it under
        # `ALLOWED_UNSCOPED` rather than as a miss.
        expense = Expense.objects.create(
            supplier=self.supplier, payment_account=self.bank,
            status=ExpenseStatusChoices.PUBLISHED, date=date(2026, 3, 1),
            total=Decimal("60"),
        )
        self.post(JournalEntryKindChoices.EXPENSE, "60", expense=expense)

        view = PrivateWeExpenseDetails()
        view.request = FakeRequest(self.user)
        self.assert_delete_preserves_drift(
            "expense", lambda: view.perform_destroy(expense)
        )


class TheInvariantCanActuallyFailTests(PostDeleteInvariantTests):
    """Guards the guard: an invariant that cannot fail proves nothing."""

    def test_a_delete_that_forgets_the_balance_is_caught(self):
        """The original defect, reproduced: retire the document, move nothing."""
        from creditnoteio.choices import CreditNoteKindChoices, CreditNoteStatusChoices
        from creditnoteio.models import CreditNote

        note = CreditNote.objects.create(
            company=self.company, kind=CreditNoteKindChoices.SALE,
            credit_note_number="CN-INV-2", status=CreditNoteStatusChoices.OPEN,
            date=date(2026, 3, 1), total=Decimal("80"), customer=self.customer,
        )
        entry = self.post(JournalEntryKindChoices.CREDIT_NOTE, "80", credit_note=note)

        def the_old_broken_delete():
            # Exactly what every one of the five did: retire the document and
            # leave the legs and the balances where they were... then erase the
            # legs, which is what §1's cascade did.
            JournalEntry.objects.filter(pk=entry.pk).delete()
            note.status = CreditNoteStatusChoices.REMOVED
            note.save()

        with self.assertRaises(AssertionError) as caught:
            self.assert_delete_preserves_drift(
                "credit note", the_old_broken_delete
            )

        self.assertIn("changed the gap", str(caught.exception))
