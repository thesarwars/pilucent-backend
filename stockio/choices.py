from django.db import models


class StockAlertStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class StockAdjustmentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class StockAdjustmentItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class StockAdjustmentItemKindChoices(models.TextChoices):
    ADDITION = "ADDITION", "Addition"
    DEDUCTION = "DEDUCTION", "Deduction"


class StockMovementTypeChoices(models.TextChoices):
    OPENING = "OPENING", "Opening balance"
    PURCHASE = "PURCHASE", "Purchase"
    PURCHASE_RETURN = "PURCHASE_RETURN", "Purchase return"
    SALE = "SALE", "Sale"
    SALE_RETURN = "SALE_RETURN", "Sale return"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment (in)"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment (out)"
    REVERSAL = "REVERSAL", "Reversal"
