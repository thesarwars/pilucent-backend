from django.db import models


class ProductStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class ProductKindChoices(models.TextChoices):
    PRODUCT = "PRODUCT", "Product"
    SERVICE = "SERVICE", "Service"
    PROJECT = "PROJECT", "Project"
    EVENT = "EVENT", "Event"

class ProductBundleStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"

