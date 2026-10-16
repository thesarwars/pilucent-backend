"""Employee ID cards (docs/backend/id-cards-done.md).

Millimetres and points are the unit of record; pixels never reach the
database. A template version is immutable once a card prints from it. A
card is a document with a lifecycle -- revoked, lost, replaced, never
deleted -- and pins its template version and the values bound at issue, so
a card printed in 2026 reproduces in 2031.

Tenancy: every table carries `company`, and every read filters on it.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from common.models import BaseModelWithUID

from .choices import (
    AssetKindChoices,
    CardAuditActionChoices,
    CardStatusChoices,
    DuplexChoices,
    FieldKindChoices,
    JobStatusChoices,
    PresetChoices,
    SheetChoices,
    TemplateStatusChoices,
)

MM = dict(max_digits=8, decimal_places=3)


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user(**kwargs):
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                             **kwargs)


# ------------------------------------------------------------------ settings


class CardSettings(BaseModelWithUID):
    """What a card says about the employer, and how cards are numbered."""

    company = models.OneToOneField("companyio.Company", on_delete=models.CASCADE, related_name="card_settings")
    name_bn = _text()
    address = models.TextField(blank=True, default="")
    signatory_title = _text(120)
    number_prefix = models.CharField(max_length=10, default="ID")
    validity_years = models.PositiveSmallIntegerField(default=3)
    # A photo outliving the employment record is a liability (§3.8): kept this
    # long after separation, then purged.
    photo_retention_days = models.PositiveSmallIntegerField(default=365)


# ------------------------------------------------------------------ template


class CardTemplate(BaseModelWithUID):
    """§3.1. One row per version. Once a card prints from a version it is
    locked; an edit makes version n+1, so a reprint reproduces the original."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="card_templates")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    name_bn = _text(120)
    description = _text()
    version = models.PositiveIntegerField(default=1)

    preset = models.CharField(max_length=16, choices=PresetChoices.choices)
    width_mm = models.DecimalField(**MM)
    height_mm = models.DecimalField(**MM)
    corner_radius_mm = models.DecimalField(**MM, default=3.18)
    bleed_mm = models.DecimalField(**MM, default=2)
    safe_area_mm = models.DecimalField(**MM, default=3)

    front_json = models.JSONField()
    back_json = models.JSONField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=TemplateStatusChoices.choices,
                              default=TemplateStatusChoices.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = _user()
    published_by_name = _text()
    # Errors acknowledged at publish, and who acknowledged them (§5.2).
    publish_findings = models.JSONField(null=True, blank=True)
    locked = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("code", "-version")
        constraints = [
            models.UniqueConstraint(fields=["company", "code", "version"], name="idcardio_template_version"),
            models.CheckConstraint(condition=Q(width_mm__gt=0, height_mm__gt=0),
                                   name="idcardio_template_dimensions_positive"),
            models.CheckConstraint(condition=Q(corner_radius_mm__lte=F("width_mm") / 2)
                                   & Q(corner_radius_mm__lte=F("height_mm") / 2), name="idcardio_template_radius_fits"),
        ]
        indexes = [models.Index(fields=["company", "code", "status"], name="idcardio_template_published")]

    def __str__(self):
        return f"{self.code} v{self.version}"


class ResolutionRule(BaseModelWithUID):
    """Which template an employee gets: the first enabled rule that matches,
    by priority, else the default template."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    priority = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=160)
    template_code = models.SlugField(max_length=40)
    condition = models.JSONField()  # {op, path, value}
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ("priority", "id")


# --------------------------------------------------------------------- media


class MediaAsset(BaseModelWithUID):
    """§3.8. An employee photo is personal data with a retention clock. The
    original is kept; crop and adjustments are parameters, not a new file."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="card_assets")
    kind = models.CharField(max_length=12, choices=AssetKindChoices.choices)
    file = models.FileField(upload_to="idcards/assets", max_length=255)
    mime_type = models.CharField(max_length=60)
    pixel_width = models.PositiveIntegerField()
    pixel_height = models.PositiveIntegerField()
    bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    # Crop in source pixels {x, y, w, h}, and {brightness, contrast, saturation} in -100..100.
    crop = models.JSONField(null=True, blank=True)
    adjustments = models.JSONField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    is_pii = models.BooleanField(default=True)
    retain_until = models.DateField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = _user()
    uploaded_by_name = _text()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["employee", "kind"], name="idcardio_asset_employee")]
        constraints = [
            models.CheckConstraint(condition=Q(pixel_width__gt=0, pixel_height__gt=0),
                                   name="idcardio_asset_dimensions_positive"),
            models.UniqueConstraint(fields=["employee", "kind"], condition=Q(is_current=True, employee__isnull=False),
                                    name="idcardio_one_current_asset"),
        ]

    @property
    def placed_size(self):
        """Pixels after the crop: what the DPI check divides."""
        c = self.crop or {}
        return int(c.get("w") or self.pixel_width), int(c.get("h") or self.pixel_height)


