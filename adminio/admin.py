from auditlog.registry import auditlog

from django.contrib import admin
from adminio.models import CompanyRole


@admin.register(CompanyRole)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "is_system", "company__name"]
    list_filter = ["kind", "status", "is_system"]
    readonly_fields = ["uid"]


auditlog.register(CompanyRole)
