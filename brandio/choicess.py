from django.db import models


class BrandKindChoices(models.TextChoices):
    PRODUCT = "PRODUCT", "Product"
    SERVICE = "SERVICE", "Service"
    PROJECT = "PROJECT", "Project"
    EVENT = "EVENT", "Event"


class BrandStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
