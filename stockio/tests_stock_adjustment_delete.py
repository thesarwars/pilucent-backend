"""Deleting a stock adjustment moved no stock and reversed no ledger.

`perform_destroy` set the document's status to REMOVED and did nothing else -- on
the one document whose entire purpose is to move inventory. The units stayed on
hand, the cost layers stayed created or spent, and both journal legs stayed
PUBLISHED, so the adjustment account went on carrying a write-up or write-down
for a document that no longer existed.

The tests below are in four groups:

* what the old delete left behind, demonstrated rather than described
* the reversal: units, layers, legs and stored balances
* the ordering that makes a mixed adjustment come out right, which is the part
  that is easy to get wrong and silent when it is wrong
* the two refusals -- stock already consumed by somebody else, and a closed
  reconciliation
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

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from stockio.choices import (
    StockAdjustmentItemKindChoices,
    StockAdjustmentItemStatusChoices,
    StockAdjustmentStatusChoices,
    StockMovementTypeChoices,
)
from stockio.django_rest.services.stock_movement import (
    ledger_layers,
    ledger_on_hand,
    record_stock_movement,
)
from stockio.models import (
    StockAdjustment,
    StockAdjustmentItem,
    StockMovement,
    StockMovementLayerConsumption,
)

from weapi.django_rest.helpers.stock_adjustment_posting import (
    AdjustmentStockConsumed,
    externally_consumed_layers,
    restore_stock_adjustment_inventory,
    void_stock_adjustment_postings,
)


class FakeRequest:
    def __init__(self, user):
        self.user = user


class StockAdjustmentDeleteTestCase(TestCase):
    """A write-up of 10 widgets at 5.000, posted the way the serializer posts it."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="S", email="stockdel@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)

        self.inventory = self.account(
            "Inventory Asset", ChartOfAccountKindChoices.ASSETS, "1000"
        )
        self.adjustment_account = self.account(
            "Inventory Shrinkage", ChartOfAccountKindChoices.EXPENSES, "0"
        )
        self.widget = self.product("Widget", quantity=10)

        self.adjustment = StockAdjustment.objects.create(
            company=self.company,
            stock_adjustment_account=self.adjustment_account,
            status=StockAdjustmentStatusChoices.ACTIVE,
            date=date(2026, 3, 1),
            reason="Recount",
        )
        self.item = self.line(self.widget, 10, StockAdjustmentItemKindChoices.ADDITION)
        self.movement = record_stock_movement(
            company=self.company,
            product=self.widget,
            date=self.adjustment.date,
            movement_type=StockMovementTypeChoices.ADJUSTMENT_IN,
            signed_quantity=10,
            rate=Decimal("5.000"),
            stock_adjustment_item=self.item,
        )

        # 10 x 5.000 = 50: inventory DEBITS, the adjustment account CREDITS.
        self.entry = JournalEntry.objects.create(
            company=self.company,
            kind=JournalEntryKindChoices.STOCK_ADJUSTMENT,
            status=JournalEntryStatusChoices.PUBLISHED,
            date=self.adjustment.date,
            amount=Decimal("50"),
            stock_adjustment=self.adjustment,
        )
        self.inventory_leg = self.leg(
            self.inventory, debit="50", kind=JournalEntryConnectorKindChoices.DEBIT
        )
        self.contra_leg = self.leg(
            self.adjustment_account,
            credit="50",
            kind=JournalEntryConnectorKindChoices.CREDIT,
        )
        self.inventory.opening_balance = Decimal("1050")
        self.inventory.save()
        self.adjustment_account.opening_balance = Decimal("-50")
        self.adjustment_account.save()

    # -- fixtures ---------------------------------------------------------
    def account(self, title, kind, balance):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(balance),
        )

    def product(self, title, quantity):
        return Product.objects.create(
            company=self.company, title=title, sku=title.upper(),
            quantity=quantity, date=date(2026, 1, 1),
            kind=ProductKindChoices.PRODUCT, status=ProductStatusChoices.ACTIVE,
            is_inventory=True, is_stock=True,
        )

    def line(self, product, quantity, kind):
        return StockAdjustmentItem.objects.create(
            stock_adjustment=self.adjustment, product=product, quantity=quantity,
            kind=kind, status=StockAdjustmentItemStatusChoices.ACTIVE,
        )

    def leg(self, account, debit="0", credit="0", kind=None, journal=None):
        return JournalEntryConnector.objects.create(
            journal=journal or self.entry, account=account, date="2026-03-01",
            debit=Decimal(debit), credit=Decimal(credit), kind=kind,
        )

    # -- helpers ----------------------------------------------------------
    def delete(self):
        from weapi.django_rest.views.stock import PrivateWeStockAdjustmentDetails

        view = PrivateWeStockAdjustmentDetails()
        view.request = FakeRequest(self.user)
        view.perform_destroy(self.adjustment)

    def on_hand(self):
        self.widget.refresh_from_db()
        return self.widget.quantity

    def balances(self):
        self.inventory.refresh_from_db()
        self.adjustment_account.refresh_from_db()
        return self.inventory.opening_balance, self.adjustment_account.opening_balance


