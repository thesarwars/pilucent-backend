from django.db import models


class MoovAccountSettingsStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"
    
class MoovAccountBankAccountSettingsStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"
    NEW = "NEW", "New"
    PENDING = "PENDING", "Pending"
    
class MoovBankAccountKindChoices(models.TextChoices):
    SOURCE = "SOURCE", "Source"
    DESTINATION = "DESTINATION", "Destination"
    
    
class MoovTransferStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    CANCELED = "CANCELED", "Canceled"
    RESERVED = "RESERVED", "Reserved"
    REMOVED = "REMOVED", "Removed"