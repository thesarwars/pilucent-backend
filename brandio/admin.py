from django.contrib import admin
from auditlog.registry import auditlog
from .models import Brand, BrandConnector


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["uid", "kind", "status", "created_at"]
    search_fields = ["kind", "status", "company__name", "company__uid"]
    list_filter = ["kind", "status"]


@admin.register(BrandConnector)
class BrandConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "brand", "product", "created_at"]
    search_fields = ["brand__title", "product__title", "product__uid"]


# Auditlog related
auditlog.register(Brand)
