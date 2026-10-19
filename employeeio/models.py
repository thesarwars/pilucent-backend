"""The BD employee profile (`docs/employee-profile.md`).

Tenancy: these tables have no RLS. Every read is scoped by `company` in the
application -- directly on `Employee`, and through `employee__company` on
every sub-record, none of which carries a company of its own.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.lookups import LessThanOrEqual

from common.models import BaseModelWithUID
from common.money import MONEY_FIELD, ZERO

from .choices import (
    ArrearsRunChoices,
    BloodGroupChoices,
    ClassificationChoices,
    DivisionChoices,
    DocumentKindChoices,
    EmployeeStatusChoices,
    EmploymentTypeChoices,
    EstablishmentChoices,
    GenderChoices,
    GradeChoices,
    InstrumentChoices,
    MaritalChoices,
    MfsProviderChoices,
    PaymentMethodChoices,
    RelationChoices,
    ReligionChoices,
    RevisionMethodChoices,
    RevisionTypeChoices,
    SalaryAuditActionChoices,
    SalaryComponentChoices,
    SalaryStatusChoices,
    SeparationTypeChoices,
    TaxpayerCategoryChoices,
    TrackedFieldChoices,
    VehicleChoices,
    WalletTypeChoices,
    WorkerCategoryChoices,
)


def _text(max_length=255, **kwargs):
    # Blank is a truthful state (doc §1.4): an unfilled string is "", never NULL
    # and never a plausible-looking default.
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


class Site(BaseModelWithUID):
    """An establishment: one place of work (a factory, a head office).
    Shifts, the holiday calendar and the attendance month belong to a site,
    not to the company -- a factory closing its month has no bearing on the
    head office (attendance §1.5). Every company has one default site; an
    employee with no site of their own is on it."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="sites")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    name_bn = _text(120)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-is_default", "name")
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="employeeio_site_code_per_company"),
            models.UniqueConstraint(fields=["company"], condition=Q(is_default=True),
                                    name="employeeio_site_one_default_per_company"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class Employee(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, related_name="employees"
    )
    # Null means the company's default site (services.sites.site_of).
    site = models.ForeignKey(Site, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    # Optional login for self-service. `User.get_employee()` reads this relation.
    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=EmployeeStatusChoices.choices,
        default=EmployeeStatusChoices.ACTIVE,
        db_index=True,
    )
    # ---- account access (accounts/tenancy, not HR -- carried over unchanged)
    # Whether the linked login may authenticate and enter this company's
    # workspace (accounts.django_rest.helpers.login_access, SelectCompany).
    # Off until an admin grants it, which sends the invitation email.
    is_access_enabled = models.BooleanField(default=False)
    # Whether the linked user finished onboarding (accounts onboard flow).
    is_joined = models.BooleanField(default=False)

    # ---- identity and personal (§2.1)
    # Business key, e.g. EMP-0142. Unique within the company, never reassigned.
    code = models.CharField(max_length=20)
    name_en = models.CharField(max_length=255)
    name_bn = _text()
    father_name = _text()
    mother_name = _text()
    marital = _text(20, choices=MaritalChoices.choices)
    spouse_name = _text()
    dob = models.DateField(null=True, blank=True)
    gender = _text(20, choices=GenderChoices.choices)
    blood = _text(3, choices=BloodGroupChoices.choices)
    religion = _text(20, choices=ReligionChoices.choices)
    nid = _text(32)
    birth_cert = _text(32)
    passport = _text(32)
    work_permit = _text(64)
    mobile = _text(20)
    email = models.EmailField(blank=True, default="")
    present_address = models.TextField(blank=True, default="")
    present_division = _text(20, choices=DivisionChoices.choices)
    permanent_same = models.BooleanField(default=False)
    permanent_address = models.TextField(blank=True, default="")
    permanent_division = _text(20, choices=DivisionChoices.choices)
    emergency_name = _text()
    emergency_relation = _text(20, choices=RelationChoices.choices)
    emergency_phone = _text(20)
    photo = models.ImageField(upload_to="employees/photos", blank=True, null=True)

    # ---- employment (§2.2)
    classification = _text(20, choices=ClassificationChoices.choices)
    worker_category = _text(20, choices=WorkerCategoryChoices.choices)
    establishment = _text(40, choices=EstablishmentChoices.choices)
    employment_type = _text(20, choices=EmploymentTypeChoices.choices)
    contract_end = models.DateField(null=True, blank=True)
    doj = models.DateField(null=True, blank=True)
    probation_end = models.DateField(null=True, blank=True)
    confirmation = models.DateField(null=True, blank=True)
    department = models.ForeignKey(
        "companyio.CompanyDepartment", on_delete=models.SET_NULL, null=True, blank=True
    )
    section = models.ForeignKey(
        "companyio.CompanySection", on_delete=models.SET_NULL, null=True, blank=True
    )
    designation = models.ForeignKey(
        "companyio.CompanyDesignation", on_delete=models.SET_NULL, null=True, blank=True
    )
    shift = models.ForeignKey(
        "companyio.CompanyShift", on_delete=models.SET_NULL, null=True, blank=True
    )
    grade = _text(2, choices=GradeChoices.choices)
    manager = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )
    appointment_letter = models.BooleanField(default=False)
    id_card = models.BooleanField(default=False)
    id_card_date = models.DateField(null=True, blank=True)
    separated_on = models.DateField(null=True, blank=True)
    separation_type = _text(20, choices=SeparationTypeChoices.choices)
    # When the final settlement ran. Separated without it is a hard block (§3.1).
    final_settlement_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("code",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="employeeio_employee_code_unique_per_company"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name_en}"

    def clean(self):
        if not (self.name_en or "").strip():
            raise ValidationError({"name_en": "A name in English is required — it prints on the service book."})

    def save(self, *args, **kwargs):
        if not self._state.adding and "code" in self.get_dirty_fields(check_relationship=False):
            raise ValidationError({"code": "An employee code is never reassigned."})
        super().save(*args, **kwargs)

    @property
    def completed_payroll_runs(self):
        """Processed payroll periods this employee was paid in. Derived,
        read-only; drives the retroactive-change warning (§2.2, §6.1)."""
        from .services.periods import completed_runs

        return completed_runs(self)

    @property
    def settlement_outstanding(self):
        return bool(self.separated_on) and not self.final_settlement_on


