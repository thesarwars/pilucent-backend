"""Give the stock ledger a layer for every lot that predates it.

FIFO is moving from walking `PurchaseItem` rows to reading cost layers off this
ledger. That only works if the ledger knows about the stock a tenant already
holds, and for most of it, it does not: `PURCHASE` movements have only been
written since the ledger was introduced, and nothing ever backfilled the lots
bought before that. Switching without this command would make historical stock
invisible, so the next sale of any older product would fall straight through to
the zero-cost fallback.

    python manage.py backfill_stock_ledger_layers
    python manage.py backfill_stock_ledger_layers --company "Halo Axis"
    python manage.py backfill_stock_ledger_layers --apply

Three jobs, all idempotent -- safe and correct to re-run:

**Seed the missing layers.** A purchase lot with no inbound movement gets one,
sized at what REMAINS on it (`PurchaseItem.quantity`), not at what was
originally bought. That is deliberate and mirrors `seed_stock_opening_movements`:
the sales that consumed the rest happened before the ledger existed, so there is
no honest way to record them, and seeding the original size would hand back
stock that is long gone. Seeding the remainder makes the ledger agree with
reality now, which is the property FIFO needs.

**Link the consumption that already happened.** Rows written since the ledger
started name a `purchase_item` but not the movement it came from, so a layer
cannot tell what has been taken off it. Those are linked to their lot's inbound
movement -- but only where that movement was genuinely recorded at purchase
time. A layer this command seeded is already sized at the remainder, so linking
its consumption too would subtract the same units twice.

**Reconcile the openings.** `seed_stock_opening_movements` sized each OPENING at
`product.quantity` -- ALL stock on hand, including units that arrived through a
purchase. Seeding those lots as layers therefore counts the same units twice, so
the opening is reduced to whatever the lots do not already explain. The lots are
the better record: they carry the price actually paid, where an opening carries a
reconstruction of it.

That step also repairs a run of this command from before it existed, which is why
re-running is worth doing even where it reports nothing left to seed.

Dry run by default. Run it before deploying the FIFO switch, not after.
"""

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from companyio.models import Company

from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import PurchaseItem

from stockio.choices import StockMovementTypeChoices
from stockio.models import StockMovement, StockMovementLayerConsumption

# Mirrors the filter `fifo_product_deduction` uses, so this seeds exactly the
# lots FIFO would have consumed and nothing else.
LAYER_STATUSES = [
    PurchaseStatus.OPEN,
    PurchaseStatus.ACCEPTED,
    PurchaseStatus.CLOSED,
    PurchaseStatus.COMPLETED,
]


