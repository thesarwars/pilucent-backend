from autoslug import AutoSlugField

from datetime import date

from django.db import models

from common.models import BaseModelWithUID
from journalio.models import JournalEntry, JournalEntryConnector

from .choices import (
    StockAlertStatusChoices,
    StockAdjustmentStatusChoices,
    StockAdjustmentItemStatusChoices,
    StockAdjustmentItemKindChoices,
    StockMovementTypeChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_stock_alert_slug,
    get_stock_adjustment_slug,
)
from .managers import (
    StockAlertQuerySet,
    StockAdjustmentQuerySet,
    StockAdjustmentItemQuerySet,
)


class StockAlert(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_stock_alert_slug, unique=True, db_index=True)
    status = models.CharField(
        choices=StockAlertStatusChoices,
        default=StockAlertStatusChoices.DRAFT,
        max_length=50,
    )
    quantity = models.PositiveIntegerField()
    description = models.TextField(blank=True, null=True)
    is_expired_date = models.BooleanField(default=False)
    before_expired_day = models.PositiveIntegerField(blank=True, null=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = StockAlertQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Quantity: {self.quantity}"


class StockAdjustment(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_stock_adjustment_slug, unique=True, db_index=True
    )
    status = models.CharField(
        choices=StockAdjustmentStatusChoices,
        default=StockAdjustmentStatusChoices.DRAFT,
        max_length=50,
    )
    date = models.DateField(default=date.today)
    reference_number = models.CharField(
        blank=True, null=True, unique=True, max_length=50
    )
    reason = models.CharField(blank=True, null=True, max_length=100)
    description = models.TextField(blank=True, null=True)

    # FK
    stock_adjustment_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = StockAdjustmentQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, status: {self.status}"

    def get_sub_total(self):
        total = 0
        for item in self.stockadjustmentitem_set.all():
            purchase_item = item.product.purchaseitem_set.first()
            if purchase_item:
                price = purchase_item.purchase_price
            else:
                selected_product = item.product.productadditionalcost_set.first()
                price = selected_product.amount
            total = price * item.quantity
        return total

    # def get_stock_adjustment_account_total(self):
    #     return self.stock_adjustment_account.opening_balance + self.get_sub_total()

    def get_journal__account_last_balance(self):

        journal_entry = JournalEntry.objects.filter(
            stock_adjustment=self, company=self.company
        ).order_by("id").first()
        if journal_entry:
            return JournalEntryConnector.objects.filter(
                journal=journal_entry, account=self.stock_adjustment_account
            ).first()
        return None


class StockAdjustmentItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_stock_adjustment_slug, unique=True, db_index=True
    )
    status = models.CharField(
        choices=StockAdjustmentItemStatusChoices,
        default=StockAdjustmentItemStatusChoices.DRAFT,
        max_length=50,
    )
    kind = models.CharField(
        choices=StockAdjustmentItemKindChoices,
        default=StockAdjustmentItemKindChoices.ADDITION,
        max_length=50,
    )
    description = models.TextField(blank=True, null=True)
    quantity = models.PositiveIntegerField()
    # Removed purchase_price field

    # FK
    stock_adjustment = models.ForeignKey(StockAdjustment, on_delete=models.CASCADE)
    product = models.ForeignKey("productio.Product", on_delete=models.CASCADE)
    objects = StockAdjustmentItemQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, status: {self.status}"


class StockMovement(BaseModelWithUID):
    """Append-only ledger of every inventory movement for a product.

    One row per stock event (purchase/sale/return/adjustment/opening). Stores the
    immutable *facts* of the movement — signed quantity, rate, and signed
    inventory cost (COGS on outbound). Running quantity-on-hand and asset value
    are **derived at read time** by cumulating these in date order (see the
    Inventory Valuation Detail report), so they are always correct regardless of
    the order rows were entered — a backdated document simply sorts into place.

    Rows are never mutated or deleted — a corrected transaction records a
    compensating REVERSAL movement. The source-line FKs are ``SET_NULL`` so the
    ledger survives deletion of the originating document.
    """

    date = models.DateField(db_index=True)
    movement_type = models.CharField(
        max_length=20, choices=StockMovementTypeChoices.choices
    )
    signed_quantity = models.IntegerField()  # + inbound, - outbound
    rate = models.DecimalField(
        max_digits=19, decimal_places=3, blank=True, null=True
    )  # unit price on the source line
    inventory_cost = models.DecimalField(
        max_digits=19, decimal_places=3, default=0
    )  # signed cost impact; COGS on outbound
    note = models.CharField(max_length=255, blank=True, null=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    product = models.ForeignKey("productio.Product", on_delete=models.CASCADE)
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.SET_NULL, blank=True, null=True
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, blank=True, null=True
    )
    # Originating document line (SET_NULL so the ledger outlives the source).
    purchase_item = models.ForeignKey(
        "purchaseio.PurchaseItem", on_delete=models.SET_NULL, blank=True, null=True
    )
    sale_item = models.ForeignKey(
        "salesio.SaleItem", on_delete=models.SET_NULL, blank=True, null=True
    )
    credit_note_item = models.ForeignKey(
        "creditnoteio.CreditNoteItem", on_delete=models.SET_NULL, blank=True, null=True
    )
    stock_adjustment_item = models.ForeignKey(
        StockAdjustmentItem, on_delete=models.SET_NULL, blank=True, null=True
    )

    class Meta:
        ordering = ("date", "created_at", "id")
        indexes = [
            models.Index(fields=["company", "product", "date"]),
        ]

    def __str__(self):
        return (
            f"ID: {self.id}, {self.movement_type} {self.signed_quantity} "
            f"of product {self.product_id} @ {self.date}"
        )


class StockMovementLayerConsumption(BaseModelWithUID):
    """One lot slice an outbound movement consumed (true FIFO detail).

    Persists the consumed quantity per purchase lot — the column the journal
    never stored — so per-line COGS is attributable even for zero-price or
    layer-exhausted (fallback) units.
    """

    quantity_consumed = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    cost_amount = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    is_fallback = models.BooleanField(default=False)  # layers exhausted, no lot

    # The INBOUND movement this slice drew from.
    #
    # Consumption was attributed only to a `purchase_item`, which makes a
    # purchase the sole thing that can be a cost layer. It is not: opening
    # stock, a customer return and a positive adjustment all add costed units,
    # and none of them is a purchase. Naming the source movement instead lets a
    # layer be any inbound row in this ledger, so what remains on a layer is
    # derivable -- its signed quantity less everything consumed against it --
    # rather than being held in `PurchaseItem.quantity`, a mutable column on a
    # document.
    #
    # Nullable: rows written before this column existed have no source, and a
    # fallback slice never had one.
    source_movement = models.ForeignKey(
        "StockMovement",
        on_delete=models.SET_NULL,
        related_name="consumed_by",
        blank=True,
        null=True,
    )

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    movement = models.ForeignKey(
        StockMovement, on_delete=models.CASCADE, related_name="layer_consumptions"
    )
    purchase_item = models.ForeignKey(
        "purchaseio.PurchaseItem", on_delete=models.SET_NULL, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, {self.quantity_consumed} @ {self.unit_cost}"
