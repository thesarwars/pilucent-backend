from django.db import models


class TermStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "Inactive"
    PENDING = "PENDING", "Pending"
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"


class TermKindChoices(models.TextChoices):
    PAYMENT = "PAYMENT", "Payment"
    CUSTOMER = "CUSTOMER", "Customer"
    SUPPLIER = "SUPPLIER", "Supplier"
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