# ------------------------------------------------------------- custom fields


class CardField(BaseModelWithUID):
    """§3.6. Beyond the employee record. `verify_visible` defaults to off: a
    field is deliberately opted in before it appears on the public page."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="card_fields")
    key = models.SlugField(max_length=40)
    label = models.CharField(max_length=80)
    label_bn = _text(80)
    kind = models.CharField(max_length=10, choices=FieldKindChoices.choices)
    enum_options = models.JSONField(default=list, blank=True)
    group_name = models.CharField(max_length=40, default="Custom fields")
    help = _text()
    required = models.BooleanField(default=False)
    is_pii = models.BooleanField(default=False)
    printable = models.BooleanField(default=True)
    verify_visible = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="idcardio_field_key_unique"),
            # Personal data never prints and never reaches the public page.
            models.CheckConstraint(condition=Q(is_pii=False) | Q(printable=False, verify_visible=False),
                                   name="idcardio_pii_never_printed"),
        ]

    @property
    def path(self):
        return f"custom.{self.key}"


class CardFieldValue(BaseModelWithUID):
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    field = models.ForeignKey(CardField, on_delete=models.CASCADE, related_name="values")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="card_field_values")
    value = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["field", "employee"], name="idcardio_field_value_once")]


# ------------------------------------------------------------ output profile


class OutputProfile(BaseModelWithUID):
    """§3.7. A card printer takes one card a pass; a sheet is guillotined,
    which is what crop marks are for; `mirror` is for retransfer printers."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="card_output_profiles")
    name = models.CharField(max_length=80)
    note = _text()
    sheet = models.CharField(max_length=12, choices=SheetChoices.choices)
    cols = models.PositiveSmallIntegerField(default=1)
    rows = models.PositiveSmallIntegerField(default=1)
    gutter_mm = models.DecimalField(**MM, default=0)
    margin_mm = models.DecimalField(**MM, default=0)
    include_bleed = models.BooleanField(default=False)
    crop_marks = models.BooleanField(default=False)
    duplex = models.CharField(max_length=10, choices=DuplexChoices.choices, default=DuplexChoices.NONE)
    colour_profile = models.CharField(max_length=40, default="sRGB")
    dpi = models.PositiveSmallIntegerField(default=300)
    mirror = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_default", "name")
        constraints = [
            models.CheckConstraint(condition=Q(dpi__gte=150, dpi__lte=1200), name="idcardio_profile_dpi_sane"),
            models.CheckConstraint(condition=Q(cols__gte=1, rows__gte=1), name="idcardio_profile_grid"),
        ]

    @property
    def cards_per_sheet(self):
        return 1 if self.sheet in ("CARD_DIRECT", "PNG") else self.cols * self.rows


# ---------------------------------------------------------------------- card


