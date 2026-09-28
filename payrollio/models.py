from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID, BaseModelWithoutTitle

from .choicess import (
    SalaryAdjustmentStatusChoices,
    SalaryAdjustmentKindChoices,
    DeductionAndContributionChoices,
    PayScheduleStatusChoice,
    PayScheduleMonthChoice,
    PayFrequencyChoice,
    EndDayChoice,
    SalaryProcessPayMethodChoice,
    PayrollSalaryProcessStatusChoices,
    PayrollComponentCategoryChoice,
    PayrollGeneralTaxCompanyTypeChoices,
    PayrollFederalTaxInfoSettingChoices,
    PayrollFederalTaxInfoTaxFormChoices,
    PayrollStateTaxInfoSettingChoices,
    PayrollStateMCTMTZoneChoices,
    PayrollWorkLocationChoices,
    AccountingPreferencesExpenseTypeChoices,
    PayrollGeneralSettingsWorkingChoices,
    PayrollGeneralSettingsEmailTemplateChoices,
    PayrollTaxConfigStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_salary_adjustment_slug,
    get_dedcon_slug,
    get_pay_schedule_slug,
    get_payroll_salary_process_slug,
    get_payroll_general_tax_setting_slug,
    get_payroll_federal_tax_info_setting_slug,
    get_payroll_state_tax_info_setting_slug,
    get_payroll_salary_component_slug,
    get_payroll_work_location_slug,
    get_payroll_accounting_preferences_slug,
    get_payroll_general_tax_setting_slug,
    get_payroll_contact_info_setting_slug,
)
from .managers import (
    SalaryAdjustmentManager,
    PayScheduleQueryset,
    PayrollWorkLocationQueryset,
)


class SalaryAdjustment(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_salary_adjustment_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=SalaryAdjustmentStatusChoices,
        default=SalaryAdjustmentStatusChoices.DRAFT,
    )
    kind = models.CharField(max_length=50, choices=SalaryAdjustmentKindChoices)
    join_date = models.DateField(blank=True, null=True)
    input_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    remark = models.TextField(blank=True, null=True)

    # FK
    employee = models.ForeignKey("employeeio.Employee", on_delete=models.CASCADE)

    objects = SalaryAdjustmentManager()

    def __str__(self):
        return f"ID: {self.id}, Name: {self.employee.user.name}, Kind: {self.kind}"

    class Meta:
        verbose_name = "Salary Adjustment"


class DeductionAndContributions(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_dedcon_slug, unique=True, db_index=True)
    deduction_type = models.CharField(max_length=255)
    sub_type = models.CharField(max_length=255)
    tax_type = models.CharField(
        max_length=10, choices=DeductionAndContributionChoices, blank=True, null=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = "Deduction and Contribution"


class PaySchedule(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_pay_schedule_slug, unique=True, db_index=True
    )
    pay_frequency = models.CharField(max_length=255, choices=PayFrequencyChoice)
    status = models.CharField(
        max_length=10,
        choices=PayScheduleStatusChoice,
        default=PayScheduleStatusChoice.ACTIVE,
    )
    is_default = models.BooleanField(default=False, db_index=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    # Fields for semi-monthly/monthly (first and second period)
    first_payday = models.CharField(max_length=15, null=True, blank=True)
    first_end_day = models.CharField(
        max_length=20, null=True, blank=True, choices=EndDayChoice
    )
    first_month = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        default=PayScheduleMonthChoice.SAME,
        choices=PayScheduleMonthChoice,
    )
    first_day = models.CharField(max_length=15, null=True, blank=True)

    second_payday = models.CharField(max_length=15, null=True, blank=True)
    second_end_day = models.CharField(
        max_length=20, null=True, blank=True, choices=EndDayChoice
    )
    second_month = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        default=PayScheduleMonthChoice.SAME,
        choices=PayScheduleMonthChoice,
    )
    second_day = models.CharField(max_length=15, null=True, blank=True)

    # Fields for weekly.
    next_pay_date = models.DateField(null=True, blank=True)
    end_of_next_pay_period = models.DateField(null=True, blank=True)

    objects = PayScheduleQueryset.as_manager()

    def __str__(self):
        return f"title: {self.title} frequency: {self.pay_frequency}"

    class Meta:
        verbose_name_plural = "Pay Schedule"


