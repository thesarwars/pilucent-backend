"""The BD employee profile (`docs/employee-profile.md`).

Tenancy: these tables have no RLS. Every read is scoped by `company` in the
application -- directly on `Employee`, and through `employee__company` on
every sub-record, none of which carries a company of its own.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q, Sum

from common.models import BaseModelWithUID
from common.money import MONEY_FIELD, ZERO

from .choices import (
    BloodGroupChoices,
    ClassificationChoices,
    DivisionChoices,
    EmployeeStatusChoices,
    EmploymentTypeChoices,
    EstablishmentChoices,
    GenderChoices,
    GradeChoices,
    GratuityBasisChoices,
    GratuityMethodChoices,
    InstrumentChoices,
    MaritalChoices,
    MfsProviderChoices,
    PaymentMethodChoices,
    RelationChoices,
    ReligionChoices,
    SalaryComponentChoices,
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


class Employee(BaseModelWithUID):
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, related_name="employees"
    )
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
        """Payroll runs completed for this employee. Derived, read-only.

        0 until the BD payroll phase records runs -- there are none to count.
        """
        return 0

    @property
    def settlement_outstanding(self):
        return bool(self.separated_on) and not self.final_settlement_on


class CompanyStatutoryProfile(BaseModelWithUID):
    """Company-level statutory facts the employee profile is gated by (§2.4)."""

    company = models.OneToOneField(
        "companyio.Company", on_delete=models.CASCADE, related_name="bd_statutory_profile"
    )
    # When false, provident-fund membership cannot be switched on for anyone.
    pf_constituted = models.BooleanField(default=False)


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
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="statutory")
    pf_member = models.BooleanField(default=False)
    pf_number = _text(64)
    pf_enrolled = models.DateField(null=True, blank=True)
    pf_employee = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pf_employer = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    gratuity_eligible = models.BooleanField(default=False)
    gratuity_basis = _text(10, choices=GratuityBasisChoices.choices)
    gratuity_method = _text(20, choices=GratuityMethodChoices.choices)
    gratuity_fund = _text()
    insurance_covered = models.BooleanField(default=False)
    insurance_policy = _text(64)
    insurance_sum = models.DecimalField(**MONEY_FIELD, null=True, blank=True)
    insurer = _text()
    festival_granted = models.BooleanField(default=False)
    festival_reason = models.TextField(blank=True, default="")


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
    def in_force_on(self, on):
        return self.filter(effective_from__lte=on).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=on)
        )


class EmployeeSalaryStructure(BaseModelWithUID):
    """A salary structure in force from `effective_from` (§1.2, §5).

    A revision closes the previous structure (`effective_to`, `superseded_by`);
    it never overwrites it, so any period already paid on it stays reproducible.
    Phase 1 reads structures; assignment and revision land with Phase 2.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_structures")
    effective_from = models.DateField()
    # Inclusive. Null means in force until superseded.
    effective_to = models.DateField(null=True, blank=True)
    superseded_by = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="supersedes"
    )
    template = _text(40)
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)

    objects = SalaryStructureQuerySet.as_manager()

    class Meta:
        ordering = ("-effective_from",)
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="employeeio_salarystructure_window_not_inverted",
            ),
        ]

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

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["structure", "code"], name="employeeio_salarycomponent_one_per_code"
            ),
        ]