class Card(BaseModelWithUID):
    """§3.4. `data_snapshot` is the point of the table: the values bound at
    issue. A designation change does not change the card in a pocket."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="id_cards")
    card_number = models.CharField(max_length=30)
    template = models.ForeignKey(CardTemplate, on_delete=models.PROTECT, related_name="cards")
    template_version = models.PositiveIntegerField()
    data_snapshot = models.JSONField()
    photo_asset = models.ForeignKey(MediaAsset, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    status = models.CharField(max_length=10, choices=CardStatusChoices.choices, default=CardStatusChoices.DRAFT)
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    issued_by = _user()
    issued_by_name = _text()

    revoked_on = models.DateField(null=True, blank=True)
    revoked_by = _user()
    revoked_by_name = _text()
    revoke_reason = models.TextField(blank=True, default="")
    replaced_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="replaces")

    verify_token = models.CharField(max_length=32)
    print_count = models.PositiveIntegerField(default=0)
    last_printed_at = models.DateTimeField(null=True, blank=True)
    last_printed_by_name = _text()
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["employee", "status"], name="idcardio_card_employee")]
        constraints = [
            models.UniqueConstraint(fields=["company", "card_number"], name="idcardio_card_number_unique"),
            models.UniqueConstraint(fields=["verify_token"], name="idcardio_verify_token_unique"),
            # One live card per employee: a replacement moves the old one first.
            models.UniqueConstraint(fields=["employee"], condition=Q(status__in=["ISSUED", "ACTIVE"]),
                                    name="idcardio_one_active_card"),
            models.CheckConstraint(condition=~Q(status__in=["REVOKED", "LOST"]) | ~Q(revoke_reason=""),
                                   name="idcardio_revoke_needs_reason"),
            models.CheckConstraint(condition=Q(expires_on__isnull=True) | Q(issued_on__isnull=True)
                                   | Q(expires_on__gt=F("issued_on")), name="idcardio_expiry_after_issue"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("A card is never deleted: revoke it, with a reason.")


# ----------------------------------------------------------------- print job


class PrintJob(BaseModelWithUID):
    """§3.5. `preflight_json` is the snapshot taken at submission: a job that
    printed wrong is examined against what was checked, not against the
    template as it stands today."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)
    name = _text(120)
    output_profile = models.ForeignKey(OutputProfile, on_delete=models.PROTECT, related_name="jobs")
    profile_snapshot = models.JSONField()
    cards = models.ManyToManyField(Card, related_name="print_jobs")
    card_count = models.PositiveIntegerField()
    skipped = models.JSONField(default=list)  # [{code, card, why}]
    status = models.CharField(max_length=10, choices=JobStatusChoices.choices, default=JobStatusChoices.QUEUED)
    preflight_json = models.JSONField()
    preflight_errors = models.PositiveIntegerField(default=0)
    include_warnings = models.BooleanField(default=False)
    artifact = models.FileField(upload_to="idcards/print", max_length=255, null=True, blank=True)
    artifact_sha256 = _text(64)
    artifact_pages = models.PositiveIntegerField(default=0)
    submitted_by = _user()
    submitted_by_name = _text()
    completed_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="idcardio_job_reference"),
            # The database refusing to let a job with errors reach a printer.
            models.CheckConstraint(condition=~Q(status__in=["READY", "PRINTED"]) | Q(preflight_errors=0),
                                   name="idcardio_no_errors_when_ready"),
        ]


# -------------------------------------------------------------------- events


class CardEvent(BaseModelWithUID):
    """§9, as an outbox: written in the transaction that caused it.
    CardRevoked is the one access control must read at once -- a revoked
    card that still opens a door for an hour is the failure the lifecycle
    exists to prevent."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=30)
    card = models.ForeignKey(Card, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")


# --------------------------------------------------------------------- audit


class CardAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("The card audit is append-only.")

    def delete(self):
        raise ValidationError("The card audit is append-only.")


class CardAudit(BaseModelWithUID):
    """§3.9. A verification scan is recorded with the IP and no actor: fifty
    scans an hour from one address is a gate or an attack, and the log is
    what tells them apart."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    card = models.ForeignKey(Card, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit")
    template = models.ForeignKey(CardTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    job = models.ForeignKey(PrintJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=24, choices=CardAuditActionChoices.choices)
    actor = _user()
    actor_name = _text()
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    objects = CardAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["card", "created_at"], name="idcardio_audit_card")]
        # §6. Override differs from print; field management is a privacy permission.
        permissions = [
            ("issue_cards", "Can create and issue ID cards"),
            ("revoke_cards", "Can revoke, report lost and replace ID cards"),
            ("edit_card_templates", "Can design ID card templates"),
            ("publish_card_templates", "Can publish an ID card template version"),
            ("print_cards", "Can submit ID card print jobs"),
            ("override_card_print", "Can print ID cards that carry warnings"),
            ("manage_card_photos", "Can upload, crop and replace ID card photos"),
            ("manage_card_fields", "Can manage ID card custom fields and what the verification page shows"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The card audit is append-only.")
        super().save(*args, **kwargs)
