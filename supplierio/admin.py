from django.contrib import admin
from auditlog.registry import auditlog
from .models import Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["uid", "first_name", "status", "created_at"]
    list_filter = list_display
    search_fields = list_display + [
        "company__name",
        "company__uid",
    ]
    list_filter = ["company__name", "company__uid", "status"]


auditlog.register(Supplier)