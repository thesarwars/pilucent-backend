from django.db import models


class AttachmentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