class TheOldDeleteMovedNoStockTests(StockAdjustmentDeleteTestCase):
    """What `status = REMOVED` alone did, shown rather than described."""

    def test_the_units_stayed_on_hand(self):
        self.adjustment.status = StockAdjustmentStatusChoices.REMOVED
        self.adjustment.save()

        self.assertEqual(self.on_hand(), 10)
        self.assertEqual(ledger_on_hand(self.widget), 10)

    def test_the_legs_stayed_published_so_the_register_still_showed_it(self):
        self.adjustment.status = StockAdjustmentStatusChoices.REMOVED
        self.adjustment.save()

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, JournalEntryStatusChoices.PUBLISHED)
        self.assertEqual(self.balances(), (Decimal("1050.000"), Decimal("-50.000")))


class DeletingNowReversesTests(StockAdjustmentDeleteTestCase):
    def test_the_units_come_off_hand(self):
        self.delete()
        self.assertEqual(self.on_hand(), 0)

    def test_the_layer_it_created_is_spent_not_left_open(self):
        """Give the units back without spending the layer and FIFO resells them."""
        self.delete()

        self.assertEqual(ledger_layers(self.widget), [])
        self.assertEqual(ledger_on_hand(self.widget), 0)

    def test_a_reversing_entry_is_posted_and_the_original_survives(self):
        self.delete()

        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        reversal = JournalEntry.objects.filter(
            stock_adjustment=self.adjustment
        ).exclude(pk=self.entry.pk).get()
        legs = JournalEntryConnector.objects.filter(journal=reversal)
        self.assertEqual(legs.count(), 2)
        for leg in legs:
            self.assertEqual(
                leg.request_kind, JournalEntryConnectorRequestKindChoices.DELETED
            )

    def test_the_reversal_is_dated_to_the_adjustment_not_to_today(self):
        self.delete()

        reversal = JournalEntry.objects.filter(
            stock_adjustment=self.adjustment
        ).exclude(pk=self.entry.pk).get()
        self.assertEqual(reversal.date, date(2026, 3, 1))
        for leg in JournalEntryConnector.objects.filter(journal=reversal):
            self.assertEqual(leg.date, date(2026, 3, 1))

    def test_the_inventory_account_nets_to_zero(self):
        self.delete()

        legs = JournalEntryConnector.objects.filter(account=self.inventory)
        self.assertEqual(sum(l.debit for l in legs), sum(l.credit for l in legs))

    def test_the_stored_balances_move_back(self):
        self.delete()
        self.assertEqual(self.balances(), (Decimal("1000.000"), Decimal("0.000")))

    def test_the_adjustment_is_retired(self):
        self.delete()
        self.adjustment.refresh_from_db()
        self.assertEqual(self.adjustment.status, StockAdjustmentStatusChoices.REMOVED)

    def test_deleting_twice_does_not_double_reverse(self):
        self.delete()
        after = (self.balances(), self.on_hand())
        self.delete()
        self.assertEqual((self.balances(), self.on_hand()), after)

    def test_an_adjustment_that_posted_nothing_is_not_an_error(self):
        JournalEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertIsNone(void_stock_adjustment_postings(self.adjustment))

    def test_the_reversal_movement_names_its_line(self):
        """Without the FK the idempotence check can never see its own work."""
        self.delete()

        reversal = StockMovement.objects.get(
            movement_type=StockMovementTypeChoices.REVERSAL
        )
        self.assertEqual(reversal.stock_adjustment_item_id, self.item.pk)
        self.assertEqual(reversal.signed_quantity, -10)
        self.assertEqual(reversal.inventory_cost, Decimal("-50.000"))


