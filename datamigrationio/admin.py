from django.contrib import admin

from datamigrationio.models import (
    DataMigrationJob,
    DataMigrationRow,
    DataMigrationFieldMapping,
    DataMigrationValidationIssue,
    DataMigrationImpactLine,
)


@admin.register(DataMigrationJob)
class DataMigrationJobAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "data_type",
        "status",
        "current_step",
        "total_rows",
        "imported_rows",
        "created_at",
    ]
    list_filter = ["status", "data_type", "current_step"]
    search_fields = ["uid", "file_name"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(DataMigrationRow)
class DataMigrationRowAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "job",
        "row_number",
        "status",
        "error_count",
        "warning_count",
        "linked_record_uid",
    ]
    list_filter = ["status"]
    search_fields = ["uid", "linked_record_uid"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(DataMigrationFieldMapping)
class DataMigrationFieldMappingAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "job",
        "source_column",
        "target_field",
        "is_required",
        "affects_accounting",
    ]
    search_fields = ["source_column", "target_field"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(DataMigrationValidationIssue)
class DataMigrationValidationIssueAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "job",
        "row",
        "issue_type",
        "severity",
        "is_resolved",
        "created_at",
    ]
    list_filter = ["severity", "issue_type", "is_resolved"]
    search_fields = ["description"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(DataMigrationImpactLine)
class DataMigrationImpactLineAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "job",
        "transaction_type",
        "account_title",
        "debit",
        "credit",
        "customer_name",
    ]
    list_filter = ["transaction_type"]
    readonly_fields = ["uid", "created_at", "updated_at"]