class Command(BaseCommand):
    help = "Seed stock-ledger layers for purchase lots that predate the ledger."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--apply", action="store_true", help="Write. Without it, dry run."
        )
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        companies = Company.objects.all().order_by("id")
        if options["company"]:
            needle = options["company"]
            companies = (
                companies.filter(id=needle)
                if str(needle).isdigit()
                else companies.filter(name__icontains=needle)
            )
        if not companies.exists():
            self.stderr.write(self.style.ERROR("No company matches."))
            return

        lots = (
            PurchaseItem.objects.filter(
                status=PurchaseItemStatus.PUBLISHED,
                purchase__status__in=LAYER_STATUSES,
                purchase__company__in=companies,
                product__isnull=False,
            )
            .filter(
                Q(purchase__is_bill=True)
                | Q(purchase__is_cheque=True)
                | Q(purchase__is_via_expense=True)
            )
            .select_related("purchase", "product", "purchase__company")
            .order_by("created_at", "id")
        )

        with_movement = set(
            StockMovement.objects.filter(
                purchase_item__isnull=False,
                movement_type=StockMovementTypeChoices.PURCHASE,
            ).values_list("purchase_item_id", flat=True)
        )

        to_seed = [lot for lot in lots if lot.pk not in with_movement]
        seedable = [lot for lot in to_seed if int(lot.quantity or 0) > 0]
        empty = len(to_seed) - len(seedable)

        unlinked = StockMovementLayerConsumption.objects.filter(
            source_movement__isnull=True,
            purchase_item__isnull=False,
            purchase_item__in=with_movement,
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Stock ledger layer backfill -- {companies.count()} company(ies)"
            )
        )
        self.stdout.write(f"  lots that are FIFO layers   : {lots.count()}")
        self.stdout.write(f"  already in the ledger       : {lots.count() - len(to_seed)}")
        self.stdout.write(f"  to seed (stock remaining)   : {len(seedable)}")
        self.stdout.write(f"  exhausted, nothing to seed  : {empty}")
        self.stdout.write(f"  consumption rows to link    : {unlinked.count()}")
        self.stdout.write("")

        by_company = defaultdict(int)
        for lot in seedable:
            by_company[lot.purchase.company.name] += 1
        for name, count in list(by_company.items())[: options["limit"]]:
            self.stdout.write(f"    {name[:34]:<36} {count} lot(s)")
        if len(by_company) > options["limit"]:
            self.stdout.write(f"    ... {len(by_company) - options['limit']} more")
        self.stdout.write("")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run -- nothing changed. Re-run with --apply.\n"
                    "Run this BEFORE deploying the ledger-sourced FIFO switch: "
                    "until it has, older lots are invisible to the ledger and "
                    "would sell at a zero fallback cost."
                )
            )
            return

        seeded = 0
        with transaction.atomic():
            for lot in seedable:
                remaining = int(lot.quantity or 0)
                price = Decimal(str(lot.purchase_price or 0))
                StockMovement.objects.create(
                    company=lot.purchase.company,
                    product=lot.product,
                    date=lot.purchase.date or lot.purchase.bill_date,
                    movement_type=StockMovementTypeChoices.PURCHASE,
                    signed_quantity=remaining,
                    rate=price,
                    inventory_cost=Decimal(remaining) * price,
                    purchase_item=lot,
                    note=(
                        "Layer reconstructed from the remaining lot quantity; "
                        "consumption before the ledger existed is not itemised."
                    ),
                )
                seeded += 1

        linked = 0
        with transaction.atomic():
            for row in unlinked.select_related("purchase_item"):
                movement = (
                    StockMovement.objects.filter(
                        purchase_item=row.purchase_item,
                        movement_type=StockMovementTypeChoices.PURCHASE,
                    )
                    .order_by("date", "id")
                    .first()
                )
                if movement is None:
                    continue
                row.source_movement = movement
                row.save(update_fields=["source_movement"])
                linked += 1

        trimmed, reclaimed = self.reconcile_openings(companies)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {seeded} layer(s); linked {linked} consumption row(s); "
                f"trimmed {trimmed} opening balance(s) by {reclaimed} unit(s)."
            )
        )
        self.verify(companies)

    def reconcile_openings(self, companies):
        """Shrink synthetic openings by whatever the lot layers now account for.

        `seed_stock_opening_movements` sized each OPENING at `product.quantity`
        -- ALL stock on hand, including units that arrived through a purchase.
        Seeding those purchase lots as layers therefore counts the same units
        twice, and FIFO then believes there is more stock than exists.

        The lots are the better record of the two: they carry the price actually
        paid, where the opening carries a reconstruction. So the opening gives
        way -- it is reduced to whatever the lots do not already explain, which
        for a product whose stock is entirely purchased is nothing at all.

        Amending the row rather than posting a compensating movement is
        deliberate here, and the exception to this ledger being append-only: an
        opening seeded from on-hand is not a recorded event, it is an estimate
        of one, and correcting the estimate should not look like stock leaving
        the building.
        """
        from productio.models import Product

        from stockio.django_rest.services.stock_movement import ledger_layers

        trimmed = reclaimed = 0
        products = Product.objects.filter(company__in=companies)
        for product in products.iterator():
            on_hand = int(product.quantity or 0)
            layers = ledger_layers(product)
            total = sum(int(q) for _m, q, _c in layers)
            excess = total - on_hand
            if excess <= 0:
                continue

            opening = next(
                (
                    movement
                    for movement, _q, _c in layers
                    if movement.movement_type == StockMovementTypeChoices.OPENING
                ),
                None,
            )
            if opening is None:
                continue

            consumed = sum(
                Decimal(str(row.quantity_consumed or 0))
                for row in StockMovementLayerConsumption.objects.filter(
                    source_movement=opening
                )
            )
            # Never below what has already been taken off it, or the layer would
            # read negative rather than empty.
            floor = int(consumed)
            new_size = max(opening.signed_quantity - excess, floor)
            if new_size == opening.signed_quantity:
                continue

            rate = Decimal(str(opening.rate or 0))
            opening.signed_quantity = new_size
            opening.inventory_cost = Decimal(new_size) * rate
            opening.note = (
                "Opening balance seeded from on-hand quantity, then reduced by "
                "the purchase lots that account for the same stock."
            )
            opening.save(
                update_fields=["signed_quantity", "inventory_cost", "note"]
            )
            trimmed += 1
            reclaimed += excess
        return trimmed, reclaimed

    def verify(self, companies):
        """Report products whose ledger layers do not total their on-hand.

        Compared against `Product.quantity`, not against the purchase lots. The
        first version of this check compared layers to lots, which is not a
        property that should hold: opening stock is a legitimate layer and no
        lot corresponds to it, so it reported every such product as a
        disagreement and buried the real one.
        """
        from productio.models import Product

        from stockio.django_rest.services.stock_movement import ledger_layers

        drift = []
        products = Product.objects.filter(company__in=companies).select_related(
            "company"
        )
        for product in products.iterator():
            on_hand = int(product.quantity or 0)
            total = sum(int(q) for _m, q, _c in ledger_layers(product))
            if total != on_hand:
                drift.append((product, on_hand, total))

        self.stdout.write("")
        if not drift:
            self.stdout.write(
                self.style.SUCCESS(
                    "Every product's cost layers total its on-hand quantity."
                )
            )
            return
        over = [d for d in drift if d[2] > d[1]]
        under = [d for d in drift if d[2] < d[1]]
        self.stdout.write(
            self.style.WARNING(
                f"{len(drift)} product(s) where layers do not match on-hand "
                f"({len(over)} over, {len(under)} under):"
            )
        )
        for product, on_hand, total in drift[:25]:
            self.stdout.write(
                f"  {product.company.name[:22]:<24} {product.title[:28]:<30} "
                f"on_hand={on_hand} layers={total}"
            )
        if over:
            self.stdout.write(
                "\n  Over-stated layers mean FIFO will relieve stock that does "
                "not exist. Under-stated means it will fall to the zero-cost "
                "fallback sooner than it should."
            )
