"""BD leave (docs/backend/leave-backend.md).

No balance is stored. Every balance is a sum over an append-only ledger, on
every read; a correction is a reversal plus a replacement, never an edit.
Every entry pins the labour rule set it was computed under, so a past
balance reproduces after the law changes.

Days are NUMERIC(18,4) and Decimal throughout: never a float.

Tenancy: every table carries `company`, and every read filters on it.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from common.models import BaseModelWithUID

from .choices import (
    AccrualKindChoices,
    BenefitBasisChoices,
    IssueMethodChoices,
    LeaveEventChoices,
    MaternityEventChoices,
    CycleKindChoices,
    EncashmentStatusChoices,
    GenderRestrictionChoices,
    HalfChoices,
    LeaveAuditActionChoices,
    LedgerReasonChoices,
    MaternityStatusChoices,
    NoticeMethodChoices,
    RequestStatusChoices,
    WorkerRestrictionChoices,
)

DAYS = dict(max_digits=18, decimal_places=4)
APPEND_ONLY = "The leave ledger is append-only. Correct an entry with a reversal and a replacement."


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user(**kwargs):
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                             **kwargs)


# ----------------------------------------------------------------- leave type


class LeaveType(BaseModelWithUID):
    """§3.2. How a kind of leave is earned, counted and booked. The statutory
    figures (10 casual, 14 sick, the divisors) are read from the rule book
    in force, not stored here."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="bd_leave_types")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=80)
    name_bn = _text(80)
    display_order = models.PositiveSmallIntegerField(default=0)

    is_statutory = models.BooleanField(default=False)
    statutory_basis = _text(120)

    cycle_kind = models.CharField(max_length=15, choices=CycleKindChoices.choices)
    earn_in_arrears = models.BooleanField(default=False)
    accrual_kind = models.CharField(max_length=20, choices=AccrualKindChoices.choices)
    # A non-statutory fixed entitlement; statutory ones come from the rule book.
    accrual_days = models.DecimalField(**DAYS, null=True, blank=True)

    gender_restriction = models.CharField(max_length=10, choices=GenderRestrictionChoices.choices,
                                          default=GenderRestrictionChoices.NONE)
    worker_restriction = models.CharField(max_length=15, choices=WorkerRestrictionChoices.choices,
                                          default=WorkerRestrictionChoices.ANY)
    pay_rate = models.CharField(max_length=10, default="FULL")

    # Day counting, per type and never global (§5.2).
    consumes_public_holidays = models.BooleanField(default=False)
    consumes_weekly_holidays = models.BooleanField(default=False)
    counts_calendar_days = models.BooleanField(default=False)

    min_consecutive_days = models.PositiveSmallIntegerField(default=1)
    max_consecutive_days = models.PositiveSmallIntegerField(null=True, blank=True)
    half_day_allowed = models.BooleanField(default=False)
    backdate_window_days = models.PositiveSmallIntegerField(default=0)
    allow_negative_balance = models.BooleanField(default=False)
    advance_allowed = models.BooleanField(default=False)

    carry_forward_allowed = models.BooleanField(default=False)
    carry_forward_fixed_cap = models.DecimalField(**DAYS, null=True, blank=True)
    encashment_allowed = models.BooleanField(default=False)
    payable_on_separation = models.BooleanField(default=False)
    requires_medical_cert = models.BooleanField(default=False)
    # Shown on the balances grid; the rest are read in the history drawer.
    on_grid = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("display_order", "code")
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="leaveledgerio_type_code_per_company"),
            # Paternity and bereavement leave have no statutory basis in Bangladesh:
            # a type claiming to be statutory must cite the section it rests on.
            models.CheckConstraint(condition=Q(is_statutory=False) | ~Q(statutory_basis=""),
                                   name="leaveledgerio_statutory_needs_basis"),
        ]

    def __str__(self):
        return self.code


# ---------------------------------------------------------------------- cycle


