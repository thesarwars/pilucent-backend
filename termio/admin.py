from django.contrib import admin
from auditlog.registry import auditlog
from .models import Term, TermConnector


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["uid", "days", "status", "company"]
    search_fields = ["title", "status", "company__name"]
    list_filter = ["status", "is_active"]


@admin.register(TermConnector)
class TermConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "kind", "supplier"]
    search_fields = ["kind", "supplier__first_name"]
    list_filter = ["kind"]


auditlog.register(Term)
