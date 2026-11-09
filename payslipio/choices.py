"""Payslip and compliance (docs/backend/payslip-compliance-done.md): the document
lifecycle, the finding codes and the permissions."""

from django.db import models

RETENTION_YEARS = 5  # s.123 minimum


class SlipStateChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    BLOCKED = "BLOCKED", "Blocked"
    ISSUABLE = "ISSUABLE", "Issuable"
    ISSUED = "ISSUED", "Issued"
    DELIVERED = "DELIVERED", "Delivered"
    SUPERSEDED = "SUPERSEDED", "Superseded"


S = SlipStateChoices
# §3.2. Past these the figures are fixed; only the moves below remain.
LOCKED = (S.ISSUED, S.DELIVERED, S.SUPERSEDED)
LIVE_ISSUED = (S.ISSUED, S.DELIVERED)
OPEN = (S.DRAFT, S.BLOCKED, S.ISSUABLE)
AFTER_ISSUE = {S.ISSUED: {S.ISSUED, S.DELIVERED, S.SUPERSEDED},
               S.DELIVERED: {S.DELIVERED, S.SUPERSEDED},
               S.SUPERSEDED: {S.SUPERSEDED}}


class LanguageChoices(models.TextChoices):
    EN = "en", "English"
    BN = "bn", "Bangla"


class SeverityChoices(models.TextChoices):
    BLOCK = "BLOCK", "Block"
    WARN = "WARN", "Warn"
    INFO = "INFO", "Info"


class ResolutionChoices(models.TextChoices):
    FIXED_UPSTREAM = "FIXED_UPSTREAM", "Fixed upstream"
    ACCEPTED = "ACCEPTED", "Accepted"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class ChannelChoices(models.TextChoices):
    PORTAL = "PORTAL", "Portal"
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"
    PRINTED = "PRINTED", "Printed"
    HANDED = "HANDED", "Handed over"


class AuditActionChoices(models.TextChoices):
    GENERATED = "GENERATED", "Generated"
    BLOCKED = "BLOCKED", "Blocked"
    FINDING_RESOLVED = "FINDING_RESOLVED", "Finding resolved"
    ISSUED = "ISSUED", "Issued"
    DELIVERED = "DELIVERED", "Delivered"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    VIEWED = "VIEWED", "Viewed"
    PRINTED = "PRINTED", "Printed"
    REGISTER_GENERATED = "REGISTER_GENERATED", "Register generated"


# §7. `release_payslips` is the run payroll permission (app `payrunio`): one
# act, one permission. An employee reading their own issued slip needs none.
PERMISSIONS = (
    ("view_all_payslips", "Can read any employee's payslip"),
    ("generate_payslips", "Can generate payslip drafts"),
    ("resolve_payslip_finding", "Can resolve a payslip compliance finding"),
    ("read_wages_register", "Can read the wages register"),
)