class PayrollSalaryProcess(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_salary_process_slug, unique=True, db_index=True
    )
    employee = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.DO_NOTHING,
        related_name="employee_salary",
    )
    schedule_name = models.CharField(max_length=255, blank=True, null=True)
    pay_date = models.DateField()
    pay_period = models.CharField(max_length=25)
    funding_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        related_name="payroll_funding_account",
    )
    payment_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.DO_NOTHING,
        related_name="payroll_payment_account",
    )
    pay_method = models.CharField(max_length=15, choices=SalaryProcessPayMethodChoice)
    project = models.CharField(max_length=255, blank=True, null=True)
    memo = models.TextField(blank=True, null=True)
    accrue_time_off = models.BooleanField(default=False)
    gross_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employee_taxes_deductions = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    employer_taxes_contributions = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_salary_done = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=PayrollSalaryProcessStatusChoices.choices,
        default=PayrollSalaryProcessStatusChoices.DRAFT,
        db_index=True,
        help_text=(
            "Lifecycle of the run. Only FINALIZED rows count toward YTD and "
            "wage-cap enforcement. Voided rows are excluded so reversals "
            "automatically subtract from cumulative totals."
        ),
    )

    def __str__(self):
        return f"employee_name: {self.employee.user.name}"


class PayrollSalaryComponent(BaseModelWithoutTitle):
    slug = AutoSlugField(
        populate_from=get_payroll_salary_component_slug,
        unique=True,
        db_index=True,
        null=True,
    )
    payroll = models.ForeignKey(
        PayrollSalaryProcess,
        on_delete=models.CASCADE,
        related_name="payroll_components",
    )
    payroll_type = models.CharField(max_length=255)
    payroll_category = models.CharField(
        max_length=155, choices=PayrollComponentCategoryChoice
    )
    current = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ytd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hours = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, blank=True, null=True
    )
    rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, blank=True, null=True
    )


class PayrollGeneralTaxSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_general_tax_setting_slug, unique=True, db_index=True
    )
    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    zip_code = models.CharField(max_length=20, blank=True, null=True)
    company_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        choices=PayrollGeneralTaxCompanyTypeChoices,
        default=PayrollGeneralTaxCompanyTypeChoices.OTHER,
    )
    ein_number = models.CharField(
        max_length=20, blank=True, null=True, verbose_name="EIN Number"
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                name="unique_payroll_general_tax_setting_per_company",
            ),
        ]

    def __str__(self):
        return f"ID: {self.id}, Company: {self.company.name}, Type: {self.company_type}"


class PayrollFederalTaxInfoSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_federal_tax_info_setting_slug,
        unique=True,
        db_index=True,
    )
    ein_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, EIN: {self.ein_number}, Company: {self.company.name}"


class PayrollFederalTaxInfoSettingItems(BaseModelWithoutTitle):
    payroll_federal_tax_info = models.ForeignKey(
        PayrollFederalTaxInfoSetting,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="items",
    )
    tax_form = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=PayrollFederalTaxInfoTaxFormChoices,
    )
    payment_frequency = models.CharField(
        max_length=20, choices=PayrollFederalTaxInfoSettingChoices
    )
    effective_date = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payroll_federal_tax_info", "tax_form", "effective_date"],
                name="uniq_federal_tax_item_form_effective_date",
                condition=models.Q(tax_form__isnull=False),
            ),
        ]

    def __str__(self):
        return f"Tax Form: {self.tax_form}, Frequency: {self.payment_frequency}"


class PayrollStateTaxInfoSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_state_tax_info_setting_slug,
        unique=True,
        db_index=True,
    )
    state = models.CharField(max_length=100, blank=True, null=True)
    win_number = models.CharField(
        max_length=15,
        unique=True,
        blank=True,
        null=True,
        verbose_name="WIN Number",
    )
    ui_registration_number = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="UI Registration Number"
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, State: {self.state}, WIN: {self.win_number}"


# New model for multiple payment schedules per state tax info
class PayrollStateTaxPaymentSchedule(BaseModelWithUID):
    payroll_state_tax_info = models.ForeignKey(
        PayrollStateTaxInfoSetting,
        on_delete=models.CASCADE,
        related_name="payment_schedules",
    )
    payment_frequency = models.CharField(
        max_length=20,
        choices=PayrollStateTaxInfoSettingChoices,
        blank=True,
        null=True,
    )
    effective_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"StateTaxInfoID: {self.payroll_state_tax_info.id}, Frequency: {self.payment_frequency}, Effective: {self.effective_date}"


class PayrollUnemploymentInsuranceTaxInfo(BaseModelWithUID):
    payroll_state_tax_info = models.ForeignKey(
        PayrollStateTaxInfoSetting,
        on_delete=models.CASCADE,
        related_name="unemployment_insurance",
    )
    ui_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=0, verbose_name="UI Rate"
    )
    effective_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"StateTaxInfoID: {self.payroll_state_tax_info.id}, UI Rate: {self.ui_rate}, Effective: {self.effective_date}"


