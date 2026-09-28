from django.db import models


class InvoiceStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    OPEN = "OPEN", "Open"
    ACCEPTED = "ACCEPTED", "Accepted"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"


