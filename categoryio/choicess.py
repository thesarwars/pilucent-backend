from django.db import models


class CategoryKindChoices(models.TextChoices):
    PRODUCT = "PRODUCT", "Product"
    SERVICE = "SERVICE", "Service"
    PROJECT = "PROJECT", "Project"
    EVENT = "EVENT", "Event"
    BRAND = "BRAND", "Brand"
    PURCHASE = "PURCHASE", "Purchase"
    PURCHASE_ITEM = "PURCHASE_ITEM", "Purchase Item"
    CREDIT_NOTE_ITEM = "CREDIT_NOTE_ITEM", "Credit Note Item"
    CHART_OF_ACCOUNT = "CHART_OF_ACCOUNT", "Chart of Account"


class CategoryStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
