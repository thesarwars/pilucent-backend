from django.contrib import admin
from auditlog.registry import auditlog
from .models import (
    SalaryAdjustment,
    DeductionAndContributions,
    PaySchedule,
    PayrollSalaryProcess,
    PayrollSalaryComponent,
    PayrollGeneralTaxSetting,
    PayrollFederalTaxInfoSetting,
    PayrollFederalTaxInfoSettingItems,
    PayrollStateTaxInfoSetting,
    PayrollStateTaxPaymentSchedule,
    PayrollUnemploymentInsuranceTaxInfo,
    PayrollFederalLoanInterestPaymentSchedule,
    PayrollReemploymentOrWorkforceServiceFund,
    PayrollMCTMTZone,
    PayrollWorkLocation,
    PayrollAccountingPreferencesSetting,
    PayrollAccountExpenseAccountComponent,
    PayrollGeneralSettings,
    PayrollContactInfoSetting,
    TaxCenterPayMethod,
    PayrollTaxConfig,
)


@admin.register(SalaryAdjustment)
class SalaryAdjustmentAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "kind",
        "join_date",
        "amount",
    ]
    search_fields = list_display + [
        "employee__user__uid",
        "employee__user__slug",
        "employee__user__name",
    ]
    list_filter = ["status", "kind", "created_at", "updated_at"]


admin.site.register(DeductionAndContributions)
admin.site.register(TaxCenterPayMethod)


@admin.register(PaySchedule)
class PayScheduleAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "pay_frequency", "status", "company__name"]
    readonly_fields = ["uid", "slug"]


class PayrollComponentTabular(admin.TabularInline):
    extra = 1
    model = PayrollSalaryComponent
    fields = ["id", "payroll_type", "payroll_category", "current", "ytd"]


@admin.register(PayrollSalaryProcess)
class PayrollSalaryProcessAdmin(admin.ModelAdmin):
    readonly_fields = ["uid"]
    # Render FKs as an id-input + lookup popup instead of a <select> that loads
    # EVERY employee / chart-of-account (across all tenants) into <option> tags —
    # that full load is what made the change page take 60-120s.
    raw_id_fields = ["employee", "funding_account", "payment_account"]
    # inlines = [PayrollComponentTabular]


@admin.register(PayrollGeneralTaxSetting)
class PayrollGeneralTaxSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "company_type", "company__name"]
    search_fields = ["uid", "title", "company__name"]
    list_filter = ["company_type", "company__name"]


@admin.register(PayrollFederalTaxInfoSetting)
class PayrollFederalTaxInfoSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "ein_number", "company__name"]
    search_fields = ["uid", "ein_number", "company__name"]
    list_filter = ["company__name"]


@admin.register(PayrollFederalTaxInfoSettingItems)
class PayrollFederalTaxInfoSettingItemsAdmin(admin.ModelAdmin):
    list_display = ["uid", "tax_form", "payment_frequency", "effective_date"]
    search_fields = ["tax_form", "payment_frequency", "effective_date"]
    list_filter = ["tax_form", "payment_frequency", "effective_date"]


@admin.register(PayrollStateTaxInfoSetting)
class PayrollStateTaxInfoSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "state", "win_number", "company__name"]
    search_fields = ["uid", "state", "win_number", "company__name"]
    list_filter = ["state", "company__name"]


@admin.register(PayrollStateTaxPaymentSchedule)
class PayrollStateTaxPaymentScheduleAdmin(admin.ModelAdmin):
    list_display = ["id", "payment_frequency", "effective_date"]
    search_fields = ["payment_frequency", "effective_date"]
    list_filter = ["payment_frequency", "effective_date"]


@admin.register(PayrollUnemploymentInsuranceTaxInfo)
class PayrollUnemploymentInsuranceTaxInfoAdmin(admin.ModelAdmin):
    list_display = ["id", "ui_rate", "effective_date"]
    search_fields = ["ui_rate", "effective_date"]
    list_filter = ["ui_rate", "effective_date"]


@admin.register(PayrollFederalLoanInterestPaymentSchedule)
class PayrollFederalLoanInterestPaymentScheduleAdmin(admin.ModelAdmin):
    list_display = ["uid", "ui_rate", "effective_date"]
    search_fields = ["ui_rate", "effective_date"]
    list_filter = ["ui_rate", "effective_date"]


