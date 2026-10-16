from django.db import models


class FormatChoices(models.TextChoices):
    CSV = "CSV", "CSV"
    TSV = "TSV", "TSV"
    FIXED = "FIXED", "Fixed width"
    XLSX = "XLSX", "Excel workbook"
    CUSTOM = "CUSTOM", "Custom"


class EncodingChoices(models.TextChoices):
    UTF8 = "UTF-8", "UTF-8"
    UTF16 = "UTF-16", "UTF-16"
    CP1252 = "Windows-1252", "Windows-1252"


class RowStructureChoices(models.TextChoices):
    EVENT_LOG = "EVENT_LOG", "Event log — one row per punch"
    PAIRED_COLUMNS = "PAIRED_COLUMNS", "Paired columns — in and out on one row"


class DirectionHandlingChoices(models.TextChoices):
    EXPLICIT_COLUMN = "EXPLICIT_COLUMN", "Explicit column"
    ALTERNATE = "ALTERNATE", "Alternate — odd in, even out"
    FIRST_LAST = "FIRST_LAST", "First and last of day"
    PAIRED = "PAIRED", "Paired columns"


class MatchingChoices(models.TextChoices):
    DEVICE_ID_MAP = "DEVICE_ID_MAP", "Device ID map"
    EMPLOYEE_CODE = "EMPLOYEE_CODE", "Employee code"
    NID = "NID", "NID"


class BatchStatusChoices(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
    PARSED = "PARSED", "Parsed"
    VALIDATED = "VALIDATED", "Validated"
    PROCESSING = "PROCESSING", "Processing"
    PROCESSED = "PROCESSED", "Processed"
    FAILED = "FAILED", "Failed"
    REVERSED = "REVERSED", "Reversed"


class PunchStateChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ORPHAN = "ORPHAN", "Held for a mapping"
    SKIPPED = "SKIPPED", "Skipped"
    REVERSED = "REVERSED", "Reversed"


class IntakeAuditActionChoices(models.TextChoices):
    BATCH_UPLOADED = "BATCH_UPLOADED", "File uploaded"
    BATCH_PARSED = "BATCH_PARSED", "File parsed"
    BATCH_VALIDATED = "BATCH_VALIDATED", "Import validated"
    BATCH_PROCESSED = "BATCH_PROCESSED", "Import processed"
    BATCH_REVERSED = "BATCH_REVERSED", "Import reversed"
    MAPPING_CREATED = "MAPPING_CREATED", "Device ID mapped"
    MAPPING_CLOSED = "MAPPING_CLOSED", "Device ID mapping closed"
    PERIOD_ADVANCED = "PERIOD_ADVANCED", "Period advanced"
    PERIOD_LOCKED = "PERIOD_LOCKED", "Period locked"
    PERIOD_UNLOCKED = "PERIOD_UNLOCKED", "Period unlocked"
    PROFILE_PUBLISHED = "PROFILE_PUBLISHED", "Device profile saved"
