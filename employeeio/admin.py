from auditlog.registry import auditlog

from django.contrib import admin
from django.db.models import Prefetch

from companyio.models import CompanyUser

from .models import (
    Employee,
    EmployeeSalary,
    EmployeeBankingInformation,
    EmployeeEducation,
    EmployeeTax,
    EmployeeEarning,
    EmployeeDeductionContribution,
    EmployeeGarnishment,
    EmployeeWorkExperience,
    EmployeeExpenseReport,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "code",
        "company",
        "status",
        "kind",
        "confirmation_date",
    ]
    search_fields = ["uid", "code", "status", "kind", "confirmation_date"]
    list_filter = ["status", "kind", "created_at", "updated_at"]
    autocomplete_fields = ["user", "department", "designation", "shift"]

    def get_queryset(self, request):
        # Prefetch the user's first CompanyUser (with company joined) into
        # `_active_companyusers` so the `company` column reads from cache
        # instead of issuing one SELECT per row.
        cu_qs = CompanyUser.objects.select_related("company").only(
            "id", "user_id", "company__id", "company__name"
        )
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .prefetch_related(
                Prefetch(
                    "user__companyuser_set",
                    queryset=cu_qs,
                    to_attr="_active_companyusers",
                )
            )
        )

    @admin.display(description="Company", ordering="user__companyuser__company__name")
    def company(self, obj):
        if obj.user_id is None:
            return None
        cached = getattr(obj.user, "_active_companyusers", None)
        if not cached:
            return None
        return cached[0].company.name if cached[0].company_id else None


@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = ["uid", "cash", "total"]
    search_fields = ["title", "employee__uid", "employee__slug"]
    list_filter = ["employee__status", "employee__kind", "created_at", "updated_at"]


@admin.register(EmployeeBankingInformation)
class EmployeeBankingInformationAdmin(admin.ModelAdmin):
    list_display = ["uid", "kind", "bank_name"]
    search_fields = list_display + ["bank_account_number", "routing_number", "iban"]
    list_filter = ["kind", "created_at", "updated_at"]


@admin.register(EmployeeEducation)
class EmployeeEducationAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "institute_name", "created_at"]
    search_fields = list_display
    list_filter = ["created_at", "updated_at"]
    autocomplete_fields = ["employee"]


@admin.register(EmployeeWorkExperience)
class EmployeeWorkExperienceAdmin(admin.ModelAdmin):
    list_display = ["uid", "company_name", "status", "created_at"]
    search_fields = list_display
    list_filter = ["created_at", "updated_at"]
    autocomplete_fields = ["employee"]


@admin.register(EmployeeTax)
class EmployeeTaxAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "is_the_state_other_income_tax",
        "is_federal_with_holding",
        "employee_W_4_kind",
        "created_at",
    ]
    search_fields = list_display
    list_filter = ["created_at", "updated_at"]
    autocomplete_fields = ["employee"]


@admin.register(EmployeeEarning)
class EmployeeEarningAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "pay_kind",
        "total_recurring_amount",
        "created_at",
    ]
    search_fields = list_display
    list_filter = ["status", "pay_kind", "created_at", "updated_at"]
    autocomplete_fields = ["employee"]


@admin.register(EmployeeDeductionContribution)
class EmployeeDeductionContributionAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "employee_deduction_kind",
        "company_contribution_kind",
        "created_at",
    ]
    list_filter = list_display
    search_fields = list_filter
    autocomplete_fields = ["employee"]


@admin.register(EmployeeGarnishment)
class EmployeeGarnishmentAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "kind", "total_requsted_amount"]
    search_fields = list_display
    list_filter = list_display
    autocomplete_fields = ["employee"]


@admin.register(EmployeeExpenseReport)
class EmployeeExpenseReportAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "employee",
        "amount",
        "vendor_supplier_name",
        "expense_date",
        "status",
        "created_at",
    ]
    search_fields = ["uid", "vendor_supplier_name", "description", "reference_number"]
    list_filter = ["status", "expense_date", "created_at"]
    autocomplete_fields = ["employee", "company", "supplier", "chart_of_account"]
    date_hierarchy = "expense_date"
    readonly_fields = ["ocr_processed", "ocr_data"]


auditlog.register(Employee)
auditlog.register(EmployeeSalary)
auditlog.register(EmployeeBankingInformation)
auditlog.register(EmployeeEducation)
auditlog.register(EmployeeTax)
auditlog.register(EmployeeEarning)
auditlog.register(EmployeeDeductionContribution)
auditlog.register(EmployeeGarnishment)
auditlog.register(EmployeeExpenseReport)
