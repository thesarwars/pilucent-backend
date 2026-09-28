"""A closed reconciliation is meant to be a fixed point. It was a moving target.

`assert_not_reconciled` refuses to disturb a leg that a CLOSED `BankReconciliation`
has signed off. It shipped wired to six DELETE paths and zero EDIT paths, so a
document whose bank leg had been ticked could still be amended freely -- and the
closed session's stored `difference` was zero when it closed, with nothing to
recompute it.

The edit half is worse than the doc described. It says a leg's amount gets
rewritten. Two of these paths **delete the leg outright**:

* `reverse_sale_postings` calls `journal_entry.delete()` and
  `JournalEntryConnector.journal` is CASCADE, so amending a sale destroys every
  leg it posted -- `reconciliation` and `cleared_on` with them.
* `reverse_pay_bill_item_postings` hard-deletes a payee line's legs directly.

A rewritten leg leaves a session asserting a figure that no longer adds up. A
deleted one leaves it asserting a figure computed against rows that no longer
exist, and there is nothing left to notice with.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from common.django_rest.helpers.reconciliation_guard import ReconciledLineLocked

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from transactionio.choices import BankReconciliationStatusChoices
from transactionio.models import BankReconciliation


class FakeRequest:
    def __init__(self, user):
        self.user = user


class ReconciledLegTestCase(TestCase):
    """A bank leg ticked by a session that has been closed."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="R", email="recon@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.bank = ChartOfAccount.objects.create(
            company=self.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("1000"),
        )

    def entry(self, **fk):
        return JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.JOURNAL_ENTRY,
            status=JournalEntryStatusChoices.PUBLISHED, date=date(2026, 3, 1),
            amount=Decimal("100"), **fk
        )

    def leg(self, entry, account=None):
        return JournalEntryConnector.objects.create(
            journal=entry, account=account or self.bank, date=date(2026, 3, 1),
            debit=Decimal("100"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )

    def close_over(self, leg):
        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"), beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        return session


class TheGuardIsWiredToTheEditPathsTests(ReconciledLegTestCase):
    """Each of these could rewrite or destroy a signed-off leg."""

    def guarded(self, name, obj):
        """Every guarded path resolves its entries the same way."""
        from common.django_rest.helpers.reconciliation_guard import (
            closed_reconciliations_for,
        )

        return closed_reconciliations_for(obj)

    def test_a_closed_session_is_found_through_any_documents_entries(self):
        entry = self.entry()
        leg = self.leg(entry)
        session = self.close_over(leg)

        found = self.guarded("manual", JournalEntry.objects.filter(pk=entry.pk))
        self.assertEqual([s.pk for s in found], [session.pk])

    def test_an_undone_session_does_not_lock_anything(self):
        """Undone is a session the user has already unlocked on purpose."""
        entry = self.entry()
        leg = self.leg(entry)
        session = self.close_over(leg)
        BankReconciliation.objects.filter(pk=session.pk).update(
            status=BankReconciliationStatusChoices.UNDONE,
            undone_on="2026-04-01", undo_reason="restated",
        )

        self.assertEqual(
            self.guarded("manual", JournalEntry.objects.filter(pk=entry.pk)), []
        )

    def test_an_unreconciled_leg_locks_nothing(self):
        entry = self.entry()
        self.leg(entry)
        self.assertEqual(
            self.guarded("manual", JournalEntry.objects.filter(pk=entry.pk)), []
        )


class AmendingAManualEntryIsRefusedTests(ReconciledLegTestCase):
    """The most direct instance: a bookkeeper editing a hand-keyed entry.

    The line loop rewrites `debit`, `credit`, `kind`, `date` AND `account` on
    the existing rows through a queryset `.update()`, so a ticked leg could even
    change which account it belonged to while still pointing at the session that
    cleared it.
    """

    def amend(self, entry, items):
        from weapi.django_rest.serializers.journals import (
            PrivateWeJournalEntryDetailsSerializer,
        )

        serializer = PrivateWeJournalEntryDetailsSerializer()
        serializer.context["request"] = FakeRequest(self.user)
        return serializer.update(entry, {"journal_items": items})

    def test_it_is_refused(self):
        entry = self.entry()
        leg = self.leg(entry)
        session = self.close_over(leg)

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.amend(entry, [{
                "uid": str(leg.uid), "account_uid": str(self.bank.uid),
                "debit": "999", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            }])

        detail = str(caught.exception)
        self.assertIn("City Bank", detail)
        self.assertIn(str(session.uid), detail)

    def test_the_leg_is_untouched_when_it_refuses(self):
        entry = self.entry()
        leg = self.leg(entry)
        self.close_over(leg)

        with self.assertRaises(ReconciledLineLocked):
            self.amend(entry, [{
                "uid": str(leg.uid), "account_uid": str(self.bank.uid),
                "debit": "999", "credit": "0",
                "kind": JournalEntryConnectorKindChoices.DEBIT,
            }])

        leg.refresh_from_db()
        self.bank.refresh_from_db()
        self.assertEqual(leg.debit, Decimal("100.000"))
        self.assertEqual(self.bank.opening_balance, Decimal("1000.000"))

    def test_an_unreconciled_entry_still_amends(self):
        entry = self.entry()
        leg = self.leg(entry)

        self.amend(entry, [{
            "uid": str(leg.uid), "account_uid": str(self.bank.uid),
            "debit": "150", "credit": "0",
            "kind": JournalEntryConnectorKindChoices.DEBIT,
        }])

        leg.refresh_from_db()
        self.assertEqual(leg.debit, Decimal("150.000"))


class DeletingAPayBillLineIsRefusedTests(ReconciledLegTestCase):
    """`reverse_pay_bill_item_postings` hard-deletes the legs -- no reversal."""

    def setUp(self):
        super().setUp()
        from purchaseio.choices import PayBillItemStatusChoices, PayBillStatusChoices
        from purchaseio.models import PayBill, PayBillItem
        from supplierio.models import Supplier

        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders"
        )
        self.pay_bill = PayBill.objects.create(
            company=self.company, payment_account=self.bank,
            status=PayBillStatusChoices.PUBLISHED, total=Decimal("100"),
        )
        self.item = PayBillItem.objects.create(
            pay_bill=self.pay_bill, supplier=self.supplier,
            status=PayBillItemStatusChoices.PUBLISHED, total=Decimal("100"),
        )
        self.pay_entry = self.entry(pay_bill=self.pay_bill)
        self.pay_leg = self.leg(self.pay_entry)

    def test_deleting_the_line_is_refused(self):
        from weapi.django_rest.views.pay_bills import PrivateWePayBillItemDetails

        self.close_over(self.pay_leg)
        view = PrivateWePayBillItemDetails()
        view.request = FakeRequest(self.user)

        with self.assertRaises(ReconciledLineLocked):
            view.perform_destroy(self.item)

        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.pay_leg.pk).exists()
        )

    def test_deleting_the_whole_payment_is_refused(self):
        from weapi.django_rest.views.pay_bills import PrivateWePayBillDetails

        self.close_over(self.pay_leg)
        view = PrivateWePayBillDetails()
        view.request = FakeRequest(self.user)

        with self.assertRaises(ReconciledLineLocked):
            view.perform_destroy(self.pay_bill)

        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.pay_leg.pk).exists()
        )


