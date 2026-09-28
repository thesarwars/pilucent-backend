from django.db import models


class SupplierkindChoices(models.TextChoices):
    PURCHASE = "PURCHASE", "Purchase"
    UN_CATEGORISED_EXPENSE = "UN_CATEGORISED_EXPENSE", "Un Categorised Expense"
    COST_OF_SELL = "COST_OF_SELL", "Cost Of Sell"


class SupplierStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
