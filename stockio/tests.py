"""Tests for the inventory movement ledger service."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from companyio.models import Company
from productio.models import Product
from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import Purchase, PurchaseItem
from supplierio.models import Supplier

from stockio.choices import StockMovementTypeChoices
from stockio.django_rest.services.stock_movement import (
    current_inventory_asset_value,
    record_stock_movement,
)


class StockMovementServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(first_name="Vendor", company=cls.company)
        cls.product = Product.objects.create(
            sku="SKU1",
            title="Widget",
            quantity=0,
            date=date(2026, 1, 1),
            kind="PRODUCT",
            status="ACTIVE",
            is_inventory=True,
            company=cls.company,
        )

    def _lot(self, qty, price):
        """A published purchase lot (bill) with `qty` units at `price` each."""
        purchase = Purchase.objects.create(
            supplier=self.supplier,
            company=self.company,
            is_bill=True,
            status=PurchaseStatus.COMPLETED,
        )
        return PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            status=PurchaseItemStatus.PUBLISHED,
            quantity=qty,
            purchase_price=Decimal(price),
        )

    def _purchase(self, qty, price, *, on_date):
        """Record a PURCHASE movement (adds a lot, bumps on-hand)."""
        lot = self._lot(qty, price)
        self.product.quantity = (self.product.quantity or 0) + qty
        self.product.save()
        return record_stock_movement(
            company=self.company,
            product=self.product,
            date=on_date,
            movement_type=StockMovementTypeChoices.PURCHASE,
            signed_quantity=qty,
            rate=Decimal(price),
            purchase_item=lot,
        ), lot

    def test_purchase_movement_records_facts(self):
        mv, _ = self._purchase(10, "400", on_date=date(2026, 1, 2))
        self.assertEqual(mv.signed_quantity, 10)
        self.assertEqual(mv.inventory_cost, Decimal("4000"))
        self.assertEqual(mv.rate, Decimal("400"))

    def test_sale_movement_records_fifo_layers_and_cogs(self):
        _, lot400 = self._purchase(10, "400", on_date=date(2026, 1, 1))
        _, lot450 = self._purchase(10, "450", on_date=date(2026, 1, 2))

        # Simulate FIFO consuming 12 units: 10 @ 400, then 2 @ 450.
        lot400.quantity = 0
        lot400.save()
        lot450.quantity = 8
        lot450.save()
        self.product.quantity = 8
        self.product.save()

        mv = record_stock_movement(
            company=self.company,
            product=self.product,
            date=date(2026, 1, 3),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-12,
            layer_slices=[(lot400, 10, Decimal("400")), (lot450, 2, Decimal("450"))],
        )
        # COGS = 10*400 + 2*450 = 4900 (asset falls -> negative)
        self.assertEqual(mv.inventory_cost, Decimal("-4900"))

        slices = mv.layer_consumptions.order_by("unit_cost")
        self.assertEqual(slices.count(), 2)
        self.assertEqual(
            [(s.quantity_consumed, s.unit_cost, s.cost_amount) for s in slices],
            [
                (Decimal("10.0000"), Decimal("400.000"), Decimal("4000.000")),
                (Decimal("2.0000"), Decimal("450.000"), Decimal("900.000")),
            ],
        )
        self.assertFalse(any(s.is_fallback for s in slices))

    def test_fallback_slice_flagged(self):
        self.product.quantity = 3
        self.product.save()
        mv = record_stock_movement(
            company=self.company,
            product=self.product,
            date=date(2026, 1, 4),
            movement_type=StockMovementTypeChoices.SALE,
            signed_quantity=-3,
            layer_slices=[(None, 3, Decimal("410"))],  # layers exhausted
        )
        self.assertEqual(mv.inventory_cost, Decimal("-1230"))
        slice_ = mv.layer_consumptions.get()
        self.assertTrue(slice_.is_fallback)
        self.assertIsNone(slice_.purchase_item)

    def test_current_inventory_asset_value_sums_live_lots(self):
        self._lot(10, "400")
        self._lot(5, "450")
        self.assertEqual(current_inventory_asset_value(self.product), Decimal("6250"))
        # a depleted lot (quantity 0) drops out
        self._lot(0, "999")
        self.assertEqual(current_inventory_asset_value(self.product), Decimal("6250"))


class InventoryValuationDetailReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(first_name="Vendor", company=cls.company)
        cls.product = Product.objects.create(
            sku="SKU1", title="Widget", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", is_inventory=True, company=cls.company,
        )

    def _movement(self, mtype, qty, cost, on_date):
        from stockio.models import StockMovement
        return StockMovement.objects.create(
            company=self.company, product=self.product, date=on_date,
            movement_type=mtype, signed_quantity=qty, inventory_cost=Decimal(cost),
        )

    def test_report_derives_running_balances_subtotal_and_total(self):
        from weapi.django_rest.helpers.reports.inventory_valuation_detail import (
            inventory_valuation_detail,
        )
        self._movement("PURCHASE", 10, "4000", date(2026, 1, 1))
        self._movement("PURCHASE", 10, "4500", date(2026, 1, 2))
        self._movement("SALE", -12, "-4900", date(2026, 1, 3))

        report = inventory_valuation_detail(self.company, as_of=date(2026, 1, 31))
        self.assertEqual(len(report["groups"]), 1)
        group = report["groups"][0]
        self.assertEqual(len(group["rows"]), 3)
        # running balances derived by cumulating in date order
        self.assertEqual(
            [(r["running_quantity"], r["running_value"]) for r in group["rows"]],
            [(10.0, 4000.0), (20.0, 8500.0), (8.0, 3600.0)],
        )
        self.assertEqual(group["subtotal"]["quantity"], 8.0)
        self.assertEqual(group["subtotal"]["asset_value"], 3600.0)
        self.assertEqual(group["subtotal"]["inventory_cost"], 3600.0)  # 4000+4500-4900
        self.assertEqual(report["total"]["asset_value"], 3600.0)
        self.assertEqual(group["rows"][2]["transaction_type"], "Sale")
        self.assertEqual(group["rows"][2]["quantity"], -12.0)

    def test_backdated_movement_does_not_corrupt_running_balances(self):
        # The bug the review caught: enter a later-dated purchase, THEN a
        # backdated one. Running balances must still be monotonic by date.
        from weapi.django_rest.helpers.reports.inventory_valuation_detail import (
            inventory_valuation_detail,
        )
        self._movement("PURCHASE", 5, "500", date(2026, 7, 6))  # entered first
        self._movement("PURCHASE", 3, "300", date(2026, 1, 1))  # backdated, entered second

        report = inventory_valuation_detail(self.company, as_of=date(2026, 12, 31))
        rows = report["groups"][0]["rows"]
        # sorted by date: Jan(3, 300) then Jul(8, 800) — balances rise, not fall
        self.assertEqual(
            [(r["date"], r["running_quantity"], r["running_value"]) for r in rows],
            [("2026-01-01", 3.0, 300.0), ("2026-07-06", 8.0, 800.0)],
        )
        self.assertEqual(report["groups"][0]["subtotal"]["asset_value"], 800.0)
        self.assertEqual(report["total"]["asset_value"], 800.0)  # true value, not 500

    def test_as_of_excludes_later_movements(self):
        from weapi.django_rest.helpers.reports.inventory_valuation_detail import (
            inventory_valuation_detail,
        )
        self._movement("PURCHASE", 10, "4000", date(2026, 1, 1))
        self._movement("SALE", -3, "-1200", date(2026, 2, 1))
        report = inventory_valuation_detail(self.company, as_of=date(2026, 1, 15))
        self.assertEqual(len(report["groups"][0]["rows"]), 1)  # Feb sale excluded
        self.assertEqual(report["total"]["asset_value"], 4000.0)


class AssembleDetailPureTests(TestCase):
    def test_multiple_products_group_independently(self):
        from weapi.django_rest.helpers.reports.inventory_valuation_detail import (
            assemble_detail,
        )
        movements = [
            {"product_uid": "a", "product": "A", "sku": "", "date": "2026-01-01",
             "type": "PURCHASE", "quantity": 5, "rate": Decimal("10"),
             "inventory_cost": Decimal("50")},
            {"product_uid": "b", "product": "B", "sku": "", "date": "2026-01-01",
             "type": "OPENING", "quantity": 2, "rate": Decimal("30"),
             "inventory_cost": Decimal("60")},
        ]
        report = assemble_detail(movements, date(2026, 1, 31))
        self.assertEqual([g["product"] for g in report["groups"]], ["A", "B"])
        self.assertEqual(report["total"]["asset_value"], 110.0)  # 50 + 60
        # each product's running derived independently from its own first row
        self.assertEqual(report["groups"][0]["subtotal"]["asset_value"], 50.0)
        self.assertEqual(report["groups"][1]["subtotal"]["asset_value"], 60.0)


class SeedOpeningMovementsCommandTests(TestCase):
    def test_seeds_one_opening_per_product_idempotently(self):
        from django.core.management import call_command
        from accounts.models import ChartOfAccount
        from productio.models import ProductAdditionalCost
        from stockio.models import StockMovement

        company = Company.objects.create(name="Acme")
        product = Product.objects.create(
            sku="S", title="Widget", quantity=5, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", is_inventory=True, company=company,
        )
        account = ChartOfAccount.objects.create(
            code="5000", title="COGS", company=company
        )
        ProductAdditionalCost.objects.create(
            product=product, amount=Decimal("100"), expense_account=account
        )
        # a zero-qty product gets no opening
        Product.objects.create(
            sku="Z", title="Empty", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", is_inventory=True, company=company,
        )

        call_command("seed_stock_opening_movements")
        opening = StockMovement.objects.filter(movement_type="OPENING")
        self.assertEqual(opening.count(), 1)
        mv = opening.get()
        self.assertEqual(mv.signed_quantity, 5)
        self.assertEqual(mv.inventory_cost, Decimal("500"))  # 5 * 100

        call_command("seed_stock_opening_movements")  # idempotent
        self.assertEqual(StockMovement.objects.filter(movement_type="OPENING").count(), 1)