class AmendingAPurchaseIsRefusedTests(ReconciledLegTestCase):
    """Bill and cheque amends both rewrite legs of an already-posted entry."""

    def setUp(self):
        super().setUp()
        from purchaseio.choices import PurchaseStatus
        from purchaseio.models import Purchase
        from supplierio.models import Supplier

        self.supplier = Supplier.objects.create(
            company=self.company, first_name="Rahim", last_name="Traders"
        )
        self.purchase = Purchase.objects.create(
            company=self.company, supplier=self.supplier, is_bill=True,
            status=PurchaseStatus.OPEN, total=Decimal("100"),
        )
        self.purchase_entry = self.entry(purchase=self.purchase)
        self.purchase_leg = self.leg(self.purchase_entry)

    def amend(self):
        from weapi.django_rest.serializers.purchases import (
            PrivateWePurchaseDetailsSerializer,
        )

        serializer = PrivateWePurchaseDetailsSerializer()
        serializer.context["request"] = FakeRequest(self.user)
        return serializer.update(self.purchase, {"total": Decimal("999")})

    def test_a_reconciled_bill_cannot_be_amended(self):
        session = self.close_over(self.purchase_leg)

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.amend()

        self.assertIn(str(session.uid), str(caught.exception))

    def test_the_leg_is_untouched_when_it_refuses(self):
        self.close_over(self.purchase_leg)

        with self.assertRaises(ReconciledLineLocked):
            self.amend()

        self.purchase_leg.refresh_from_db()
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase_leg.debit, Decimal("100.000"))
        self.assertEqual(self.purchase.total, Decimal("100.000"))

    def test_one_guard_covers_both_the_bill_and_cheque_branches(self):
        """They are two branches of a single `update()`, not two methods."""
        import inspect

        from weapi.django_rest.serializers.purchases import (
            PrivateWePurchaseDetailsSerializer,
        )

        source = inspect.getsource(PrivateWePurchaseDetailsSerializer.update)
        self.assertEqual(source.count("assert_not_reconciled("), 1)
        self.assertIn("is_cheque", source)


class TheGuardsSitWhereTheMutationIsTests(ReconciledLegTestCase):
    """Placement is the difference between a guard and a nuisance.

    The expense, pay-bill and pay-bill-item amends only rewrite a leg when the
    amount actually moves. Guarding the whole method would refuse a
    description-only edit that touches no ledger row — a refusal blocking
    something that was always legal. Each of those guards sits inside the branch
    that does the writing.
    """

    def source_of(self, dotted):
        import importlib
        import inspect

        module, _, name = dotted.rpartition(".")
        cls = getattr(importlib.import_module(module), name)
        return inspect.getsource(cls.update)

    def test_the_expense_guard_is_inside_the_payment_account_branch(self):
        source = self.source_of(
            "weapi.django_rest.serializers.purchases."
            "PrivateWeExpenseDetailsSerializer"
        )
        before, _, after = source.partition("assert_not_reconciled(")
        self.assertIn("if payment_account:", before)
        self.assertIn("amend_leg(", after)

    def test_the_pay_bill_guard_is_inside_the_account_changed_branch(self):
        source = self.source_of(
            "weapi.django_rest.serializers.pay_bills."
            "PrivateWePayBillDetailsSerializer"
        )
        before, _, _after = source.partition("assert_not_reconciled(")
        self.assertIn("if old_payment_account != new_payment_account:", before)

    def test_the_pay_bill_item_guard_precedes_the_first_write(self):
        source = self.source_of(
            "weapi.django_rest.serializers.pay_bills."
            "PrivateWePayBillItemDetailsSerializer"
        )
        before, _, after = source.partition("assert_not_reconciled(")
        self.assertIn("if old_total != new_total", before)
        self.assertIn("unapply_pay_bill_item(", after)

    def test_the_purchase_line_delete_guard_precedes_the_stock_move(self):
        import inspect

        from weapi.django_rest.views.purchases import PrivateWePurchaseItemDetails

        source = inspect.getsource(PrivateWePurchaseItemDetails.perform_destroy)
        before, _, after = source.partition("assert_not_reconciled(")
        self.assertIn("_posted_entries(", before)
        self.assertIn("update_quantity(", after)
