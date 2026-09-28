"""Seed one OPENING StockMovement per inventory product from current on-hand.

Existing products carry ``quantity`` with no ledger history. This writes the
opening fact the Detail report cumulates from: ``signed_quantity = quantity``,
``rate = latest ProductAdditionalCost.amount``, ``inventory_cost = quantity x rate``.
The report derives running balances in date order, so this OPENING (dated at the
product's date / a fixed go-live date) becomes the base of the perpetual.

Idempotent: a product that already has an OPENING movement is skipped, so it's
safe to re-run. Run once at rollout (and after importing legacy products).

    python manage.py seed_stock_opening_movements [--company <uid>] [--date YYYY-MM-DD]
"""

from datetime import date as date_cls
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from productio.choices import ProductStatusChoices
from productio.models import Product, ProductAdditionalCost

from stockio.choices import StockMovementTypeChoices
from stockio.models import StockMovement


class Command(BaseCommand):
    help = "Seed OPENING stock movements for inventory products from current on-hand."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Limit to a single company uid.")
        parser.add_argument(
            "--date", help="Opening date (YYYY-MM-DD); defaults to each product's date."
        )

    def handle(self, *args, **options):
        opening_date = None
        if options.get("date"):
            opening_date = date_cls.fromisoformat(options["date"])

        products = Product.objects.filter(is_inventory=True).exclude(
            status=ProductStatusChoices.REMOVED
        )
        if options.get("company"):
            products = products.filter(company__uid=options["company"])

        created = skipped = 0
        for product in products.select_related("company").iterator():
            quantity = int(product.quantity or 0)
            if quantity == 0:
                skipped += 1
                continue
            if StockMovement.objects.filter(
                product=product, movement_type=StockMovementTypeChoices.OPENING
            ).exists():
                skipped += 1
                continue

            cost = ProductAdditionalCost.objects.filter(product=product).order_by(
                "created_at"
            ).values_list("amount", flat=True).first() or Decimal("0")
            value = Decimal(quantity) * Decimal(str(cost))

            with transaction.atomic():
                StockMovement.objects.create(
                    company=product.company,
                    product=product,
                    date=opening_date or product.date or date_cls.today(),
                    movement_type=StockMovementTypeChoices.OPENING,
                    signed_quantity=quantity,
                    rate=Decimal(str(cost)),
                    inventory_cost=value,
                    note="Opening balance seeded from on-hand quantity.",
                )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OPENING movements: created {created}, skipped {skipped}."
            )
        )
