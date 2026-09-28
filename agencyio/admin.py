from django.contrib import admin
from auditlog.registry import auditlog
from .models import Agency, AgencyTax, AgencyTaxSet


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = ["status", "company__name", "company__uid"]
    list_filter = ["status"]


@admin.register(AgencyTax)
class AgencyTaxAdmin(admin.ModelAdmin):
    list_display = ["uid", "is_single", "created_at"]
    search_fields = ["title", "company__name"]
    list_filter = ["is_single"]


@admin.register(AgencyTaxSet)
class TaxSetAdmin(admin.ModelAdmin):
    readonly_fields = ["uid", "created_at", "updated_at"]

# Auditlog related
auditlog.register(Agency)
auditlog.register(AgencyTax)