class PayrollFederalLoanInterestPaymentSchedule(BaseModelWithUID):
    payroll_state_tax_info = models.ForeignKey(
        PayrollStateTaxInfoSetting,
        on_delete=models.CASCADE,
        related_name="federal_loan_interest_payment_schedules",
    )
    ui_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0,
        verbose_name="Federal Loan Interest Rate",
    )
    effective_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"StateTaxInfoID: {self.payroll_state_tax_info.id}, Federal Loan Interest Rate: {self.ui_rate}, Effective: {self.effective_date}"


# New model for Reemployment Service Fund rate
class PayrollReemploymentOrWorkforceServiceFund(BaseModelWithUID):
    payroll_state_tax_info = models.ForeignKey(
        PayrollStateTaxInfoSetting,
        on_delete=models.CASCADE,
        related_name="reemployment_service_funds",
    )
    reemployment_or_workforce_fund_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0,
        verbose_name="Reemployment Service Fund Rate",
    )
    effective_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"StateTaxInfoID: {self.payroll_state_tax_info.id}, Reemployment Fund Rate: {self.reemployment_or_workforce_fund_rate}, Effective: {self.effective_date}"


# model for Metropolitan Commuter Transportation Mobility Tax (MCTMT)
class PayrollMCTMTZone(BaseModelWithUID):
    payroll_state_tax_info = models.ForeignKey(
        PayrollStateTaxInfoSetting,
        on_delete=models.CASCADE,
        related_name="mctmt_zones",
    )
    zone = models.CharField(
        max_length=10,
        choices=PayrollStateMCTMTZoneChoices,
        verbose_name="Metropolitan Commuter Transportation Mobility Tax Zone",
    )
    mctmt_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0,
        verbose_name="Metropolitan Commuter Transportation Mobility Tax Rate",
    )
    effective_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"StateTaxInfoID: {self.payroll_state_tax_info.id}, Zone: {self.zone}, MCTMT Rate: {self.mctmt_rate}, Effective: {self.effective_date}"


class PayrollWorkLocation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_work_location_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=PayrollWorkLocationChoices,
        default=PayrollWorkLocationChoices.DRAFT,
    )
    location_address = models.CharField(max_length=255, blank=True, null=True)
    location_city = models.CharField(max_length=100, blank=True, null=True)
    location_state = models.CharField(max_length=100, blank=True, null=True)
    location_zip = models.CharField(max_length=10, blank=True, null=True)
    is_primary = models.BooleanField(default=False, db_index=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = PayrollWorkLocationQueryset.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_primary=True),
                name="unique_primary_payroll_work_location_per_company",
            ),
        ]

    created_by = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_location_created_by",
    )

    def __str__(self):
        return f"WorkLocation: {self.location_address}, {self.location_city}, {self.location_state}, {self.location_zip}"


class PayrollAccountingPreferencesSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_accounting_preferences_slug,
        unique=True,
        db_index=True,
    )
    paycheck_payroll_tax_expense_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="payroll_tax_expense_account",
    )
    global_wage_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="global_wage_account",
    )
    global_contribution_expense_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="global_contribution_expense_account",
    )
    global_employer_tax_expenses = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="global_employer_tax_expenses",
    )
    wage_expense_type = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        default=AccountingPreferencesExpenseTypeChoices.SINGLE_WAGE_ACCOUNT,
    )
    company_contribution_expense_type = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        default=AccountingPreferencesExpenseTypeChoices.COMPANY_CONTRIBUTION_SINGLE_ACCOUNT,
    )
    employer_tax_expense_type = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        default=AccountingPreferencesExpenseTypeChoices.SINGLE_EMPLOYER_TAX_ACCOUNT,
    )
    tax_liability_expense_type = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        default=AccountingPreferencesExpenseTypeChoices.DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP,
    )
    other_liability_asset_account = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        default=AccountingPreferencesExpenseTypeChoices.OTHER_LIABILITY_ASSETS_TYPE,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"ID: {self.id}, Company: {self.company.name}"


