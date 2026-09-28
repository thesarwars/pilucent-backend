from django.db import models


class CreditNoteStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    CLOSE = "CLOSE", "Close"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class CreditNoteKindChoices(models.TextChoices):
    SALE = "SALE", "Sale"
    PURCHASE = "PURCHASE", "Purchase"


class CreditNoteItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