class LeaveCycle(BaseModelWithUID):
    """§3.3. Opened lazily. A service-year cycle runs from the joining
    anniversary; a credit's cycle is its own window."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="leave_cycles")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="cycles")
    kind = models.CharField(max_length=15, choices=CycleKindChoices.choices)
    starts_on = models.DateField()
    ends_on = models.DateField()
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = _user()
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ("employee", "leave_type", "starts_on")
        constraints = [
            models.UniqueConstraint(fields=["employee", "leave_type", "starts_on"], name="leaveledgerio_cycle_unique"),
            models.CheckConstraint(condition=Q(ends_on__gte=F("starts_on")), name="leaveledgerio_cycle_ordered"),
        ]

    def __str__(self):
        return f"{self.leave_type_id} {self.starts_on}..{self.ends_on}"


# --------------------------------------------------------------------- ledger


class LedgerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(APPEND_ONLY)

    def delete(self):
        raise ValidationError(APPEND_ONLY)

    def _mark_reversed(self, reversal):
        """The one permitted change: `reversed_by`, once, from null. Returns
        how many rows changed; 0 means it was already reversed."""
        return models.QuerySet.update(self.filter(reversed_by__isnull=True), reversed_by=reversal)


class LedgerEntry(BaseModelWithUID):
    """§3.4. Append-only. `basis` is a sentence the employee can read."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="leave_entries")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="entries")
    cycle = models.ForeignKey(LeaveCycle, on_delete=models.PROTECT, related_name="entries")

    effective_date = models.DateField()
    days = models.DecimalField(**DAYS)
    reason = models.CharField(max_length=20, choices=LedgerReasonChoices.choices)
    basis = models.TextField()
    basis_bn = models.TextField(blank=True, default="")
    source_ref = _text(80)

    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    created_by = _user()
    created_by_name = _text()
    on_behalf = models.BooleanField(default=False)
    reversed_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="reverses")

    objects = LedgerQuerySet.as_manager()

    class Meta:
        ordering = ("employee", "leave_type", "effective_date", "id")
        indexes = [models.Index(fields=["employee", "leave_type", "effective_date"],
                                name="leaveledgerio_entry_emp_type")]
        constraints = [
            # A zero is a movement that did not happen -- except the capped marker,
            # and the reversal of one.
            models.CheckConstraint(condition=~Q(days=0) | Q(reason__in=["ACCRUAL_CAPPED", "REVERSAL"]),
                                   name="leaveledgerio_days_nonzero"),
            models.CheckConstraint(condition=~Q(basis=""), name="leaveledgerio_basis_present"),
            # Idempotency by construction: a second accrual run is refused here.
            models.UniqueConstraint(fields=["employee", "leave_type", "cycle"],
                                    condition=Q(reason__in=["ACCRUAL", "ACCRUAL_CAPPED"], reversed_by__isnull=True),
                                    name="leaveledgerio_one_accrual_per_cycle"),
            # One posting per attendance credit, however often it is synced.
            models.UniqueConstraint(fields=["company", "source_ref"],
                                    condition=Q(reason="CREDIT_EARNED") & ~Q(source_ref=""),
                                    name="leaveledgerio_credit_once"),
        ]

    @property
    def reference(self):
        return f"LEDG-{self.pk:06d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(APPEND_ONLY)


# ------------------------------------------------------------------- requests


class LeaveRequest(BaseModelWithUID):
    """§3.7. `day_breakdown` is frozen at submission: a calendar republished
    later does not change what was agreed."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    cycle = models.ForeignKey(LeaveCycle, on_delete=models.PROTECT, related_name="requests")

    from_date = models.DateField()
    to_date = models.DateField()
    start_half = models.CharField(max_length=12, choices=HalfChoices.choices, default=HalfChoices.FULL)
    end_half = models.CharField(max_length=12, choices=HalfChoices.choices, default=HalfChoices.FULL)
    days_consumed = models.DecimalField(**DAYS)
    day_breakdown = models.JSONField()

    status = models.CharField(max_length=12, choices=RequestStatusChoices.choices,
                              default=RequestStatusChoices.SUBMITTED)
    note = models.TextField(blank=True, default="")
    contact_during_leave = _text(120)
    cover_employee = models.ForeignKey("employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    evidence = _text()

    is_backdated = models.BooleanField(default=False)
    is_advance = models.BooleanField(default=False)
    # Statutory and not refusable: maternity is not a clash an approver resolves.
    non_refusable = models.BooleanField(default=False)

    created_by = _user()
    created_by_name = _text()
    on_behalf = models.BooleanField(default=True)
    decided_by = _user()
    decided_by_name = _text()
    decided_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default="")
    ledger_entry = models.ForeignKey(LedgerEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["employee", "status"], name="leaveledgerio_request_emp")]
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="leaveledgerio_request_reference"),
            models.CheckConstraint(condition=Q(to_date__gte=F("from_date")), name="leaveledgerio_dates_ordered"),
            models.CheckConstraint(condition=~Q(status="DECLINED") | ~Q(decline_reason=""),
                                   name="leaveledgerio_decline_needs_reason"),
        ]


class LeaveHold(BaseModelWithUID):
    """§3.6. A submitted request reserves its days without debiting them, so
    three requests cannot each be approved against the same four days."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name="holds")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="+")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    cycle = models.ForeignKey(LeaveCycle, on_delete=models.PROTECT, related_name="holds")
    days = models.DecimalField(**DAYS)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request"], condition=Q(released_at__isnull=True),
                                    name="leaveledgerio_one_live_hold"),
        ]


