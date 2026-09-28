from django.db import models


class CompanyRoleKindChoices(models.TextChoices):
    USER = "USER", "User"
    EMPLOYEE = "EMPLOYEE", "Employee"


class CompanyRoleStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"
