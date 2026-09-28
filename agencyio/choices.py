from django.db import models


class AgencyFillingFrequencyChoices(models.TextChoices):
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    ANNUALLY = "ANNUALLY", "Annually"


class AgencyStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"


class AgencyReportingMethod(models.TextChoices):
    ACCRUAL = "ACCRUAL", "Accrual"
    CASH = "CASH", "Cash"


class AgencyStartOfPeriodChoices(models.TextChoices):
    JANUARY = "January", "January"
    FEBRUARY = "February", "February"
    MARCH = "March", "March"
    APRIL = "April", "April"
    MAY = "May", "May"
    JUNE = "June", "June"
    JULY = "July", "July"
    AUGUST = "August", "August"
    SEPTEMBER = "September", "September"
    OCTOBER = "October", "October"
    NOVEMBER = "November", "November"
    DECEMBER = "December", "December"


