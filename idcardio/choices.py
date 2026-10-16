from django.db import models


class PresetChoices(models.TextChoices):
    CR80 = "CR80", "CR80 landscape"
    CR79 = "CR79", "CR79"
    CR100 = "CR100", "CR100"
    BADGE_PORTRAIT = "BADGE_PORTRAIT", "CR80 portrait"
    CUSTOM = "CUSTOM", "Custom"


# ISO/IEC 7810 ID-1 is CR80: the bank-card size every card printer takes.
PRESETS = {
    "CR80": (85.6, 54.0, 3.18),
    "CR79": (83.9, 51.0, 3.18),
    "CR100": (98.5, 67.0, 3.18),
    "BADGE_PORTRAIT": (54.0, 85.6, 3.18),
}


class TemplateStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    ARCHIVED = "ARCHIVED", "Archived"


class CardStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUED = "ISSUED", "Issued"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    REVOKED = "REVOKED", "Revoked"
    LOST = "LOST", "Lost"
    REPLACED = "REPLACED", "Replaced"


LIVE = ("ISSUED", "ACTIVE")


class JobStatusChoices(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    RENDERING = "RENDERING", "Rendering"
    READY = "READY", "Ready"
    PRINTED = "PRINTED", "Printed"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


class SheetChoices(models.TextChoices):
    CARD_DIRECT = "CARD_DIRECT", "Card printer, one card per pass"
    A4 = "A4", "A4 sheet"
    LETTER = "LETTER", "Letter sheet"
    PNG = "PNG", "PNG images"


class DuplexChoices(models.TextChoices):
    NONE = "NONE", "Single-sided"
    LONG_EDGE = "LONG_EDGE", "Long edge"
    SHORT_EDGE = "SHORT_EDGE", "Short edge"


class FieldKindChoices(models.TextChoices):
    TEXT = "TEXT", "Text"
    DATE = "DATE", "Date"
    NUMBER = "NUMBER", "Number"
    ENUM = "ENUM", "Select"
    MULTI = "MULTI", "Multi-select"
    BOOLEAN = "BOOLEAN", "Yes / no"


class AssetKindChoices(models.TextChoices):
    PHOTO = "PHOTO", "Photo"
    SIGNATURE = "SIGNATURE", "Signature"
    LOGO = "LOGO", "Logo"
    BACKGROUND = "BACKGROUND", "Background"


class CardAuditActionChoices(models.TextChoices):
    TEMPLATE_SAVED = "TEMPLATE_SAVED", "Template saved"
    TEMPLATE_VERSIONED = "TEMPLATE_VERSIONED", "New template version"
    TEMPLATE_PUBLISHED = "TEMPLATE_PUBLISHED", "Template published"
    TEMPLATE_ARCHIVED = "TEMPLATE_ARCHIVED", "Template archived"
    CARD_CREATED = "CARD_CREATED", "Card created"
    CARD_ISSUED = "CARD_ISSUED", "Card issued"
    CARD_ACTIVATED = "CARD_ACTIVATED", "Card printed and active"
    CARD_REVOKED = "CARD_REVOKED", "Card revoked"
    CARD_LOST = "CARD_LOST", "Card reported lost"
    CARD_REPLACED = "CARD_REPLACED", "Card replaced"
    PRINT_SUBMITTED = "PRINT_SUBMITTED", "Print job submitted"
    PRINT_COMPLETED = "PRINT_COMPLETED", "Print job rendered"
    PRINT_FAILED = "PRINT_FAILED", "Print job failed"
    PRINT_MARKED = "PRINT_MARKED", "Print job marked printed"
    VERIFY_SCANNED = "VERIFY_SCANNED", "Verification scan"
    VERIFY_THROTTLED = "VERIFY_THROTTLED", "Verification scan refused (rate)"
    PHOTO_REPLACED = "PHOTO_REPLACED", "Photo replaced"
    FIELD_CHANGED = "FIELD_CHANGED", "Custom field changed"
