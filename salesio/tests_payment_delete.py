"""Deleting a customer payment left it on the books and the invoice paid.

`perform_destroy` set the document's status to REMOVED and did nothing else.
`get_status_all()` excludes REMOVED, so the payment vanished from its own list
and looked deleted, while `JournalEntry.status` was never touched -- so both
legs stayed PUBLISHED, and with them:

* the payment stayed in the bank register and its running balance
* the invoice it settled stayed PAID, owing nothing, with no payment behind it
* the payment stayed in the set `/reconcile/complete` offers to tick

The last is the sharp one. Tick it and you have reconciled a transaction that
does not exist; leave it and the difference never reaches zero. One delete makes
the account unreconcilable, and nothing on screen says why.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from customerio.models import Customer

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from paymentio.models import PaymentMethod

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
    SalesStatusChoices,
)
from salesio.models import Sale, SalePaymentReceive, SalePaymentReceiveItem

from transactionio.choices import BankReconciliationStatusChoices
from transactionio.models import BankReconciliation

from weapi.django_rest.helpers.sale_payment_posting import (
    unapply_sale_payment_items,
    void_sale_payment_postings,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class PaymentDeleteTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="P", email="paydel@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="Nusrat", last_name="Chowdhury"
        )
        self.bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "1000")
        self.receivable = self.account(
            "Accounts Receivable", ChartOfAccountKindChoices.ASSETS, "500"
        )
        # An invoice for 500, fully settled by a 500 receipt.
        self.sale = Sale.objects.create(
            company=self.company, customer=self.customer,
            status=SalesStatusChoices.PAID,
            total=Decimal("500"), due_total=Decimal("0"), deposit=Decimal("500"),
        )
        self.payment = SalePaymentReceive.objects.create(
            company=self.company, customer=self.customer,
            payment_method=PaymentMethod.objects.create(
                company=self.company, title="Bank Transfer"
            ),
            deposit_to=self.bank,
            status=SalePaymentReceiveStatusChoices.COMPLETED,
        )
        SalePaymentReceiveItem.objects.create(
            sale_payment_receive=self.payment,
            model_kind=SalePaymentReceiveItemModelKindChoices.SALE,
            sale=self.sale, total=Decimal("500"), used_total=Decimal("500"),
        )
        self.entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.SALE_PAYMENT_RECEIVE,
            status=JournalEntryStatusChoices.PUBLISHED,
            amount=Decimal("500"), sale_payment_receive=self.payment,
        )
        self.bank_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.bank, date="2026-03-01",
            debit=Decimal("500"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        self.ar_leg = JournalEntryConnector.objects.create(
            journal=self.entry, account=self.receivable, date="2026-03-01",
            debit=Decimal("0"), credit=Decimal("500"),
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        self.bank.opening_balance = Decimal("1500")
        self.bank.save()
        self.receivable.opening_balance = Decimal("0")
        self.receivable.save()

    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def delete(self):
        from weapi.django_rest.views.sales import PrivateWeSalePaymentReceiveDetails

        view = PrivateWeSalePaymentReceiveDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.payment)

    def balances(self):
        self.bank.refresh_from_db()
        self.receivable.refresh_from_db()
        return self.bank.opening_balance, self.receivable.opening_balance


class TheOldDeleteLeftEverythingBehindTests(PaymentDeleteTestCase):
    """What `status = REMOVED` alone did, shown rather than described."""

    def test_the_legs_stayed_published_so_the_register_still_showed_it(self):
        self.payment.status = SalePaymentReceiveStatusChoices.REMOVED
        self.payment.save()

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntryStatusChoices.PUBLISHED)
        self.assertEqual(
            JournalEntryConnector.objects.filter(account=self.bank).count(), 1
        )

    def test_and_the_invoice_stayed_paid_with_no_payment_behind_it(self):
        self.payment.status = SalePaymentReceiveStatusChoices.REMOVED
        self.payment.save()

        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SalesStatusChoices.PAID)
        self.assertEqual(self.sale.due_total, Decimal("0.000"))


class DeletingNowReversesTests(PaymentDeleteTestCase):
    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.filter(
            sale_payment_receive=self.payment
        ).exclude(pk=self.entry.pk).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_the_bank_nets_to_zero_so_the_register_no_longer_shows_money_in(self):
        self.delete()

        legs = JournalEntryConnector.objects.filter(account=self.bank)
        self.assertEqual(
            sum(l.debit for l in legs), sum(l.credit for l in legs)
        )

    def test_the_stored_balances_move_back(self):
        self.delete()
        self.assertEqual(self.balances(), (Decimal("1000.000"), Decimal("500.000")))

    def test_the_invoice_owes_again(self):
        self.delete()

        self.sale.refresh_from_db()
        self.assertEqual(self.sale.due_total, Decimal("500.000"))
        self.assertEqual(self.sale.deposit, Decimal("0.000"))
        self.assertEqual(self.sale.status, SalesStatusChoices.OPEN)

    def test_the_payment_is_retired(self):
        self.delete()
        self.payment.refresh_from_db()
        self.assertEqual(
            self.payment.status, SalePaymentReceiveStatusChoices.REMOVED
        )

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = self.balances()
        self.delete()
        self.assertEqual(self.balances(), after)

    def test_a_payment_that_posted_nothing_is_not_an_error(self):
        JournalEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertIsNone(void_sale_payment_postings(self.payment))

    def test_a_credit_note_line_moves_no_invoice(self):
        """Only SALE lines own a `due_total`."""
        SalePaymentReceiveItem.objects.create(
            sale_payment_receive=self.payment,
            model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE,
            total=Decimal("40"), used_total=Decimal("40"),
        )
        restored = unapply_sale_payment_items(self.payment)
        self.assertEqual(restored, Decimal("500.000"))


class ReconciledPaymentsAreRefusedTests(PaymentDeleteTestCase):
    """A closed reconciliation signed off these lines. Undo it first."""

    def close_a_session_over_the_bank_leg(self):
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
        return session

    def test_the_delete_is_refused_and_names_the_session(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )

        session = self.close_a_session_over_the_bank_leg()

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.delete()

        detail = str(caught.exception)
        self.assertIn("City Bank", detail)
        self.assertIn("2026-03-31", detail)
        self.assertIn(str(session.uid), detail)

    def test_nothing_moved_when_it_refused(self):
        self.close_a_session_over_the_bank_leg()
        before = self.balances()

        with self.assertRaises(Exception):
            self.delete()

        self.payment.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.sale.status, SalesStatusChoices.PAID)
        self.assertNotEqual(
            self.payment.status, SalePaymentReceiveStatusChoices.REMOVED
        )

    def test_an_undone_session_does_not_block(self):
        """Undone is a session the user has already unlocked on purpose."""
        session = self.close_a_session_over_the_bank_leg()
        BankReconciliation.objects.filter(pk=session.pk).update(
            status=BankReconciliationStatusChoices.UNDONE,
            undone_on="2026-04-01", undo_reason="restated",
        )

        self.delete()

        self.payment.refresh_from_db()
        self.assertEqual(
            self.payment.status, SalePaymentReceiveStatusChoices.REMOVED
        )