class ProcessedPayrollPeriod(BaseModelWithUID):
    """A payroll period the company has processed: the source of "periods a
    backdated change reopens" and of the next unprocessed period (§5.2).

    The BD payroll run writes one row when it completes a period. `period` is
    the first day of the month.
    """

    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, related_name="processed_payroll_periods"
    )
    period = models.DateField()
    processed_on = models.DateField()
    processed_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("period",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "period"], name="employeeio_processed_period_once_per_company"
            ),
        ]

    def __str__(self):
        return f"{self.company_id} {self.period:%Y-%m}"

    def clean(self):
        if self.period and self.period.day != 1:
            raise ValidationError({"period": "A payroll period is a month: give its first day."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class EmployeeNominee(BaseModelWithUID):
    """0..n per employee. Σ share must be 100 ± 0.001 when any exist (§2.3)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="nominees")
    name = models.CharField(max_length=255)
    relation = _text(20, choices=RelationChoices.choices)
    nid = _text(32)
    share = models.DecimalField(max_digits=7, decimal_places=3)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")


class EmployeeStatutory(BaseModelWithUID):
    """The employee's own statutory particulars. Scheme MEMBERSHIP is not
    here: it is effective-dated per scheme in `paysetio.SchemeParticipation`
    (payroll settings §3.7), and the flags below read it. The gratuity basis
    and accrual method are the company's election and scheme, not a per-
    employee field."""

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="statutory")
    pf_number = _text(64)
    insurance_policy = _text(64)
    insurance_sum = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    insurer = _text()
    festival_granted = models.BooleanField(default=False)
    festival_reason = models.TextField(blank=True, default="")

    def _participation(self, code, on=None):
        from paysetio.services.ops import participation_in_force

        return participation_in_force(self.employee, code, on)

    @property
    def pf_member(self):
        return self._participation("PF") is not None

    @property
    def pf_enrolled(self):
        p = self._participation("PF")
        return p.enrolled_on if p else None

    @property
    def pf_employee(self):
        """The member's employee rate in percent: their own, else the fund's."""
        return self._pf_rate("override_rate_pct", "employeeRatePct")

    @property
    def pf_employer(self):
        return self._pf_rate("override_employer_rate_pct", "employerRatePct")

    def _pf_rate(self, own, fund):
        from paysetio.services.ops import scheme_config

        p = self._participation("PF")
        if p is None:
            return None
        rate = getattr(p, own)
        return rate if rate is not None else Decimal(scheme_config(self.employee.company, "PF")[fund])

    @property
    def gratuity_eligible(self):
        return self._participation("GRATUITY") is not None

    @property
    def insurance_covered(self):
        return self._participation("GROUP_INSURANCE") is not None


class EmployeeTaxProfile(BaseModelWithUID):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="tax_profile")
    # GENERAL is the law's default, not a guess: the other categories are claims
    # the employee has to make. The suggestion in services.tax never auto-applies.
    category = models.CharField(
        max_length=40,
        choices=TaxpayerCategoryChoices.choices,
        default=TaxpayerCategoryChoices.GENERAL,
    )
    disabled_children = models.PositiveSmallIntegerField(default=0)
    etin = _text(20)
    psr = models.BooleanField(default=False)
    psr_date = models.DateField(null=True, blank=True)
    vehicle = models.CharField(
        max_length=20, choices=VehicleChoices.choices, default=VehicleChoices.NONE
    )
    accommodation = models.BooleanField(default=False)
    accommodation_value = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    prior_employer = models.BooleanField(default=False)
    prior_name = _text()
    prior_income = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    prior_tds = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    tax_borne_by_employer = models.BooleanField(default=False)


class EmployeeInvestment(BaseModelWithUID):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="investments")
    instrument = models.CharField(max_length=40, choices=InstrumentChoices.choices)
    amount = models.DecimalField(**MONEY_FIELD)
    # Rebate qualification requires proof (§2.6).
    proof = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("position", "id")


class EmployeePaymentProfile(BaseModelWithUID):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="payment")
    method = models.CharField(
        max_length=20,
        choices=PaymentMethodChoices.choices,
        default=PaymentMethodChoices.BANK_TRANSFER,
    )
    cash_reason = models.TextField(blank=True, default="")
    bank = _text()
    branch = _text()
    routing = _text(20)
    account_name = _text()
    account_number = _text(40)
    account_type = _text(40)
    mfs_provider = _text(20, choices=MfsProviderChoices.choices)
    wallet_number = _text(20)
    wallet_type = _text(20, choices=WalletTypeChoices.choices)
    on_hold = models.BooleanField(default=False)
    hold_reason = models.TextField(blank=True, default="")
    hold_approver = _text()
    hold_since = models.DateField(null=True, blank=True)


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Change history is append-only. Record a correction as a new entry.")

    def delete(self):
        raise ValidationError("Change history is append-only. Record a correction as a new entry.")


class EmployeeFieldHistory(BaseModelWithUID):
    """One timeline entry `{field, date, from, to, by, reason}` (§8).

    Append-only: corrections are new entries, never edits. Deleting the
    employee still removes it (the cascade does not go through this queryset).
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="field_history")
    field = models.CharField(max_length=20, choices=TrackedFieldChoices.choices)
    # The date the change takes effect, not when it was recorded (`created_at`).
    date = models.DateField()
    from_value = _text()
    to_value = _text()
    by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    # The actor's name at the time, so the entry still reads after the user goes.
    by_name = _text()
    reason = models.TextField(blank=True, default="")

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ("-date", "-created_at", "-id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Change history is append-only. Record a correction as a new entry.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Change history is append-only. Record a correction as a new entry.")


class SalaryStructureQuerySet(models.QuerySet):
    def live(self):
        """Everything but cancelled structures: a cancelled scheduled change
        stays on file but was never in force."""
        return self.filter(cancelled_at__isnull=True)

    def in_force_on(self, on):
        return self.live().filter(effective_from__lte=on).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=on)
        )


