from autoslug import AutoSlugField

from datetime import datetime

from phonenumber_field.modelfields import PhoneNumberField

from versatileimagefield.fields import VersatileImageField

from django.db.models import Sum
from django.utils import timezone
from django.db import models

from accounts.choices import UserGenderChoices

from addressio.models import Address

from common.models import BaseModelWithUID
from common.choices import CurrencyChoices
from common.django_rest.helpers.countries import COUNTRIES

from leaveio.choices import LeaveTypeChoice, EmployeeLeaveRequestStatusChoices

import uuid

from .choices import (
    EmployeeKindChoices,
    EmployeeStatusChoices,
    EmployeeLevelChoices,
    EmployeeSalaryKind,
    EmployeeSalaryStatusChoices,
    EmployeeNoticePeriodChoices,
    EmployeeTerminateKindChoices,
    EmployeeBankingInformationStatusChoices,
    EmployeeBankingInformationKindChoices,
    EmployeeEducationStatusChoices,
    EmployeeBankingInformationAccountKind,
    EmployeeTaxMartialChoicess,
    EmployeeTaxExemptChoicess,
    EmployeeTaxW4KindChoicess,
    EmployeeTaxHoldingStatusChoicess,
    EmployeePayKindChoices,
    EmployeeSalaryFrequencyChoices,
    EmployeeEarningStatusChoices,
    EmployeeEarningPayKindChoices,
    EmployeeDeductionContributionKindChoices,
    EmployeeDeductionContributionStatusChoices,
    EmployeeDeductionContributionKindChoices,
    EmployeeGarnishmentStatusChoices,
    EmployeeGarnishmentKindChoices,
    EmployeeWorkExperienceStatusChoices,
    EmployeeWorkExperienceKindChoices,
    EmployeeOnboardingKindChoices,
    EmployeeCitizenshipKindChoices,
    EmployeeExpenseReportStatusChoices,
)

from .managers import EmployeeSalaryQuerySet

from .django_rest.helpers.slug_helpers import (
    get_employee_slug,
    get_employee_salary_slug,
    get_employee_banking_information_slug,
    get_employee_education,
    get_employee_tax,
    get_employee_earning_tax,
    get_employee_deduction_and_contribution,
    get_employee_work_experience_slug,
    get_employee_expense_report_slug,
)


