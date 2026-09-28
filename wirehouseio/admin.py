from django.contrib import admin
from auditlog.registry import auditlog
from .models import Warehouse

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["uid", "slug", "title", "kind", "company"]
    search_fields = ["slug", "title", "kind", "company__name"]
    list_filter = ["kind", "company"]


auditlog.register(Warehouse)