class WritingDownReversesTheOtherWayTests(StockAdjustmentDeleteTestCase):
    """A deduction relieves layers; undoing it has to un-relieve them."""

    def setUp(self):
        super().setUp()
        # A separate product with a purchased layer of 8 at 4.000, written down
        # by 3. The write-up above is left alone.
        self.gadget = self.product("Gadget", quantity=8)
        self.layer = record_stock_movement(
            company=self.company, product=self.gadget, date=date(2026, 1, 5),
            movement_type=StockMovementTypeChoices.OPENING,
            signed_quantity=8, rate=Decimal("4.000"),
        )
        self.shrink_item = self.line(
            self.gadget, 3, StockAdjustmentItemKindChoices.DEDUCTION
        )
        self.gadget.quantity = 5
        self.gadget.save()
        self.shrink = record_stock_movement(
            company=self.company, product=self.gadget, date=self.adjustment.date,
            movement_type=StockMovementTypeChoices.ADJUSTMENT_OUT,
            signed_quantity=-3, rate=Decimal("4.000"),
            layer_slices=[(self.layer, Decimal("3"), Decimal("4.000"))],
            stock_adjustment_item=self.shrink_item,
        )

    def test_the_units_go_back_on_hand(self):
        self.delete()
        self.gadget.refresh_from_db()
        self.assertEqual(self.gadget.quantity, 8)

    def test_the_layer_is_whole_again_rather_than_still_looking_spent(self):
        """The failure this guards: on hand says 8, the layers say 5."""
        self.delete()

        self.assertEqual(ledger_on_hand(self.gadget), 8)
        layers = ledger_layers(self.gadget)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0][1], Decimal("8"))

    def test_the_reversal_carries_negative_slices_against_the_same_lot(self):
        self.delete()

        reversal = StockMovement.objects.get(
            product=self.gadget, movement_type=StockMovementTypeChoices.REVERSAL
        )
        slices = list(reversal.layer_consumptions.all())
        self.assertEqual(len(slices), 1)
        self.assertEqual(slices[0].source_movement_id, self.layer.pk)
        self.assertEqual(slices[0].quantity_consumed, Decimal("-3.0000"))


class TheOrderOfTheTwoPassesTests(StockAdjustmentDeleteTestCase):
    """One adjustment writing the same product up and then down.

    The write-down draws on the write-up's brand-new layer, so reversing the
    write-up first would find its layer already spent, withdraw nothing, and
    leave on-hand and the journal disagreeing by the full amount.
    """

    def setUp(self):
        super().setUp()
        # The write-up of 10 already exists. Now write 4 back down off it.
        self.down_item = self.line(
            self.widget, 4, StockAdjustmentItemKindChoices.DEDUCTION
        )
        self.widget.quantity = 6
        self.widget.save()
        self.down = record_stock_movement(
            company=self.company, product=self.widget, date=self.adjustment.date,
            movement_type=StockMovementTypeChoices.ADJUSTMENT_OUT,
            signed_quantity=-4, rate=Decimal("5.000"),
            layer_slices=[(self.movement, Decimal("4"), Decimal("5.000"))],
            stock_adjustment_item=self.down_item,
        )

    def test_internal_consumption_is_not_treated_as_someone_elses(self):
        self.assertEqual(externally_consumed_layers(self.adjustment), [])

    def test_both_halves_unwind_to_nothing(self):
        self.delete()

        self.assertEqual(self.on_hand(), 0)
        self.assertEqual(ledger_on_hand(self.widget), 0)
        self.assertEqual(ledger_layers(self.widget), [])

    def test_the_write_down_is_reversed_before_the_write_up(self):
        """The ordering is the whole design; assert it, do not assume it."""
        self.delete()

        reversals = list(
            StockMovement.objects.filter(
                product=self.widget, movement_type=StockMovementTypeChoices.REVERSAL
            ).order_by("id")
        )
        self.assertEqual(
            [r.signed_quantity for r in reversals], [4, -10],
            "the ADJUSTMENT_OUT must be reversed first, or the IN has no layer left",
        )


class StockSomebodyElseHasUsedIsRefusedTests(StockAdjustmentDeleteTestCase):
    """Units that have left cannot be taken back off the shelf."""

    def consume_six_units_on_another_document(self):
        sale_movement = record_stock_movement(
            company=self.company, product=self.widget, date=date(2026, 4, 1),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-6, rate=Decimal("9.000"),
            layer_slices=[(self.movement, Decimal("6"), Decimal("5.000"))],
        )
        self.widget.quantity = 4
        self.widget.save()
        return sale_movement

    def test_the_layer_is_reported_as_externally_consumed(self):
        self.consume_six_units_on_another_document()

        consumed = externally_consumed_layers(self.adjustment)
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0][0].pk, self.movement.pk)
        self.assertEqual(consumed[0][1], Decimal("6"))

    def test_the_delete_is_refused_and_names_the_product(self):
        self.consume_six_units_on_another_document()

        with self.assertRaises(AdjustmentStockConsumed) as caught:
            self.delete()

        self.assertIn("Widget", str(caught.exception))

    def test_nothing_moved_when_it_refused(self):
        self.consume_six_units_on_another_document()
        before = self.balances()

        with self.assertRaises(AdjustmentStockConsumed):
            self.delete()

        self.adjustment.refresh_from_db()
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.on_hand(), 4)
        self.assertNotEqual(
            self.adjustment.status, StockAdjustmentStatusChoices.REMOVED
        )
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovementTypeChoices.REVERSAL
            ).exists()
        )

    def test_on_hand_short_of_the_layer_is_refused_rather_than_a_500(self):
        """`Product.quantity` is a PositiveIntegerField; do not let it raise."""
        self.widget.quantity = 3
        self.widget.save()

        with self.assertRaises(AdjustmentStockConsumed):
            self.delete()

        self.assertEqual(self.on_hand(), 3)