# ----------------------------------------------------------------- encashment


class Encashment(BaseModelWithUID):
    """§3.8. `divisor` is stored: leave wages, encashment, maternity benefit
    and separation each use a different base and divisor, and the row says
    which one was used. The ledger entry is written on approval."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="leave_encashments")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    cycle = models.ForeignKey(LeaveCycle, on_delete=models.PROTECT, related_name="encashments")

    days = models.DecimalField(**DAYS)
    wage_base = models.DecimalField(**DAYS)
    divisor = models.PositiveSmallIntegerField()
    daily_rate = models.DecimalField(**DAYS)
    amount = models.DecimalField(**DAYS)
    rate_basis = models.CharField(max_length=160)

    status = models.CharField(max_length=10, choices=EncashmentStatusChoices.choices,
                              default=EncashmentStatusChoices.SUBMITTED)
    requested_by = _user()
    requested_by_name = _text()
    approved_by = _user()
    approved_by_name = _text()
    approved_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default="")
    payment_month = models.DateField(null=True, blank=True)
    payroll_ref = _text(40)
    payslip_ref = _text(60)
    paid_at = models.DateTimeField(null=True, blank=True)
    ledger_entry = models.ForeignKey(LedgerEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="leaveledgerio_encashment_reference"),
            models.UniqueConstraint(fields=["employee", "leave_type", "cycle"], condition=~Q(status="DECLINED"),
                                    name="leaveledgerio_one_encashment_per_cycle"),
            models.CheckConstraint(condition=Q(days__gt=0), name="leaveledgerio_encashment_days_positive"),
            models.CheckConstraint(condition=~Q(status="DECLINED") | ~Q(decline_reason=""),
                                   name="leaveledgerio_encashment_decline_reason"),
        ]


# ------------------------------------------------------------------ maternity


RESTRICTED_MATERNITY_FIELDS = ("expected_delivery", "actual_delivery", "surviving_children")


class MaternityCase(BaseModelWithUID):
    """§3.10. Three fields are restricted to HR and every read of one is
    logged, a refused read included. A pay disqualification is never a leave
    disqualification: where the benefit is not payable, the leave stands."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="maternity_cases")
    status = models.CharField(max_length=15, choices=MaternityStatusChoices.choices,
                              default=MaternityStatusChoices.NOTIFIED)

    notice_date = models.DateField()
    notice_method = models.CharField(max_length=10, choices=NoticeMethodChoices.choices)
    notice_recorded_by = _user()
    notice_recorded_by_name = _text()

    expected_delivery = models.DateField()  # RESTRICTED
    actual_delivery = models.DateField(null=True, blank=True)  # RESTRICTED
    surviving_children = models.PositiveSmallIntegerField()  # RESTRICTED

    service_months = models.PositiveSmallIntegerField()
    service_months_met = models.BooleanField()
    children_met = models.BooleanField()
    benefit_payable = models.BooleanField()
    eligibility_reason = models.TextField()

    pre_leave_from = models.DateField()
    pre_leave_to = models.DateField()
    post_leave_from = models.DateField()
    post_leave_to = models.DateField()
    total_days_granted = models.PositiveSmallIntegerField()

    protection_start = models.DateField()
    protection_end = models.DateField()
    employment_ban_end = models.DateField()
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")
    request = models.OneToOneField(LeaveRequest, on_delete=models.PROTECT, related_name="maternity_case")

    # The benefit (s.48), computed at the notice and kept as computed: the
    # basis is a disputed rule, elected on the record, and the reference wages
    # are what it was worked out from.
    benefit_basis = models.CharField(max_length=12, choices=BenefitBasisChoices.choices,
                                     default=BenefitBasisChoices.ACT_S48)
    basis_elected_by_name = _text()
    reference_lines = models.JSONField(default=list)  # [{month, wage, days, daysSource}]
    total_wage = models.DecimalField(**DAYS, default=0)
    total_days = models.DecimalField(**DAYS, default=0)
    average_daily_wage = models.DecimalField(**DAYS, default=0)
    benefit_days = models.PositiveSmallIntegerField(default=0)
    benefit_amount = models.DecimalField(**DAYS, default=0)
    first_instalment_amount = models.DecimalField(**DAYS, default=0)
    second_instalment_amount = models.DecimalField(**DAYS, default=0)
    benefit_basis_text = models.TextField(blank=True, default="")

    proof_of_pregnancy_on = models.DateField(null=True, blank=True)
    first_instalment_paid_on = models.DateField(null=True, blank=True)
    proof_of_birth_on = models.DateField(null=True, blank=True)
    second_instalment_paid_on = models.DateField(null=True, blank=True)
    returned_on = models.DateField(null=True, blank=True)
    cancelled_on = models.DateField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="leaveledgerio_maternity_reference"),
        ]


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(APPEND_ONLY)

    def delete(self):
        raise ValidationError(APPEND_ONLY)


