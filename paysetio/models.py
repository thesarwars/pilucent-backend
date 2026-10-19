"""Payroll settings (docs/backend/payroll-settings-done.md).

- An election is effective-dated and never updated in place (§1.1): a change
  closes the row in force and opens a new one. The citation is stored on the
  row at election time (§3.2), so an amended Act does not rewrite what a 2026
  election cited.
- Four of the seven elections have no default (§2.1): no row means
  UNANSWERED, and an unanswered election blocks the run.
- A superseding election is a DRAFT proposal until a second person approves
  it (§6.2); the impact preview the approver saw is stored on the row.
- A site (the establishment) may override a company-wide election (§4.1).
- Scheme participation is per employee and effective-dated (§3.7), not a
  company boolean: `employeeio.EmployeeStatutory`'s membership flags are read
  from it.

The no-overlap rules (§5, invariants 1 and 2), the bonus-band check (§3.3)
and the append-only audit are Postgres guards in migration 0002; the models
enforce the same for the test database.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import BaseModelWithUID

from .choices import (
    ELECTION_KEYS,
    HOURS_RANGE,
    SCHEME_CODES,
    AuditActionChoices,
    ElectionStatusChoices,
    FrequencyChoices,
    SchemeStatusChoices,
)


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user():
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")


def _in(values):
    return list(values)


class PayrollElection(BaseModelWithUID):
    """§3.1. One election for one period. Only the lifecycle moves after
    insert: a DRAFT is approved or rejected, an ACTIVE row is closed."""

    MUTABLE = {"status", "effective_to", "approved_by_id", "approved_by_name", "approved_at", "rejected_reason",
               "updated_at"}

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    election_key = models.CharField(max_length=32)
    value_text = models.CharField(max_length=32, null=True, blank=True)
    value_json = models.JSONField(null=True, blank=True)
    standard_month_hours = models.PositiveSmallIntegerField(null=True, blank=True)

    statutory_citation = models.CharField(max_length=255)
    rule_set = models.ForeignKey("rulebookio.RuleSet", on_delete=models.PROTECT, related_name="+")

    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=ElectionStatusChoices.choices,
                              default=ElectionStatusChoices.ACTIVE)

    reason = models.TextField(blank=True, default="")
    impact_json = models.JSONField(null=True, blank=True)  # the preview the approver saw
    # SEEDED: a preset the company starts with; ELECTED: somebody chose it.
    source = models.CharField(max_length=8, default="ELECTED")
    decided_by = _user()
    decided_by_name = _text()
    approved_by = _user()
    approved_by_name = _text()
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("election_key", "-effective_from")
        indexes = [models.Index(fields=["company", "election_key", "-effective_from"], name="paysetio_election_lookup")]
        constraints = [
            models.CheckConstraint(condition=Q(election_key__in=_in(ELECTION_KEYS)), name="paysetio_election_key_known"),
            models.CheckConstraint(condition=Q(status__in=_in(ElectionStatusChoices.values)),
                                   name="paysetio_election_status_known"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gte=models.F("effective_from")),
                                   name="paysetio_election_dates_ordered"),
            models.CheckConstraint(condition=Q(status="DRAFT") | Q(value_text__isnull=False) | Q(value_json__isnull=False),
                                   name="paysetio_election_value_present"),
            models.CheckConstraint(condition=Q(standard_month_hours__isnull=True) | Q(election_key="overtime_base"),
                                   name="paysetio_election_hours_only_for_overtime"),
            models.CheckConstraint(condition=Q(standard_month_hours__isnull=True)
                                   | Q(standard_month_hours__gte=HOURS_RANGE[0], standard_month_hours__lte=HOURS_RANGE[1]),
                                   name="paysetio_election_hours_sane"),
            models.CheckConstraint(condition=~Q(statutory_citation=""), name="paysetio_election_cites"),
        ]

    def __str__(self):
        return f"{self.election_key}={self.value_text or self.value_json} from {self.effective_from}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            before = PayrollElection.objects.filter(pk=self.pk).values().first()
            if before:
                moved = {f.attname for f in self._meta.concrete_fields
                         if before.get(f.attname) != getattr(self, f.attname)} - self.MUTABLE
                if moved:
                    raise ValidationError(f"An election is never updated in place ({', '.join(sorted(moved))}). "
                                          "Elect again from a date instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("An election is never deleted: it is the record of what the company elected.")


class PaySchedule(BaseModelWithUID):
    """§3.4. Effective-dated like an election; the payment day is checked
    against the s.123 deadline when it is written."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    frequency = models.CharField(max_length=12, choices=FrequencyChoices.choices)
    cutoff_day = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_day = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_weekday = models.PositiveSmallIntegerField(null=True, blank=True)  # ISO 1-7
    payment_day_rule = models.CharField(max_length=32, default="WORKING_DAYS_AFTER_PERIOD")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=SchemeStatusChoices.choices, default=SchemeStatusChoices.ACTIVE)
    reason = models.TextField(blank=True, default="")
    decided_by = _user()
    decided_by_name = _text()

    class Meta:
        ordering = ("-effective_from",)
        constraints = [
            models.CheckConstraint(condition=Q(frequency__in=_in(FrequencyChoices.values)),
                                   name="paysetio_schedule_frequency_known"),
            models.CheckConstraint(condition=~Q(frequency="MONTHLY") | Q(cutoff_day__isnull=False, payment_day__isnull=False),
                                   name="paysetio_schedule_monthly_has_days"),
            models.CheckConstraint(condition=~Q(frequency__in=["WEEKLY", "FORTNIGHTLY"]) | Q(payment_weekday__isnull=False),
                                   name="paysetio_schedule_weekly_has_weekday"),
            models.CheckConstraint(condition=(Q(cutoff_day__isnull=True) | Q(cutoff_day__gte=1, cutoff_day__lte=31))
                                   & (Q(payment_day__isnull=True) | Q(payment_day__gte=1, payment_day__lte=31)),
                                   name="paysetio_schedule_days_in_range"),
            models.CheckConstraint(condition=Q(payment_weekday__isnull=True) | Q(payment_weekday__gte=1, payment_weekday__lte=7),
                                   name="paysetio_schedule_weekday_in_range"),
        ]