class EmployeeSalaryStructure(BaseModelWithUID):
    """A salary structure in force from `effective_from` (§1.2, §5).

    A revision closes the previous structure (`effective_to`, `superseded_by`);
    it never overwrites it, so any period already paid on it stays reproducible.
    Assignment and revision: services.salary.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_structures")
    effective_from = models.DateField()
    # Inclusive. Null means in force until superseded.
    effective_to = models.DateField(null=True, blank=True)
    # RESTRICT, not PROTECT: a structure that superseded another cannot be
    # deleted on its own, but both go when the employee (or company) is deleted.
    superseded_by = models.OneToOneField(
        "self", on_delete=models.RESTRICT, null=True, blank=True, related_name="supersedes"
    )
    # A SalaryTemplateChoices id. Anything else is a structure the templates
    # did not build, which a revision has to be told how to rebuild.
    template = _text(40)
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    # How this structure came about. Blank on a first assignment.
    revision_type = _text(30, choices=RevisionTypeChoices.choices)
    method = _text(30, choices=RevisionMethodChoices.choices)
    # The consequence recorded when it was saved (§6.2): processed periods it
    # reopened ("YYYY-MM") and the arrears queued for them.
    reopened_periods = models.JSONField(default=list, blank=True)
    arrears = models.DecimalField(**MONEY_FIELD, default=ZERO)
    arrears_run = _text(20, choices=ArrearsRunChoices.choices)
    # The pay-library template version it was built on (null for structures
    # from before templates were rows, and the retired std/classic). PROTECT:
    # a template that has been used is never deleted.
    template_version = models.ForeignKey(
        "paylibio.StructureTemplate", on_delete=models.PROTECT, null=True, blank=True, related_name="structures"
    )
    # The labour rule set its floor and figures were checked against, so a
    # 2025 structure still reproduces after the 2026 rules change (§5.5).
    rule_set = models.ForeignKey(
        "rulebookio.RuleSet", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # The basic floor applied when it was written, and whether basic cleared
    # it. Null on structures from before this was recorded.
    grade_floor_applied = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    clears_floor = models.BooleanField(null=True, blank=True)
    # Recorded, not gated (yet): whoever saved it.
    approved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # A scheduled structure cancelled before it took effect. Kept, never deleted.
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.TextField(blank=True, default="")
    # A retried request with the same key returns this structure, not a second one.
    idempotency_key = _text(80)

    objects = SalaryStructureQuerySet.as_manager()

    class Meta:
        ordering = ("-effective_from",)
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="employeeio_salarystructure_window_not_inverted",
            ),
            models.UniqueConstraint(
                fields=["employee", "idempotency_key"], condition=~Q(idempotency_key=""),
                name="employeeio_salarystructure_idempotency_once",
            ),
        ]

    def status_on(self, today):
        """Derived from the dates and the cancellation (never stored)."""
        if self.cancelled_at is not None:
            return SalaryStatusChoices.CANCELLED
        if self.effective_from > today:
            return SalaryStatusChoices.SCHEDULED
        if self.effective_to is not None and self.effective_to < today:
            return SalaryStatusChoices.SUPERSEDED
        return SalaryStatusChoices.ACTIVE

    def component_amount(self, code):
        return self.components.filter(code=code).aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def gross(self):
        return self.components.aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def basic(self):
        return self.component_amount(SalaryComponentChoices.BASIC)


class EmployeeSalaryComponent(BaseModelWithUID):
    structure = models.ForeignKey(
        EmployeeSalaryStructure, on_delete=models.CASCADE, related_name="components"
    )
    code = models.CharField(max_length=10, choices=SalaryComponentChoices.choices)
    amount = models.DecimalField(**MONEY_FIELD)
    position = models.PositiveSmallIntegerField(default=0)
    # The basis as it reads: "60% of gross", "50% of basic", "Balance of gross".
    basis_text = _text(120)
    # What the template said for this line, for diffing (null when no template
    # built it: RMG, or a structure from before templates were rows). HRA's
    # is a percentage of basic; every other one is of gross.
    template_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    # Back-solved from the amounts on file (one decimal), on the same base.
    effective_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    # MEASURED on write: |effective - template| >= 0.5pp. Never a flag someone sets.
    is_overridden = models.BooleanField(default=False)
    is_balancing = models.BooleanField(default=False)
    # The pay-library component version this line was built on (components &
    # structures §9). Its bases are read from that version -- never from the
    # current one -- so a later flag change does not restate this line.
    component_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["structure", "code"], name="employeeio_salarycomponent_one_per_code"
            ),
            # A negative line is a deduction, which does not belong in a structure.
            models.CheckConstraint(condition=Q(amount__gte=0), name="employeeio_salarycomponent_not_negative"),
        ]


class SalaryOverride(BaseModelWithUID):
    """A deliberate deviation from the template: the recorded intent beside
    the component's measured `is_overridden` (§3.6). Carried forward to the
    next structure on a revision, so an override survives one."""

    structure = models.ForeignKey(EmployeeSalaryStructure, on_delete=models.CASCADE, related_name="overrides")
    component_code = models.CharField(max_length=10, choices=SalaryComponentChoices.choices)
    template_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    override_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    # The base of `override_pct`: of gross, or (house rent) of basic.
    of_basic = models.BooleanField(default=False)
    override_amount = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    reason = models.TextField()
    approved_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField()
    excluded_from_template_revision = models.BooleanField(default=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.CheckConstraint(
                condition=(Q(override_pct__isnull=False, override_amount__isnull=True)
                           | Q(override_pct__isnull=True, override_amount__isnull=False)),
                name="employeeio_salaryoverride_pct_or_amount",
            ),
            models.CheckConstraint(condition=~Q(reason=""), name="employeeio_salaryoverride_reason_present"),
        ]


class SalaryAudit(BaseModelWithUID):
    """Who did what to a salary, and who looked at one (§3.8). Viewing the
    figures is itself an audited event; so is the masked view, so an access
    review can tell "opened the screen" from "unmasked the figures".
    Append-only."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_audit")
    structure = models.ForeignKey(
        EmployeeSalaryStructure, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=20, choices=SalaryAuditActionChoices.choices)
    actor = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_name = _text()
    actor_role = _text(120)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    rule_set = models.ForeignKey(
        "rulebookio.RuleSet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    engine_version = models.CharField(max_length=40)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["employee", "-created_at"], name="employeeio_salaryaudit_emp_at")]
        # Role permissions (salary profile §7). The active company's admin
        # holds all three; anyone else needs them through a role.
        permissions = [
            ("view_salary_figures", "Can view salary figures"),
            ("write_salary", "Can assign, revise and override salary structures"),
            ("approve_salary", "Can approve a salary revision someone else raised"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The salary audit is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The salary audit is append-only.")


class EmployeeDocument(BaseModelWithUID):
    """A generated employee document (§9): the content as issued, frozen.

    Templates are data, never markup (`docs.js`): `content` is the filled
    template the client renders, so a reissue is a new row and the copy the
    employee holds can always be shown again. Append-only.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=30, choices=DocumentKindChoices.choices)
    # 1 for the first issue of this kind to this employee, then 2, 3, ...
    version = models.PositiveIntegerField()
    issued_on = models.DateField()
    issued_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    issued_by_name = _text()
    content = models.JSONField(default=dict)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ("kind", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "kind", "version"], name="employeeio_document_version_unique"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("An issued document is never edited. Reissue it.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("An issued document is never deleted. Reissue it.")
