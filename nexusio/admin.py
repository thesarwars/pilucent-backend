from django.contrib import admin
from auditlog.registry import auditlog

from .models import (
    NexusStateRule,
    NexusStateStatus,
    NexusAgencyRegistration,
    NexusAlertLog,
    NexusSettings,
)


@admin.register(NexusStateRule)
class NexusStateRuleAdmin(admin.ModelAdmin):
    list_display = [
        "state_code",
        "state_name",
        "combination_logic",
        "sales_threshold",
        "txn_threshold",
        "effective_from",
        "effective_to",
    ]
    search_fields = ["state_code", "state_name"]
    list_filter = [
        "has_sales_tax",
        "combination_logic",
        "measurement_period_type",
        "includable_sales_basis",
    ]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(NexusStateStatus)
class NexusStateStatusAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "state_code",
        "status",
        "threshold_met",
        "sales_amount",
        "txn_count",
        "last_evaluated_at",
    ]
    search_fields = ["state_code", "company__name", "company__uid"]
    list_filter = ["status", "threshold_met", "state_code"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(NexusAgencyRegistration)
class NexusAgencyRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "state_code",
        "registration_type",
        "registration_status",
        "collection_start_date",
    ]
    search_fields = ["state_code", "company__name", "sales_tax_permit_number"]
    list_filter = ["registration_status", "registration_type", "state_code"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(NexusAlertLog)
class NexusAlertLogAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "state_code",
        "alert_type",
        "triggered_at",
        "acknowledged_at",
    ]
    search_fields = ["state_code", "company__name"]
    list_filter = ["alert_type", "state_code"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(NexusSettings)
class NexusSettingsAdmin(admin.ModelAdmin):
    list_display = ["uid", "company", "warning_fraction"]
    search_fields = ["company__name", "company__uid"]
    readonly_fields = ["uid", "created_at", "updated_at"]


# Auditlog related
auditlog.register(NexusAgencyRegistration)
auditlog.register(NexusSettings)
