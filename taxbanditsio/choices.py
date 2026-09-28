from django.db import models


class TaxBanditsBusinessAccountStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"

class TaxBandits940StatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    TRANSMITTED = "TRANSMITTED", "Transmitted"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    
    
class TaxBandits941StatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    TRANSMITTED = "TRANSMITTED", "Transmitted"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"