class PayrollAccountExpenseAccountComponent(BaseModelWithUID):
    payroll_accounting_preferences = models.ForeignKey(
        PayrollAccountingPreferencesSetting,
        on_delete=models.CASCADE,
        related_name="expense_accounts",
    )
    payroll_accounting_preferences_type = models.CharField(
        max_length=150,
        choices=AccountingPreferencesExpenseTypeChoices,
        blank=True,
        null=True,
    )

    employee = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="payroll_expense_employee",
    )
    account_type = models.CharField(max_length=100, blank=True, null=True)
    expense_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        related_name="expense_account",
        blank=True,
        null=True,
    )
    deduction_and_contribution = models.ForeignKey(
        DeductionAndContributions,
        on_delete=models.SET_NULL,
        related_name="expense_deduction_and_contribution",
        blank=True,
        null=True,
    )
    employee_garnishment = models.ForeignKey(
        "employeeio.EmployeeGarnishment",
        on_delete=models.SET_NULL,
        related_name="expense_employee_garnishment",
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"Payroll Accounting Preferences: {self.payroll_accounting_preferences.slug}, Account Type: {self.account_type}, Expense Account: {self.expense_account.title if self.expense_account else 'N/A'}"


class PayrollGeneralSettings(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_general_tax_setting_slug, unique=True, db_index=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    # Working Days and Hours
    payroll_working_days = models.CharField(
        max_length=150,
        choices=PayrollGeneralSettingsWorkingChoices,
        blank=True,
        null=True,
    )
    is_total_working_days = models.BooleanField(default=False)
    max_working_hours = models.PositiveIntegerField(default=0, blank=True, null=True)
    daily_salary_half_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        blank=True,
        null=True,
    )

    # Salary Slip
    is_round_total = models.BooleanField(default=False, blank=True, null=True)
    is_show_leave_balance = models.BooleanField(default=False, blank=True, null=True)
    is_encrypt_salary_slip = models.BooleanField(default=False, blank=True, null=True)

    # Email
    is_salary_slip = models.BooleanField(default=False, blank=True, null=True)
    email_template = models.CharField(
        max_length=150,
        choices=PayrollGeneralSettingsEmailTemplateChoices,
        blank=True,
        null=True,
    )

    # Other Settings
    is_process_payroll_by_employee = models.BooleanField(
        default=False,
        help_text="If checked, Payroll Payment will be booked against each employee",
    )

    def __str__(self):
        return (
            f"Company: {self.company.name} | Working Days: {self.payroll_working_days}"
        )


class PayrollContactInfoSetting(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_payroll_contact_info_setting_slug, unique=True, db_index=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    contact_first_name = models.CharField(max_length=250, blank=True, null=True)
    contact_last_name = models.CharField(max_length=250, blank=True, null=True)
    contact_email = models.EmailField(max_length=255, blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"Company: {self.company.name}, Contact Email: {self.contact_email}"


class TaxCenterPayMethod(BaseModelWithUID):
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_liability_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        related_name="tax_liability_account",
        blank=True,
        null=True,
    )
    tax_record_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        related_name="tax_record_account",
        blank=True,
        null=True,
    )
    payment_date = models.DateField(blank=True, null=True)
    check_number = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_inside_balanzify = models.BooleanField(default=False)
    liability_period = models.CharField(max_length=100, blank=True, null=True)
    is_paid = models.BooleanField(default=False)
    is_filed = models.BooleanField(default=False)


# Jurisdiction sentinel for the shared federal layer; states use their USPS code.
FEDERAL_JURISDICTION = "FEDERAL"


class PayrollTaxConfig(BaseModelWithUID):
    """Statutory payroll tax tables & system-default rates, one row per
    ``(year, jurisdiction)``.

    ``jurisdiction`` is ``FEDERAL`` (the shared federal layer) or a 2-letter USPS
    state code. ``data`` holds that jurisdiction's tables as JSON (open bracket
    bounds serialized as ``null``; the frontend rehydrates to Infinity).

    This is **tenant-independent reference data** (like a currency table): it has
    NO ``company`` FK and is deliberately **excluded from the tenant RLS policy**
    — do not add the RLS enable step to its migration. A payroll run should pin
    the resolved ``year`` + per-jurisdiction ``version`` for audit.
    """

    year = models.PositiveIntegerField(db_index=True)
    jurisdiction = models.CharField(max_length=16, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=PayrollTaxConfigStatusChoices.choices,
        default=PayrollTaxConfigStatusChoices.DRAFT,
    )
    # Year is the resolver today; effective window kept for future mid-year edits.
    effective_from = models.DateField(blank=True, null=True)
    effective_to = models.DateField(blank=True, null=True)
    data = models.JSONField()
    source_notes = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("-year", "jurisdiction")
        constraints = [
            models.UniqueConstraint(
                fields=["year", "jurisdiction"],
                name="uniq_payroll_tax_config_year_jurisdiction",
            )
        ]

    def __str__(self):
        return f"PayrollTaxConfig {self.year} {self.jurisdiction} v{self.version} ({self.status})"