@admin.register(PayrollReemploymentOrWorkforceServiceFund)
class PayrollReemploymentOrWorkforceServiceFundAdmin(admin.ModelAdmin):
    list_display = ["id", "reemployment_or_workforce_fund_rate", "effective_date"]
    search_fields = ["reemployment_or_workforce_fund_rate", "effective_date"]
    list_filter = ["reemployment_or_workforce_fund_rate", "effective_date"]


@admin.register(PayrollMCTMTZone)
class PayrollMCTMTZoneAdmin(admin.ModelAdmin):
    list_display = ["id", "zone", "mctmt_rate", "effective_date"]
    search_fields = ["zone", "mctmt_rate", "effective_date"]
    list_filter = ["zone", "mctmt_rate", "effective_date"]


@admin.register(PayrollAccountingPreferencesSetting)
class PayrollAccountingPreferencesSettingAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "paycheck_payroll_tax_expense_account",
        "company",
    ]
    # `paycheck_payroll_tax_expense_account` is a ForeignKey, and a search term
    # is applied with `icontains` -- against a relation that is a FieldError, so
    # every search on this changelist was a 500. Traverse to the account title.
    search_fields = [
        "uid",
        "paycheck_payroll_tax_expense_account__title",
        "created_by__name",
    ]
    list_filter = [
        "created_at",
        "updated_at",
        "wage_expense_type",
        "company_contribution_expense_type",
        "employer_tax_expense_type",
        "tax_liability_expense_type",
    ]


@admin.register(PayrollAccountExpenseAccountComponent)
class PayrollAccountExpenseAccountComponentAdmin(admin.ModelAdmin):
    list_display = ["uid", "expense_account", "account_type"]
    search_fields = ["uid", "expense_account__title"]
    list_filter = ["created_at", "updated_at"]


@admin.register(PayrollWorkLocation)
class PayrollWorkLocationAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "location_address",
        "location_city",
        "location_state",
        "location_zip",
        "company",
    ]
    search_fields = ["uid", "location_address", "location_city", "company__name"]
    list_filter = ["status", "company__name"]
    readonly_fields = ["uid"]


@admin.register(PayrollGeneralSettings)
class PayrollGeneralSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "payroll_working_days",
        "is_total_working_days",
        "max_working_hours",
        "daily_salary_half_hours",
    ]
    search_fields = ["uid", "company__name", "email_template"]
    list_filter = ["created_at", "updated_at", "company__name"]


@admin.register(PayrollContactInfoSetting)
class PayrollContactInfoSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "company", "contact_email", "contact_phone"]
    search_fields = [
        "uid",
        "company__name",
        "contact_first_name",
        "contact_last_name",
        "contact_email",
        "contact_phone",
    ]
    list_filter = ["created_at", "company__name"]


@admin.register(PayrollTaxConfig)
class PayrollTaxConfigAdmin(admin.ModelAdmin):
    # PayrollTaxConfig is global reference data with NO company FK, so no
    # company / company__name lookups here.
    list_display = [
        "uid",
        "year",
        "jurisdiction",
        "status",
        "version",
        "effective_from",
        "effective_to",
    ]
    search_fields = ["uid", "jurisdiction", "status"]
    list_filter = ["status", "jurisdiction", "year"]


auditlog.register(SalaryAdjustment)
auditlog.register(PaySchedule)
auditlog.register(PayrollSalaryProcess)
auditlog.register(PayrollSalaryComponent)
auditlog.register(PayrollGeneralTaxSetting)
auditlog.register(PayrollFederalTaxInfoSetting)
auditlog.register(PayrollStateTaxInfoSetting)
auditlog.register(PayrollStateTaxPaymentSchedule)
auditlog.register(PayrollUnemploymentInsuranceTaxInfo)
auditlog.register(PayrollReemploymentOrWorkforceServiceFund)
auditlog.register(PayrollMCTMTZone)
auditlog.register(PayrollWorkLocation)
auditlog.register(PayrollAccountingPreferencesSetting)
auditlog.register(PayrollAccountExpenseAccountComponent)
auditlog.register(PayrollFederalLoanInterestPaymentSchedule)
auditlog.register(PayrollContactInfoSetting)