class Employee(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_employee_slug, unique=True, db_index=True)

    # Profile fields. These mirror their counterparts on `accounts.User` but live
    # independently here so that updating the employee record does not mutate the
    # user's login profile (and vice versa). All are nullable; on creation the
    # admin's input is copied to BOTH User and Employee, then the two diverge.
    first_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=250, blank=True, null=True)
    salutation = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=10, null=True, blank=True)
    gender = models.CharField(
        max_length=50,
        choices=UserGenderChoices.choices,
        db_index=True,
        blank=True,
        null=True,
    )
    nid_card_no = models.CharField(max_length=50, null=True, blank=True)
    ssn = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(
        max_length=2, choices=COUNTRIES, blank=True, null=True, db_index=True
    )
    description = models.TextField(blank=True, null=True)

    father_name = models.CharField(max_length=255, null=True, blank=True)
    work_locations = models.ForeignKey(
        "payrollio.PayrollWorkLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    code = models.CharField(max_length=50, null=True, blank=True)
    employee_id = models.CharField(max_length=50, null=True, blank=True)
    finger_id = models.CharField(max_length=50, null=True, blank=True)
    kind = models.CharField(
        max_length=50,
        choices=EmployeeKindChoices,
        default=EmployeeKindChoices.FULL_TIME,
    )
    on_boarding_kind = models.CharField(
        max_length=50,
        choices=EmployeeOnboardingKindChoices,
        default=EmployeeOnboardingKindChoices.MANUAL_ENTRY,
    )
    level = models.CharField(
        max_length=50, choices=EmployeeLevelChoices, blank=True, null=True
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeStatusChoices,
        default=EmployeeStatusChoices.DRAFT,
    )
    is_over_time = models.BooleanField(default=False)
    company_phone_number = PhoneNumberField(blank=True, null=True)
    company_email = models.EmailField(blank=True, null=True)
    # True once the employee has successfully completed their onboarding pipeline.
    is_joined = models.BooleanField(default=False)
    # Whether this employee is allowed to authenticate / log in. SELF_ONBOARD and
    # SELF_ONBOARD_WITH_I9 employees are granted access automatically on creation;
    # MANUAL_ENTRY employees stay disabled until an admin sends an invitation
    # (approve), and access can be turned off later (revoke) without deleting the
    # record. Non-employee users are not affected by this flag.
    is_access_enabled = models.BooleanField(default=False)

    # Contact information
    phone_number = PhoneNumberField(blank=True, null=True)
    home_phone_number = PhoneNumberField(blank=True, null=True)
    personal_email = models.EmailField(blank=True, null=True)
    preferred_email = models.EmailField(blank=True, null=True)

    # Emargency contact information
    emergency_contact_name = models.CharField(max_length=255, null=True, blank=True)
    emergency_contact_relationship = models.CharField(
        max_length=100, null=True, blank=True
    )
    emergency_phone_number = PhoneNumberField(blank=True, null=True)

    # Hiring information
    confirmation_date = models.DateField(default=timezone.now, null=True, blank=True)
    notice_period = models.CharField(
        max_length=50,
        choices=EmployeeNoticePeriodChoices,
        default=EmployeeNoticePeriodChoices.FIFTEEN_DAYS,
    )
    offer_date = models.DateField(default=timezone.now, null=True, blank=True)
    contract_end_date = models.DateField(null=True, blank=True)

    # Terminate information
    terminate_date = models.DateField(default=timezone.now, null=True, blank=True)
    last_date_of_work = models.DateField(default=timezone.now, null=True, blank=True)
    terminate_kind = models.CharField(
        max_length=50,
        choices=EmployeeTerminateKindChoices,
        default=EmployeeTerminateKindChoices.FULL,
    )
    terminate_description = models.TextField(blank=True, null=True)

    # Attendance related
    attendance_device_id = models.CharField(max_length=100, blank=True, null=True)

    # Payroll information
    pay_kind = models.CharField(
        max_length=50,
        choices=EmployeePayKindChoices,
        default=EmployeePayKindChoices.SALARY,
    )
    is_double_over_time = models.BooleanField(default=False)
    is_holiday_pay = models.BooleanField(default=False)
    is_bonus = models.BooleanField(default=False)
    is_same_address = models.BooleanField(default=False)
    is_banking_info_verified = models.BooleanField(default=False)
    salary_frequency = models.CharField(
        max_length=50,
        choices=EmployeeSalaryFrequencyChoices,
        default=EmployeeSalaryFrequencyChoices.PER_MONTH,
    )
    total_salary = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_hour_per_day = models.CharField(max_length=100, blank=True, null=True)
    total_day_per_week = models.CharField(max_length=100, blank=True, null=True)
    total_rate_per_hour = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )

    # Eligibility
    citizenship_kind = models.CharField(
        max_length=50,
        choices=EmployeeCitizenshipKindChoices,
        default=EmployeeCitizenshipKindChoices.OTHER,
    )
    uscis_or_alien_registration_number = models.CharField(
        max_length=100, blank=True, null=True
    )
    from_i_94 = models.CharField(max_length=100, blank=True, null=True)
    foreign_passport = models.CharField(max_length=100, blank=True, null=True)
    w4_signature = VersatileImageField(
        "Signature", upload_to="employee/signatures", blank=True, null=True
    )
    authorized_to_work_until = models.DateField(blank=True, null=True)
    is_not_applicable = models.BooleanField(default=False)
    is_included_social_security_number_from_i9 = models.BooleanField(default=False)
    image = VersatileImageField(
        "Image", upload_to="media/employees", blank=True, null=True
    )    

    # FK
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    # The company this employee record belongs to. A single user can be an
    # employee of several companies; each membership is a distinct Employee row
    # scoped by this FK. Nullable only to allow a safe backfill migration of
    # legacy rows -- new rows must always set it.
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employees",
    )
    report_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True
    )
    department = models.ForeignKey(
        "companyio.CompanyDepartment", on_delete=models.SET_NULL, null=True, blank=True
    )
    designation = models.ForeignKey(
        "companyio.CompanyDesignation", on_delete=models.SET_NULL, null=True, blank=True
    )
    shift = models.ForeignKey(
        "companyio.CompanyShift", on_delete=models.SET_NULL, null=True, blank=True
    )
    pay_schedule = models.ForeignKey(
        "payrollio.PaySchedule", on_delete=models.SET_NULL, null=True, blank=True
    )
    holiday = models.ForeignKey(
        "attendanceio.Holiday",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_set",
    )

    def __str__(self):
        return f"ID: {self.id}, Name: {self.user.name}"

    @property
    def full_name(self):
        return self.user.name

    def get_salary(self):
        return self.employeesalary_set.filter().first()

    def get_image(self):
        return self.user.image

    def get_bank_information(self):
        return self.employeebankinginformation_set.first()

    def get_worked_hours(self, dates=None):
        attendances = self.attendance_set
        if dates:
            attendances = attendances.filter(date__range=dates)
        return (
            attendances.aggregate(Sum("worked_hour_count"))["worked_hour_count__sum"]
            or 0
        )

    def get_company_role(self):
        company_user = self.user.companyuser_set.prefetch_related("roles").first()
        if not company_user:
            return None
        return company_user.roles.first()

    def get_company_roles(self):
        company_user = self.user.companyuser_set.prefetch_related("roles").first()
        if not company_user:
            return []
        return list(company_user.roles.all())

    def get_company(self):
        # Prefer the explicit per-employee company; fall back to the user's
        # active company for legacy rows that predate the company FK backfill.
        return self.company or self.user.get_active_company()

    def get_company_address(self):
        company = self.get_company()
        return company.company_addresses if company else None

    def get_addresses(self):
        return Address.objects.filter(addressconnector__employee=self)

    def get_banking_informations(self):
        return self.employeebankinginformation_set

    def get_taxes(self):
        return self.employeetax_set

    def get_first_tax(self):
        return self.employeetax_set.first()

    def get_paid_or_un_paid_leave_hour_count(self, dates=None, filters=None):
        hour_count = 0
        if dates:
            if employee_leave_allocation := (
                self.employeeleaveallocation_set.filter(
                    leave_year=int(datetime.strptime(dates[0], "%Y-%m-%d").year),
                    **filters,
                ).first()
            ):
                leave_requests = (
                    self.leaverequest_set.filter(
                        status=EmployeeLeaveRequestStatusChoices.APPROVED,
                        from_date=dates[0],
                        to_date=dates[1],
                    )
                    .distinct()
                    .select_related("employee_shift")
                )
                if (
                    employee_leave_allocation.leave_type.leave_type
                    == LeaveTypeChoice.DAILY
                ):
                    hour_count = sum(
                        leave_request.total_days
                        * leave_request.employee_shift.get_workable_hour()
                        for leave_request in leave_requests
                        if leave_request.employee_shift
                    )
                else:
                    hour_count = sum(
                        leave_request.total_days
                        * employee_leave_allocation.leave_type.maximum_allocation_hours
                        for leave_request in leave_requests
                    )
        return hour_count

    def get_un_paid_leave_hour_count(self, dates=None):
        return self.get_paid_or_un_paid_leave_hour_count(
            dates,
            {
                "leave_type__is_leave_without_pay": True,
            },
        )

    def get_paid_leave_hour_count(self, dates=None):
        return self.get_paid_or_un_paid_leave_hour_count(
            dates,
            {
                "leave_type__is_partially_paid": False,
                "leave_type__is_leave_without_pay": False,
            },
        )

    def get_workable_hour_count(self, dates=None):
        attendances = self.attendance_set.all()
        if dates:
            attendances = attendances.filter(date__range=dates)
        return sum(
            attendance.shift.get_workable_hour()
            for attendance in attendances.select_related("shift")
            if attendance.shift
        )

    def get_difference_hour_count(self, dates=None):
        return self.get_worked_hours(dates) - self.get_workable_hour_count(dates)

    def get_ot_hour_count(self, dates=None):
        difference_hour_count = self.get_difference_hour_count(dates)
        return difference_hour_count if difference_hour_count > 0 else 0

    def get_partial_paid_leave_hour_count(self, dates=None):
        return self.get_paid_or_un_paid_leave_hour_count(
            dates,
            {
                "leave_type__is_partially_paid": True,
            },
        )

    def get_leave_requests(self, dates=None):
        leave_requests = self.leaverequest_set
        if dates:
            leave_requests = leave_requests.filter(from_date=dates[0], to_date=dates[1])
        return leave_requests

    def get_banking_information(self):
        return self.employeebankinginformation_set

    def get_deduction_and_contibution(self):
        return self.employeedeductioncontribution_set


