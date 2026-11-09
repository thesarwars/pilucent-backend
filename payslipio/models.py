"""Payslip and compliance (docs/backend/payslip-compliance-done.md).

- A payslip is a stored document, built from its run line. Once issued only
  its state, its link to a correction and its retention (extended, never
  shortened) still move (§3.2).
- The wages register is written from issued slips, never recomputed (§3.6).

The triggers are Postgres guards in migration 0002; the models enforce the
same for the test database.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan

from common.models import BaseModelWithUID
from payrunio.models import AppendOnly

from .choices import (
    AFTER_ISSUE,
    LIVE_ISSUED,
    LOCKED,
    PERMISSIONS,
    AuditActionChoices,
    ChannelChoices,
    LanguageChoices,
    ResolutionChoices,
    SeverityChoices,
    SlipStateChoices,
)

MONEY = {"max_digits": 18, "decimal_places": 4}
# §3.2: everything else is frozen at issue.
MUTABLE_AFTER_ISSUE = {"state", "superseded_by_id", "retention_until", "updated_at"}


def _money(**kwargs):
    return models.DecimalField(**MONEY, **kwargs)


def _refuse_shorter(old, new, what="Retention"):
    if old is not None and (new is None or new < old):
        raise ValidationError(f"{what} runs to {old} and cannot be shortened to {new}.")


class PayslipQuerySet(models.QuerySet):
    def delete(self):
        issued = self.filter(state__in=LOCKED).first()
        if issued is not None:
            raise ValidationError(issued.deletion_refused())
        return super().delete()

    def update(self, **kwargs):
        if set(kwargs) - MUTABLE_AFTER_ISSUE - {"superseded_by"}:
            issued = self.filter(state__in=LOCKED).first()
            if issued is not None:
                raise ValidationError(issued.edit_refused())
        return super().update(**kwargs)


class PayslipDocument(BaseModelWithUID):
    """§3.1."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.PROTECT, related_name="payslips")
    run = models.ForeignKey("payrunio.PayrollRun", on_delete=models.PROTECT, related_name="payslips")
    run_line = models.ForeignKey("payrunio.PayrollRunLine", on_delete=models.PROTECT, related_name="payslips")

    period = models.CharField(max_length=7)  # YYYY-MM
    document_no = models.CharField(max_length=30)
    state = models.CharField(max_length=12, choices=SlipStateChoices.choices, default=SlipStateChoices.DRAFT)
    language = models.CharField(max_length=2, choices=LanguageChoices.choices, default=LanguageChoices.EN)

    gross = _money()
    total_deductions = _money()
    net_pay = _money()
    net_in_words = models.TextField()
    net_in_words_bn = models.TextField(null=True, blank=True)

    wages_base = _money()  # s.125, narrower than gross
    non_cash_earnings = _money(default=0)
    pf_base = _money(default=0)
    deduction_ceiling = _money(null=True, blank=True)
    ceiling_basis = models.TextField(null=True, blank=True)

    earnings_json = models.JSONField()
    deductions_json = models.JSONField()  # in statutory order
    facts_json = models.JSONField()
    derivation_json = models.JSONField()  # the numbered tax working
    employer_json = models.JSONField()  # name and address as at issue

    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    tax_card = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    engine_version = models.CharField(max_length=40)
    input_hash = models.CharField(max_length=64)
    document_hash = models.CharField(max_length=64, null=True, blank=True)

    issued_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    issued_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="supersedes")
    retention_until = models.DateField(null=True, blank=True)

    objects = PayslipQuerySet.as_manager()

    class Meta:
        permissions = list(PERMISSIONS)
        constraints = [
            models.CheckConstraint(condition=Q(state__in=SlipStateChoices.values), name="slip_state_known"),
            models.UniqueConstraint(fields=["company", "document_no"], name="slip_no_unique"),
            models.CheckConstraint(condition=Q(net_pay__gte=0), name="net_non_negative"),
            models.CheckConstraint(condition=Q(wages_base__lte=F("gross") + F("non_cash_earnings")),
                                   name="wages_le_gross"),
            models.CheckConstraint(
                condition=~Q(state__in=LOCKED) | Q(issued_by__isnull=False, issued_at__isnull=False,
                                                   document_hash__isnull=False),
                name="issued_has_actor"),
            models.CheckConstraint(condition=GreaterThan(Length(Trim("net_in_words")), 0), name="words_present"),
            models.CheckConstraint(condition=Q(language__in=LanguageChoices.values), name="lang_known"),
            models.UniqueConstraint(fields=["run_line"], condition=~Q(state="SUPERSEDED"),
                                    name="one_live_slip_per_line"),
        ]
        indexes = [
            models.Index(fields=["employee", "-period"], name="idx_slip_employee_period"),
            models.Index(fields=["company", "period"], condition=Q(state="BLOCKED"), name="idx_slip_blocked"),
        ]

    def __str__(self):
        return self.document_no

    def edit_refused(self):
        return f"Document {self.document_no} is issued. A correction is a new document that supersedes it, not an edit."

    def deletion_refused(self):
        return f"Document {self.document_no} is issued and cannot be deleted. Retention runs to {self.retention_until}."

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old is not None and old.state in LOCKED:
                for field in self._meta.concrete_fields:
                    if field.attname not in MUTABLE_AFTER_ISSUE and \
                            getattr(self, field.attname) != getattr(old, field.attname):
                        raise ValidationError(self.edit_refused())
                if self.state not in AFTER_ISSUE[SlipStateChoices(old.state)]:
                    raise ValidationError(f"Document {self.document_no} is {old.state}; it does not go back.")
                _refuse_shorter(old.retention_until, self.retention_until)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.state in LOCKED:
            raise ValidationError(self.deletion_refused())
        return super().delete(*args, **kwargs)


