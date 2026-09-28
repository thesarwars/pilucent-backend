from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from auditlog.registry import auditlog


from .deletion import count_ledger_legs, purge_companies
from .models import (
    Company,
    CompanyShift,
    CompanyDepartment,
    CompanySection,
    CompanyDesignation,
    CompanyUser,
    CompanySetting,
)


@admin.register(Company)
class CompanyAdmin(SimpleHistoryAdmin):

    list_display = [
        "slice_uid",
        "name",
        "legal_name",
        "status",
        "business_id_no",
        "vat_number",
        "email",
        "phone",
    ]
    search_fields = [
        "uid",
        "slug",
        "name",
        "legal_name",
        "business_id_no",
        "vat_number",
        "email",
        "phone",
    ]
    list_filter = ["status"]
    history_list_display = ["status"]
    ordering = ("-created_at",)
    readonly_fields = ["company_admin_user", "uid", "slug", "history"]

    def slice_uid(self, obj):
        return str(obj.uid)[:8]

    def company_admin_user(self, obj):
        company_user = obj.companyuser_set.filter(user__is_admin=True).first()
        # print("company_user", company_user)
        if company_user:
            return company_user.user.first_name
        return "N/A"

    company_admin_user.short_description = "Admin User"
    slice_uid.short_description = "UID"

    # -- deletion -----------------------------------------------------------
    #
    # Deleting a Company normally hits a wall: all four PROTECT foreign keys in
    # the schema live on `JournalEntryConnector`, and PROTECT fires even from
    # inside the same cascade. That is what produces the admin's "Cannot delete
    # Companiess" page, and for tenant-facing paths it is exactly right --
    # `AdminCompanyRetrieve.perform_destroy` soft-removes instead, keeping the
    # books.
    #
    # This admin is not a tenant-facing path. It stands in for a database GUI,
    # where a delete is meant to be final: clearing out test signups and junk
    # fixtures that should never have had books. So it tears the ledger down
    # explicitly, in order, rather than leaving an action that reliably 409s.
    #
    # The confirmation page still shows the journal-leg count before anything is
    # written, because that number is the whole cost of the operation.

    def get_deleted_objects(self, objs, request):
        deletable, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        legs = count_ledger_legs(objs)
        if legs:
            model_count = {
                **model_count,
                "journal entry connectors (ledger, IRREVERSIBLE)": legs,
            }
        # `protected` is emptied deliberately: `delete_queryset` removes those
        # rows itself. Leaving them here would render the refusal page for an
        # operation that is going to succeed.
        return deletable, model_count, perms_needed, []

    def delete_queryset(self, request, queryset):
        purge_companies(queryset)

    def delete_model(self, request, obj):
        purge_companies(Company.objects.filter(pk=obj.pk))


@admin.register(CompanyShift)
class CompanyShiftAdmin(SimpleHistoryAdmin):
    list_display = [
        "title",
        "code",
        "kind",
        "in_time",
        "out_time",
        "status",
        "company",
    ]
    search_fields = ["title", "code", "company__name"]
    list_filter = ["status", "company", "kind"]
    history_list_display = ["code", "in_time", "out_time"]
    ordering = ("-created_at",)


@admin.register(CompanyDepartment)
class CompanyDepartmentAdmin(SimpleHistoryAdmin):
    list_display = ["title", "code", "company"]
    search_fields = ["title", "code", "company__name"]
    list_filter = ["company"]
    history_list_display = ["code", "company"]
    ordering = ("-created_at",)


@admin.register(CompanySection)
class CompanySectionAdmin(SimpleHistoryAdmin):
    list_display = ["title", "department", "company"]
    search_fields = ["title", "department__title", "company__name"]
    list_filter = ["company", "department"]
    history_list_display = ["title", "department", "company"]
    ordering = ("-created_at",)


@admin.register(CompanyDesignation)
class CompanyDesignationAdmin(SimpleHistoryAdmin):
    list_display = ["title", "company"]
    search_fields = ["title"]
    history_list_display = ["title", "company"]
    ordering = ("-created_at",)


@admin.register(CompanyUser)
class CompanyUserAdmin(admin.ModelAdmin):
    list_display = ["user", "company"]
    search_fields = ["user__email", "user__name", "company__name"]
    list_filter = ["company"]
    # history_list_display = ["user", "company"]
    readonly_fields = ["uid"]
    ordering = ("-created_at",)


@admin.register(CompanySetting)
class CompanySettingAdmin(SimpleHistoryAdmin):
    list_display = ["uid", "preffered_first_financial_month", "is_chart_of_account"]
    search_fields = list_display
    ordering = ("-created_at",)


# Auditlog related
auditlog.register(Company)
auditlog.register(CompanyShift)
auditlog.register(CompanyDepartment)
auditlog.register(CompanySection)
auditlog.register(CompanyDesignation)
auditlog.register(CompanyUser)
auditlog.register(CompanySetting)