class EmployeeSalary(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_salary_slug, unique=True, db_index=True
    )
    gross = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    basic = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    house_rent = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    medical_allowance = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    transport_allowance = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    food_allowance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    other_allowance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    grade_bonus = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    mobile_allowance = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    skill_bonus = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    management_bonus = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    special_allowance = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    tiffin_allowance = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    night_allowance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    income_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    lunch_deduction = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    cash_provident_fund = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    cash = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    over_time_rate = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    kind = models.CharField(
        choices=EmployeeSalaryKind,
        default=EmployeeSalaryKind.CHEQUE,
        max_length=20,
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeSalaryStatusChoices,
        default=EmployeeSalaryStatusChoices.DRAFT,
    )
    objects = EmployeeSalaryQuerySet.as_manager()

    # Fk
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, null=True, blank=True
    )
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, Name: {self.employee}, Total: {self.total}"


class EmployeeBankingInformation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_banking_information_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeBankingInformationStatusChoices,
        default=EmployeeBankingInformationStatusChoices.DRAFT,
        db_index=True,
    )
    kind = models.CharField(
        max_length=50,
        choices=EmployeeBankingInformationKindChoices,
        default=EmployeeBankingInformationKindChoices.BANK_TRANSFER,
        db_index=True,
    )
    currency = models.CharField(
        max_length=50, choices=CurrencyChoices, default=CurrencyChoices.USD
    )
    payment_date = models.DateField(default=timezone.now, null=True, blank=True)

    # For Bank Transfer
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    bank_account_type = models.CharField(
        max_length=50,
        choices=EmployeeBankingInformationAccountKind,
        blank=True,
        null=True,
    )
    bank_account_number = models.CharField(max_length=100, null=True, blank=True)
    bank_account_holder_name = models.CharField(max_length=100, null=True, blank=True)
    routing_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Bank routing number (e.g., ABA, SWIFT, or sort code)",
    )
    iban = models.CharField(max_length=100, blank=True, null=True)

    # For Paper Check
    check_number = models.CharField(max_length=50, null=True, blank=True)
    check_issued_date = models.DateField(null=True, blank=True)

    # For Mobile Payment / Digital Wallet
    mobile_wallet_provider = models.CharField(max_length=50, null=True, blank=True)
    mobile_wallet_number = models.CharField(max_length=20, null=True, blank=True)
    # FK
    employee = models.ForeignKey(
        "employeeio.Employee", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID:{self.id}, Kind:{self.kind}, Employee:{self.employee}"


class EmployeeEducation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_education, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeEducationStatusChoices,
        default=EmployeeEducationStatusChoices.DRAFT,
    )
    institute_name = models.CharField(max_length=200, blank=True, null=True)
    degree = models.CharField(max_length=200, blank=True, null=True)
    level = models.CharField(max_length=100, blank=True, null=True)
    passing_year = models.CharField(max_length=50, blank=True, null=True)
    grade = models.CharField(max_length=100, blank=True, null=True)

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID:{self.id}, Kind:{self.status}, Employee:{self.employee}"