class PayslipFinding(BaseModelWithUID):
    """§3.3. A finding with no statutory reference is an opinion."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    payslip = models.ForeignKey(PayslipDocument, on_delete=models.CASCADE, related_name="findings")
    severity = models.CharField(max_length=5, choices=SeverityChoices.choices)
    code = models.CharField(max_length=30)
    message = models.TextField()
    message_bn = models.TextField(null=True, blank=True)
    citation = models.TextField()
    consequence = models.TextField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=20, choices=ResolutionChoices.choices, null=True, blank=True)
    resolved_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(severity__in=SeverityChoices.values), name="finding_sev"),
            models.CheckConstraint(condition=GreaterThan(Length(Trim("citation")), 0), name="citation_present"),
            models.CheckConstraint(condition=Q(resolved=False) | Q(resolved_by__isnull=False, resolution__isnull=False),
                                   name="resolved_has_actor"),
        ]
        indexes = [models.Index(fields=["payslip"], condition=Q(severity="BLOCK", resolved=False),
                                name="idx_finding_blocking")]


class PayslipDelivery(BaseModelWithUID):
    """§3.5."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    payslip = models.ForeignKey(PayslipDocument, on_delete=models.PROTECT, related_name="deliveries")
    channel = models.CharField(max_length=10, choices=ChannelChoices.choices)
    destination = models.CharField(max_length=120, null=True, blank=True)  # masked
    delivered_at = models.DateTimeField(auto_now_add=True)
    delivered_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(channel__in=ChannelChoices.values), name="channel_known")]


class WagesRegister(BaseModelWithUID):
    """§3.6. Generated from issued slips: only its retention may move."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, related_name="+")
    run = models.OneToOneField("payrunio.PayrollRun", on_delete=models.PROTECT, related_name="wages_register")
    period = models.CharField(max_length=7)
    row_count = models.IntegerField()
    total_gross = _money()
    total_deductions = _money()
    total_net = _money()
    register_hash = models.CharField(max_length=64)
    generated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    generated_at = models.DateTimeField(auto_now_add=True)
    retention_until = models.DateField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(row_count__gt=0), name="register_rows")]

    def save(self, *args, **kwargs):
        if self._state.adding:
            slips = PayslipDocument.objects.filter(run_id=self.run_id, state__in=LIVE_ISSUED)
            n = slips.count()
            total = slips.aggregate(s=models.Sum("net_pay"))["s"] or 0
            if n != self.row_count or total != self.total_net:
                raise ValidationError(
                    f"Register states {self.row_count} rows totalling {self.total_net}, the issued slips are "
                    f"{n} totalling {total} — a register that disagrees with the slips is the document an "
                    "inspector will find.")
        else:
            old = type(self).objects.get(pk=self.pk)
            for field in self._meta.concrete_fields:
                if field.attname not in {"retention_until", "updated_at"} and \
                        getattr(self, field.attname) != getattr(old, field.attname):
                    raise ValidationError("A wages register is generated once; only its retention may be extended.")
            _refuse_shorter(old.retention_until, self.retention_until)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(f"The register for {self.period} cannot be deleted. Retention runs to "
                              f"{self.retention_until}.")


class PayslipAudit(AppendOnly):
    """§3.7. Plain references: the trail outlives any draft it mentions."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    payslip_uid = models.UUIDField(null=True, blank=True, db_index=True)
    run_uid = models.UUIDField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=20, choices=AuditActionChoices.choices)
    employee_uid = models.UUIDField(null=True, blank=True)
    actor_uid = models.UUIDField(null=True, blank=True)
    actor_name = models.CharField(max_length=255, blank=True, default="")
    actor_role = models.CharField(max_length=120, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    document_hash = models.CharField(max_length=64, null=True, blank=True)
    engine_version = models.CharField(max_length=40, blank=True, default="")
