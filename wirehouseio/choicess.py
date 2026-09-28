from django.db import models

class WarehouseKindChoices(models.TextChoices):
    MAIN = 'MAIN', 'Main'
    TEMPORARY = 'TEMPORARY', 'Temporary'

class WarehouseStatusChoices(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    PENDING = 'PENDING', 'Pending'
    REMOVED = 'REMOVED', 'Removed'
    