class EmployeeWorkExperience(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_work_experience_slug,
        unique=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeWorkExperienceStatusChoices,
        default=EmployeeWorkExperienceStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50,
        choices=EmployeeWorkExperienceKindChoices,
        default=EmployeeWorkExperienceKindChoices.EXPERIENCE,
    )
    company_name = models.CharField(max_length=100, blank=True, null=True)
    branch_name = models.CharField(max_length=100, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    total_salary = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    full_address = models.TextField(blank=True, null=True)

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID:{self.id}, Status:{self.status}, Kind:{self.kind}, Employee:{self.employee}"


class EmployeeTax(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_employee_tax, unique=True, db_index=True)

    # State other income tax
    is_the_state_other_income_tax = models.BooleanField(default=False)
    state = models.CharField(max_length=100, blank=True, null=True)
    martial_status = models.CharField(
        max_length=50,
        choices=EmployeeTaxMartialChoicess,
        default=EmployeeTaxMartialChoicess.UN_MARRIED,
    )
    total_allowance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    additional_with_holdings = models.CharField(max_length=100, blank=True, null=True)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    exempt = models.CharField(
        max_length=100, choices=EmployeeTaxExemptChoicess, blank=True, null=True
    )
    is_the_employee_exempt_from_any_state_taxes = models.BooleanField(default=False)
    is_the_employee_work_in_the_state_where_live = models.BooleanField(default=False)

    # Federal With Holdings
    is_federal_with_holding = models.BooleanField(default=False)
    employee_W_4_kind = models.CharField(
        max_length=100, choices=EmployeeTaxW4KindChoicess, blank=True, null=True
    )
    is_multiple_jobs_or_spouse_works = models.BooleanField(default=False)
    total_other_income = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    extra_with_holding = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    holding_status = models.CharField(
        choices=EmployeeTaxHoldingStatusChoicess,
        blank=True,
        null=True,
        max_length=50,
    )
    claim_depends = models.CharField(max_length=250, blank=True, null=True)
    deduction = models.CharField(max_length=100, blank=True, null=True)
    exempt_from_with_holding = models.CharField(max_length=100, blank=True, null=True)
    is_employee_exempt_from_federal_tax = models.BooleanField(default=True)
    is_employee_exempt_from_family_paid_leave = models.BooleanField(default=False)
    exempt_fields = models.JSONField(default=dict, blank=True, null=True)
    children_under_17 = models.IntegerField(blank=True, null=True)
    other_dependents = models.IntegerField(blank=True, null=True)
    other_tax_credits = models.IntegerField(blank=True, null=True)
    children_amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    dependent_amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_credits = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID:{self.id}, Employee:{self.employee}"


class EmployeeEarning(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_earning_tax, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeEarningStatusChoices,
        default=EmployeeEarningStatusChoices.DRAFT,
    )
    pay_kind = models.CharField(
        max_length=50,
        choices=EmployeeEarningPayKindChoices,
        default=EmployeeEarningPayKindChoices.ALLOWANCE,
    )

    total_recurring_amount = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    description = models.TextField(blank=True, null=True)

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID:{self.id}, Pay kind:{self.pay_kind}, Employee:{self.employee}"


class EmployeeDeductionContribution(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_deduction_and_contribution,
        unique=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeDeductionContributionStatusChoices,
        default=EmployeeDeductionContributionStatusChoices.DRAFT,
    )
    tax_option = models.CharField(max_length=255, blank=True, null=True)

    # Employee deduction
    employee_deduction_kind = models.CharField(
        max_length=50,
        choices=EmployeeDeductionContributionKindChoices,
        default=EmployeeDeductionContributionKindChoices.FLAT_AMOUNT,
    )
    total_employee_deduction_per_pay_check = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    total_maximum_annual_employee_deduction = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )

    # Company contribution
    company_contribution_kind = models.CharField(
        max_length=50,
        choices=EmployeeDeductionContributionKindChoices,
        default=EmployeeDeductionContributionKindChoices.FLAT_AMOUNT,
    )
    total_company_contribution_per_pay_check = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    total_maximum_annual_company_contribution = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    deduction_and_contribution = models.ForeignKey(
        "payrollio.DeductionAndContributions",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"ID:{self.id}, Status:{self.status}, Employee:{self.employee}"


class EmployeeGarnishment(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_deduction_and_contribution,
        unique=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeGarnishmentStatusChoices,
        default=EmployeeGarnishmentStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50,
        choices=EmployeeGarnishmentKindChoices,
        default=EmployeeGarnishmentKindChoices.OTHER_GARNISHMENT,
    )
    description = models.TextField(blank=True, null=True)
    total_requsted_amount = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )
    total_maximum_percentage_of_disposal_income = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3
    )

    # FK
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID:{self.id}, Status:{self.status}, Kind:{self.kind}, Employee:{self.employee}"


