"""Run payroll (docs/backend/run-payroll-done.md).

- A run is one site's pay schedule for one month (§11 non-negotiable 11). The
  schedule is payroll settings' `PaySchedule`: the site's own, else the
  company's. Nobody is in two schedules, because a person has one site.
- The state is a cache of the latest transition row (§2.1); the transition
  log is the truth and is append-only.
- The seven elections are resolved at run start and frozen into
  `elections_snapshot` (§3.4); a line never re-resolves them.
- A line's figures are fixed once the run is approved (§3.6): only the
  payment status moves after that. A correction is an adjustment run.
- The approver differs from the creator (§3.3), in the schema.

The line-immutability and totals-reconcile triggers and the append-only logs
are Postgres guards in migration 0002; the models enforce the same for the
test database.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from common.models import BaseModelWithUID

from .choices import (
    EXCEPTION_CODES,
    FIXED,
    PERMISSIONS,
    AuditActionChoices,
    OtSourceChoices,
    PayMethodChoices,
    PayStatusChoices,
    ResolutionChoices,
    RunStateChoices,
    RunTypeChoices,
    SeverityChoices,
    TransferStatusChoices,
)

MONEY = {"max_digits": 18, "decimal_places": 4}


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user(**kwargs):
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                             **kwargs)


def _money(**kwargs):
    return models.DecimalField(**MONEY, default=0, **kwargs)


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(f"{self.model.__name__} is append-only.")

    def delete(self):
        raise ValidationError(f"{self.model.__name__} is append-only.")


class AppendOnly(BaseModelWithUID):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(f"{type(self).__name__} is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(f"{type(self).__name__} is append-only.")


class PayrollRun(BaseModelWithUID):
    """§3.3."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, related_name="+")
    schedule = models.ForeignKey("paysetio.PaySchedule", on_delete=models.PROTECT, related_name="+")

    period = models.CharField(max_length=7)  # 'YYYY-MM'
    period_start = models.DateField()
    period_end = models.DateField()
    statutory_due_date = models.DateField()  # derived from the site's calendar (§4.1), never typed
    payment_date = models.DateField()  # the schedule's payment day, checked against the due date
    run_type = models.CharField(max_length=20, choices=RunTypeChoices.choices, default=RunTypeChoices.REGULAR)
    state = models.CharField(max_length=16, choices=RunStateChoices.choices, default=RunStateChoices.DRAFT)

    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    tax_card = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    engine_version = models.CharField(max_length=40)
    elections_snapshot = models.JSONField()

    member_count = models.PositiveIntegerField(default=0)
    included_count = models.PositiveIntegerField(default=0)
    excluded_count = models.PositiveIntegerField(default=0)
    total_gross = _money()
    total_tax = _money()
    total_pf_employee = _money()
    total_pf_employer = _money()
    total_net = _money()

    computed_at = models.DateTimeField(null=True, blank=True)
    approved_by = _user()
    approved_by_name = _text()
    approved_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(null=True, blank=True)

    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_by_name = _text()
    idempotency_key = _text(80)

    class Meta:
        ordering = ("-period_start", "site_id", "-created_at")
        indexes = [models.Index(fields=["company", "period_start"], name="payrunio_run_period")]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=list(RunStateChoices.values)), name="payrunio_run_state_known"),
            models.CheckConstraint(condition=Q(run_type__in=list(RunTypeChoices.values)), name="payrunio_run_type_known"),
            models.CheckConstraint(condition=Q(period__regex=r"^\d{4}-\d{2}$"), name="payrunio_period_shape"),
            models.CheckConstraint(condition=~Q(state__in=list(FIXED))
                                   | Q(approved_by__isnull=False, approved_at__isnull=False),
                                   name="payrunio_approved_has_approver"),
            # Segregation of duties, in the schema: whoever prepared the run
            # cannot approve it.
            models.CheckConstraint(condition=Q(approved_by__isnull=True) | ~Q(approved_by=F("created_by")),
                                   name="payrunio_approver_differs_from_creator"),
            models.CheckConstraint(condition=~Q(state="CANCELLED") | Q(cancelled_reason__isnull=False),
                                   name="payrunio_cancelled_has_reason"),
            models.UniqueConstraint(fields=["site", "period"],
                                    condition=Q(run_type="REGULAR") & ~Q(state="CANCELLED"),
                                    name="payrunio_one_regular_run"),
            models.UniqueConstraint(fields=["company", "idempotency_key"], condition=~Q(idempotency_key=""),
                                    name="payrunio_run_idempotent"),
        ]
        permissions = list(PERMISSIONS)

    def __str__(self):
        return f"{self.site_id}/{self.period} {self.run_type} {self.state}"

    @property
    def ref(self):
        return f"PR-{self.period}-{str(self.uid)[:8].upper()}"

    @property
    def fixed(self):
        return self.state in FIXED