class ReconciledAdjustmentsAreRefusedTests(StockAdjustmentDeleteTestCase):
    """The adjustment account takes any selectable account, a bank one included."""

    def close_a_session_over_the_inventory_leg(self):
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        session = BankReconciliation.objects.create(
            company=self.company, bank_account=self.inventory,
            status=BankReconciliationStatusChoices.CLOSED,
            statement_ending_balance=Decimal("0"), beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31", reconciled_on="2026-03-31",
        )
        JournalEntryConnector.objects.filter(pk=self.inventory_leg.pk).update(
            reconciliation=session, cleared_on="2026-03-31"
        )
        return session

    def test_the_delete_is_refused_and_names_the_session(self):
        from common.django_rest.helpers.reconciliation_guard import (
            ReconciledLineLocked,
        )

        session = self.close_a_session_over_the_inventory_leg()

        with self.assertRaises(ReconciledLineLocked) as caught:
            self.delete()

        detail = str(caught.exception)
        self.assertIn("Inventory Asset", detail)
        self.assertIn(str(session.uid), detail)

    def test_the_stock_is_untouched_when_it_refused(self):
        """The guard runs before the inventory pass, not after it."""
        self.close_a_session_over_the_inventory_leg()

        with self.assertRaises(Exception):
            self.delete()

        self.assertEqual(self.on_hand(), 10)
        self.assertEqual(
            StockMovementLayerConsumption.objects.filter(
                source_movement=self.movement
            ).count(),
            0,
        )


class AnotherCompanysLineCannotBeRewrittenTests(StockAdjustmentDeleteTestCase):
    """`StockAdjustmentItem.objects.get(uid=...)` took any uid in the table.

    The uid comes straight from the request body, and
    `stockio_stockadjustmentitem` carries no row-level-security policy — unlike
    ChartOfAccount, Product, Sale, Purchase and Customer, where the database
    refuses a cross-tenant row even when the query forgets. So the amend loop
    resolved any line in the installation and rewrote its `status`, `kind`,
    `description`, `quantity` and `product`.

    Scoped to the parent adjustment rather than to the company, which is
    narrower: `instance` is already tenant-scoped by the view's `get_object`,
    and a line on a *different* adjustment of the *same* company has no business
    being rewritten through this endpoint either.
    """

    def setUp(self):
        super().setUp()
        self.other_company = Company.objects.create(name="Theirs", kind="ECOMMERCE")
        self.their_account = ChartOfAccount.objects.create(
            company=self.other_company, title="Their Adjust", code="TA",
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )
        self.their_product = Product.objects.create(
            company=self.other_company, title="Their Widget", sku="TW",
            quantity=50, date=date(2026, 1, 1), kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, is_inventory=True, is_stock=True,
        )
        self.their_adjustment = StockAdjustment.objects.create(
            company=self.other_company,
            stock_adjustment_account=self.their_account,
            status=StockAdjustmentStatusChoices.ACTIVE, date=date(2026, 3, 1),
        )
        self.their_line = StockAdjustmentItem.objects.create(
            stock_adjustment=self.their_adjustment, product=self.their_product,
            quantity=7, kind=StockAdjustmentItemKindChoices.ADDITION,
            status=StockAdjustmentItemStatusChoices.ACTIVE,
        )

    def amend(self, line_uid, quantity):
        from weapi.django_rest.serializers.stock import (
            PrivateWeStockAdjustmentDetailSerializer,
        )

        serializer = PrivateWeStockAdjustmentDetailSerializer()
        serializer.context["request"] = FakeRequest(self.user)
        return serializer.update(
            self.adjustment,
            {
                "stock_adjustment_items": [
                    {
                        "uid": str(line_uid),
                        "quantity": quantity,
                        "product_uid": str(self.widget.uid),
                        "kind": StockAdjustmentItemKindChoices.ADDITION,
                    }
                ]
            },
        )

    def test_a_line_on_another_companys_adjustment_is_not_reachable(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            self.amend(self.their_line.uid, 999)

        self.their_line.refresh_from_db()
        self.assertEqual(self.their_line.quantity, 7)
        self.assertEqual(self.their_line.product_id, self.their_product.pk)

    def test_our_own_line_still_amends(self):
        self.amend(self.item.uid, 12)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 12)