def get_employee_expense_report_receipt_path(instance, filename):
    ext = filename.split(".")[-1] if "." in filename else "jpg"
    return f"employee_expense_receipts/{instance.employee_id}/{instance.uid}/{uuid.uuid4().hex[:8]}.{ext}"


class EmployeeExpenseReport(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_employee_expense_report_slug,
        unique=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=50,
        choices=EmployeeExpenseReportStatusChoices,
        default=EmployeeExpenseReportStatusChoices.DRAFT,
    )

    receipt = models.FileField(
        upload_to=get_employee_expense_report_receipt_path,
        blank=True,
        null=True,
    )
    ocr_processed = models.BooleanField(default=False)

    amount = models.DecimalField(
        default=0.00,
        max_digits=19,
        decimal_places=3,
    )
    currency = models.CharField(
        max_length=50,
        default="USD",
        blank=True,
        null=True,
    )

    vendor_supplier_name = models.CharField(max_length=255, blank=True, null=True)
    supplier = models.ForeignKey(
        "supplierio.Supplier",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee_expense_reports",
    )

    expense_date = models.DateField(default=timezone.now, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    reference_number = models.CharField(max_length=100, blank=True, null=True)

    chart_of_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee_expense_reports",
    )

    ocr_data = models.JSONField(blank=True, null=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="expense_reports",
    )
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="employee_expense_reports",
        blank=True,
        null=True,
    )
    submitted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="submitted_expense_reports",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_expense_reports",
    )
    paid_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="paid_expense_reports",
    )
    rejected_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="rejected_expense_reports",
    )
    file_path = models.URLField(blank=True, null=True)
    status_previous = models.CharField(
        max_length=50,
        choices=EmployeeExpenseReportStatusChoices,
        blank=True,
        null=True,
    )
    purchase = models.ForeignKey(
        "purchaseio.Purchase",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee_expense_reports",
    )
    payment_date = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Expense Report #{self.uid} - {self.employee} - {self.amount}"