class PayrollRunTransition(AppendOnly):
    """§2.1. "Who approved this run and when" must be answerable years later."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.CharField(max_length=16, null=True, blank=True)
    to_state = models.CharField(max_length=16)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    actor_name = _text()
    actor_role = models.CharField(max_length=60)
    reason = models.TextField(blank=True, default="")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("at", "id")
        indexes = [models.Index(fields=["run", "at"], name="payrunio_transition_run")]


class PayrollRunLine(BaseModelWithUID):
    """§3.5. One row per employee per run."""

    # What may still change once the run is approved (§3.6).
    MUTABLE_FIXED = {"payment_status", "paid_at", "updated_at"}

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.PROTECT, related_name="payroll_lines")

    included = models.BooleanField(default=True)
    exclusion_reason = models.TextField(null=True, blank=True)
    excluded_by = _user()
    excluded_by_name = _text()

    structure = models.ForeignKey("employeeio.EmployeeSalaryStructure", on_delete=models.PROTECT, null=True,
                                  blank=True, related_name="+")
    gross_before_proration = models.DecimalField(**MONEY, null=True, blank=True)

    calendar_days = models.PositiveSmallIntegerField()
    payable_days = models.DecimalField(max_digits=8, decimal_places=4)
    days_lost = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    lwp_days = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    join_date_in_period = models.DateField(null=True, blank=True)
    leave_date_in_period = models.DateField(null=True, blank=True)
    proration_factor = models.DecimalField(max_digits=10, decimal_places=6, default=1)

    ot_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ot_hours_attendance = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ot_hours_source = models.CharField(max_length=16, choices=OtSourceChoices.choices,
                                       default=OtSourceChoices.ATTENDANCE)
    ot_hours_overridden_by = _user()
    ot_override_reason = models.TextField(blank=True, default="")
    ot_base_amount = _money()
    ot_amount = _money()

    gross = _money()
    tax_withheld = _money()
    pf_employee = _money()
    pf_employer = _money()
    other_deductions = _money()
    net_pay = _money()
    blocked = models.BooleanField(default=False)  # could not be computed (no structure)

    payment_method = models.CharField(max_length=16, choices=PayMethodChoices.choices)
    mfs_provider = _text(20)
    destination_ref = _text(80)  # masked account or wallet
    payment_status = models.CharField(max_length=12, choices=PayStatusChoices.choices,
                                      default=PayStatusChoices.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    earnings_json = models.JSONField(null=True, blank=True)
    deductions_json = models.JSONField(null=True, blank=True)
    tax_derivation_json = models.JSONField(null=True, blank=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    input_hash = _text(64)

    class Meta:
        ordering = ("employee__code",)
        indexes = [models.Index(fields=["run"], condition=Q(included=True), name="payrunio_line_run"),
                   models.Index(fields=["run"], condition=Q(payment_status__in=["PENDING", "INSTRUCTED"], included=True),
                                name="payrunio_line_unpaid")]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="payrunio_line_unique"),
            models.CheckConstraint(condition=Q(net_pay__gte=0), name="payrunio_net_non_negative"),
            models.CheckConstraint(condition=Q(payable_days__lte=F("calendar_days")), name="payrunio_payable_le_calendar"),
            models.CheckConstraint(condition=Q(proration_factor__gt=0, proration_factor__lte=1),
                                   name="payrunio_factor_in_range"),
            models.CheckConstraint(condition=Q(payment_method__in=list(PayMethodChoices.values)),
                                   name="payrunio_method_known"),
            models.CheckConstraint(condition=Q(payment_status__in=list(PayStatusChoices.values)),
                                   name="payrunio_pay_status_known"),
            models.CheckConstraint(condition=Q(included=True) | Q(exclusion_reason__isnull=False),
                                   name="payrunio_excluded_has_reason"),
            models.CheckConstraint(condition=~Q(ot_hours_source="MANUAL_OVERRIDE")
                                   | Q(ot_hours_overridden_by__isnull=False),
                                   name="payrunio_override_has_actor"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            state = PayrollRun.objects.filter(pk=self.run_id).values_list("state", flat=True).first()
            if state in FIXED:
                before = PayrollRunLine.objects.filter(pk=self.pk).values().first() or {}
                moved = {f.attname for f in self._meta.concrete_fields
                         if before.get(f.attname) != getattr(self, f.attname)} - self.MUTABLE_FIXED
                if moved:
                    raise ValidationError(f"Run is {state} — the figures are fixed. A correction is an adjustment "
                                          f"run, not an edit ({', '.join(sorted(moved))}).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        state = PayrollRun.objects.filter(pk=self.run_id).values_list("state", flat=True).first()
        if state in FIXED:
            raise ValidationError(f"Run is {state} — a line cannot be deleted. Raise an adjustment run.")
        super().delete(*args, **kwargs)


class PayrollException(BaseModelWithUID):
    """§3.7. Every message carries its figures."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="exceptions")
    line = models.ForeignKey(PayrollRunLine, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="exceptions")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="+")
    severity = models.CharField(max_length=5, choices=SeverityChoices.choices)
    code = models.CharField(max_length=32)
    message = models.TextField()
    message_bn = models.TextField(blank=True, default="")
    citation = _text()

    resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=16, choices=ResolutionChoices.choices, null=True, blank=True)
    resolution_reason = models.TextField(blank=True, default="")
    resolved_by = _user()
    resolved_by_name = _text()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [models.Index(fields=["run"], condition=Q(severity="BLOCK", resolved=False),
                                name="payrunio_exception_blocking")]
        constraints = [
            models.CheckConstraint(condition=Q(severity__in=list(SeverityChoices.values)), name="payrunio_sev_known"),
            models.CheckConstraint(condition=Q(code__in=list(EXCEPTION_CODES)), name="payrunio_code_known"),
            models.CheckConstraint(condition=Q(resolution__isnull=True)
                                   | Q(resolution__in=list(ResolutionChoices.values)),
                                   name="payrunio_resolution_known"),
            models.CheckConstraint(condition=Q(resolved=False)
                                   | Q(resolved_by__isnull=False, resolution__isnull=False),
                                   name="payrunio_resolved_has_actor"),
            # §6.3: a BLOCK cannot be accepted.
            models.CheckConstraint(condition=~Q(severity="BLOCK", resolution="ACCEPTED"),
                                   name="payrunio_block_not_accepted"),
        ]