class AppendOnlyModel(BaseModelWithUID):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(APPEND_ONLY)


class MaternityEvent(AppendOnlyModel):
    """The case's timeline, in the statute's order. Never edited."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    case = models.ForeignKey(MaternityCase, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=20, choices=MaternityEventChoices.choices)
    on = models.DateField()
    note = models.TextField(blank=True, default="")
    actor = _user()
    actor_name = _text()

    class Meta:
        ordering = ("on", "id")


# ----------------------------------------------------------------- statements


class StatementBatch(BaseModelWithUID):
    """A quarter's leave statements (Form-9), one per worker. Regenerating
    makes a new version; an issued statement is never rewritten."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    quarter = models.CharField(max_length=7)  # 2026-Q4
    version = models.PositiveSmallIntegerField(default=1)
    period_from = models.DateField()
    period_to = models.DateField()
    generated_by = _user()
    generated_by_name = _text()
    # Attendance months still open when it was generated, acknowledged on the record.
    unlocked_months = models.JSONField(default=list)

    class Meta:
        ordering = ("-quarter", "-version")
        constraints = [
            models.UniqueConstraint(fields=["company", "quarter", "version"], name="leaveledgerio_statement_version"),
        ]


class Statement(BaseModelWithUID):
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    batch = models.ForeignKey(StatementBatch, on_delete=models.CASCADE, related_name="statements")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="leave_statements")
    rows = models.JSONField()  # one per leave type: opening, earned, taken, refused, encashed, other, closing
    acknowledged_at = models.DateField(null=True, blank=True)
    acknowledged_by_name = _text()

    class Meta:
        ordering = ("employee__code",)
        constraints = [
            models.UniqueConstraint(fields=["batch", "employee"], name="leaveledgerio_statement_once"),
        ]


class StatementIssue(AppendOnlyModel):
    """How a statement reached the worker. The statement is easy; evidencing
    that the worker received it is what an inspection tests."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    statement = models.ForeignKey(Statement, on_delete=models.CASCADE, related_name="issues")
    method = models.CharField(max_length=10, choices=IssueMethodChoices.choices)
    on = models.DateField()
    detail = _text()
    recorded_by = _user()
    recorded_by_name = _text()

    class Meta:
        ordering = ("on", "id")


# --------------------------------------------------------------------- events


class LeaveEvent(BaseModelWithUID):
    """§9's events, as an outbox: written in the same transaction as the
    change, consumed later (payroll reads LeaveApproved and
    EncashmentApproved). Notifications go out beside it."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=40, choices=LeaveEventChoices.choices)
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    entity_ref = models.CharField(max_length=60, blank=True, default="")
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=["company", "name", "consumed_at"], name="leaveledgerio_event_open")]


# ---------------------------------------------------------------------- audit


class LeaveAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("The leave audit is append-only.")

    def delete(self):
        raise ValidationError("The leave audit is append-only.")


class LeaveAudit(BaseModelWithUID):
    """§3.11. `on_behalf_of`: HR entering a request for an employee is a
    different act from the employee entering it, and a dispute turns on
    which happened."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    entity_type = models.CharField(max_length=30)
    entity_id = models.CharField(max_length=60)
    action = models.CharField(max_length=30, choices=LeaveAuditActionChoices.choices)
    actor = _user()
    actor_name = _text()
    actor_role = _text(120)
    on_behalf_of = models.ForeignKey("employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    reason = models.TextField(blank=True, default="")
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    engine_version = models.CharField(max_length=40)

    objects = LeaveAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        # §8. Approve and grant are separate from applying; the restricted
        # maternity fields are their own permission.
        permissions = [
            ("apply_leave", "Can submit leave and encashment on an employee's behalf"),
            ("approve_leave", "Can approve or decline leave"),
            ("grant_leave", "Can grant, debit or correct leave"),
            ("approve_encashment", "Can approve and pay a leave encashment"),
            ("close_leave_year", "Can post accruals and close the leave year"),
            ("read_maternity_restricted", "Can read restricted maternity fields"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The leave audit is append-only.")
        super().save(*args, **kwargs)
