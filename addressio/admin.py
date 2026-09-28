from django.contrib import admin

from auditlog.registry import auditlog

from .models import Address, AddressConnector


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ["uid", "city", "full_address", "created_at"]
    search_fields = ["street", "city", "province", "postal_code", "company__name"]
    list_filter = ["city", "province", "is_shipping", "company"]


@admin.register(AddressConnector)
class AddressConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "kind", "created_at"]
    search_fields = list_display
    list_filter = ["kind"]

# Auditlog related
auditlog.register(Address)