class PaymentInstruction(BaseModelWithUID):
    """§3.9. The file is stored with its hash: a bank disputing a file is
    answered by what was generated, not by regenerating it."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="instructions")
    bank_profile_code = models.CharField(max_length=32)
    corporate_account = _text(60)

    file_name = models.CharField(max_length=120)
    file_hash = models.CharField(max_length=64)
    content = models.TextField()
    encoding = models.CharField(max_length=20, default="UTF-8")
    row_count = models.PositiveIntegerField()
    total_amount = models.DecimalField(**MONEY)

    generated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    generated_by_name = _text()
    generated_at = models.DateTimeField(auto_now_add=True)
    idempotency_key = models.CharField(max_length=80)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    ack_reference = _text(80)

    class Meta:
        ordering = ("generated_at", "id")
        constraints = [
            models.UniqueConstraint(fields=["company", "idempotency_key"], name="payrunio_instruction_idempotent"),
            models.CheckConstraint(condition=Q(row_count__gt=0), name="payrunio_rows_positive"),
        ]


class PaymentInstructionLine(BaseModelWithUID):
    instruction = models.ForeignKey(PaymentInstruction, on_delete=models.CASCADE, related_name="lines")
    run_line = models.ForeignKey(PayrollRunLine, on_delete=models.PROTECT, related_name="transfers")
    amount = models.DecimalField(**MONEY)
    status = models.CharField(max_length=12, choices=TransferStatusChoices.choices,
                              default=TransferStatusChoices.INSTRUCTED)
    failure_reason = models.TextField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=["instruction", "run_line"], name="payrunio_one_line_per_instruction")]


class CorporateAccount(BaseModelWithUID):
    """The company's own account for a bank or wallet file profile: the debit
    side every file header carries."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    profile_code = models.CharField(max_length=32)
    account = models.CharField(max_length=60)
    set_by = _user()
    set_by_name = _text()

    class Meta:
        ordering = ("profile_code",)
        constraints = [models.UniqueConstraint(fields=["company", "profile_code"], name="payrunio_one_account")]


class RunEvent(BaseModelWithUID):
    """§8. The outbox: the TDS ledger, the GL journal and the compliance
    dashboard read and mark consumed."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    name = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")


class PayrollAudit(AppendOnly):
    """§3.10."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(PayrollRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=24, choices=AuditActionChoices.choices)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    actor = _user()
    actor_name = _text()
    actor_role = _text(60)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    engine_version = _text(40)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-at", "-id")
        indexes = [models.Index(fields=["run", "at"], name="payrunio_audit_run")]
