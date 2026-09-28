from django.db import models


class NexusCombinationLogicChoices(models.TextChoices):
    SALES_ONLY = "SALES_ONLY", "Sales only"
    OR = "OR", "Sales or transactions"
    AND = "AND", "Sales and transactions"
    NONE = "NONE", "No sales tax"  # states without a statewide sales tax


class NexusIncludableSalesBasisChoices(models.TextChoices):
    GROSS = "GROSS", "Gross"  # all sales, incl. exempt + resale
    RETAIL = "RETAIL", "Retail"  # excludes sales for resale
    TAXABLE = "TAXABLE", "Taxable"  # taxable sales only


class NexusMeasurementPeriodChoices(models.TextChoices):
    CURRENT_YEAR = "CURRENT_YEAR", "Current calendar year"
    PREVIOUS_YEAR = "PREVIOUS_YEAR", "Previous calendar year"
    CURRENT_OR_PREVIOUS_YEAR = "CURRENT_OR_PREVIOUS_YEAR", "Current or previous year"
    TRAILING_12M = "TRAILING_12M", "Trailing 12 months"


class NexusStatusChoices(models.TextChoices):
    NOT_APPROACHING = "NOT_APPROACHING", "Not approaching"
    APPROACHING = "APPROACHING", "Approaching"
    MET = "MET", "Threshold met"
    REGISTERED = "REGISTERED", "Registered"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"


class NexusRegistrationTypeChoices(models.TextChoices):
    ECONOMIC = "ECONOMIC", "Economic nexus"
    PHYSICAL_MANUAL = "PHYSICAL_MANUAL", "Physical presence (manual)"


class NexusRegistrationStatusChoices(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    REGISTERED = "REGISTERED", "Registered"


class NexusFilingFrequencyChoices(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    ANNUAL = "ANNUAL", "Annual"


class NexusAlertTypeChoices(models.TextChoices):
    APPROACHING = "APPROACHING", "Approaching"
    CROSSED = "CROSSED", "Crossed"