class StatutoryScheme(BaseModelWithUID):
    """§3.5. One table for the four schemes. A change supersedes the period
    in force (§6.5): changing the PF rate does not restate past
    contributions.

    The spec's `applies_needs_expense` CHECK is not here: it contradicts
    §4.2 and test S12, where an applying scheme without an expense account is
    the state that blocks the journal. Readiness reports it instead."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    scheme_code = models.CharField(max_length=16)
    applies = models.BooleanField()
    statutory_citation = models.CharField(max_length=255)
    config_json = models.JSONField(default=dict)
    expense_account = models.ForeignKey("accounts.ChartOfAccount", on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="+")
    liability_account = models.ForeignKey("accounts.ChartOfAccount", on_delete=models.PROTECT, null=True, blank=True,
                                          related_name="+")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=SchemeStatusChoices.choices, default=SchemeStatusChoices.ACTIVE)
    reason = models.TextField(blank=True, default="")
    decided_by = _user()
    decided_by_name = _text()

    class Meta:
        ordering = ("scheme_code", "-effective_from")
        constraints = [
            models.CheckConstraint(condition=Q(scheme_code__in=_in(SCHEME_CODES)), name="paysetio_scheme_code_known"),
            models.CheckConstraint(condition=~Q(scheme_code="GROUP_INSURANCE") | Q(liability_account__isnull=True),
                                   name="paysetio_insurance_has_no_liability"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gte=models.F("effective_from")),
                                   name="paysetio_scheme_dates_ordered"),
        ]


class SchemeParticipation(BaseModelWithUID):
    """§3.7. Per employee, effective-dated. `autoEnrol` does not mean
    everyone is enrolled: an unconfirmed probationer is not in the fund."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE, related_name="scheme_participations")
    scheme_code = models.CharField(max_length=16)
    enrolled = models.BooleanField(default=True)
    enrolled_on = models.DateField()
    opted_out_on = models.DateField(null=True, blank=True)
    opt_out_reason = models.TextField(blank=True, default="")
    # The member's own rates, in percent; null takes the scheme's.
    override_rate_pct = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    override_employer_rate_pct = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    decided_by = _user()
    decided_by_name = _text()

    class Meta:
        ordering = ("scheme_code", "-enrolled_on")
        indexes = [models.Index(fields=["scheme_code", "employee"], condition=Q(opted_out_on__isnull=True),
                                name="paysetio_participation_active")]
        constraints = [
            models.CheckConstraint(condition=Q(opted_out_on__isnull=True) | ~Q(opt_out_reason=""),
                                   name="paysetio_opt_out_has_reason"),
            models.CheckConstraint(condition=Q(opted_out_on__isnull=True) | Q(opted_out_on__gte=models.F("enrolled_on")),
                                   name="paysetio_opt_out_after_enrolment"),
            models.UniqueConstraint(fields=["employee", "scheme_code", "enrolled_on"], name="paysetio_one_participation"),
            models.UniqueConstraint(fields=["employee", "scheme_code"], condition=Q(opted_out_on__isnull=True),
                                    name="paysetio_one_open_participation"),
        ]

    def in_force_on(self, on):
        """`opted_out_on` is the first day outside the scheme."""
        return self.enrolled and self.enrolled_on <= on and (self.opted_out_on is None or self.opted_out_on > on)


class SettingsEvent(BaseModelWithUID):
    """§8. The outbox: payroll reads and marks consumed."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")


class SettingsAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("The settings audit is append-only.")

    def delete(self):
        raise ValidationError("The settings audit is append-only.")


class SettingsAudit(BaseModelWithUID):
    """§3.8, the changelog. `impact_json` is the consequence preview that was
    shown before approval: "we did not know it would cost that" is answerable
    from the record."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey("employeeio.Site", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    election_key = _text(32)
    scheme_code = _text(16)
    action = models.CharField(max_length=20, choices=AuditActionChoices.choices)
    from_value = models.JSONField(null=True, blank=True)
    to_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    impact_json = models.JSONField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    decided_by = _user()
    decided_by_name = _text()
    approved_by = _user()
    approved_by_name = _text()

    objects = SettingsAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-id")
        # §7. Approving is separate from electing and must be a different person.
        permissions = [
            ("view_payroll_settings", "Can view payroll settings"),
            ("preview_payroll_election", "Can run a payroll election consequence preview"),
            ("write_payroll_election", "Can elect or propose a payroll election"),
            ("approve_payroll_election", "Can approve a payroll election (not one they proposed)"),
            ("write_payroll_scheme", "Can enable and configure statutory schemes"),
            ("write_pay_schedule", "Can set the pay frequency, cut-off and payment day"),
            ("map_payroll_gl", "Can map statutory schemes to GL accounts"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The settings audit is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The settings audit is append-only.")
