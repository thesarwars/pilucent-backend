from django.contrib import admin
from auditlog.registry import auditlog

from .models import (
    Product,
    ProductBundle,
    ProductBundleConnector,
    ProductAdditionalCost,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "quantity", "kind", "status", "company"]
    search_fields = ["kind", "status", "company__name", "company__uid"]
    list_filter = ["kind", "status", "company__uid", "company__name"]


@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "title"]
    search_fields = ["status", "title"]
    list_filter = ["status"]


@admin.register(ProductBundleConnector)
class ProductBundleConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "product_bundle", "products"]
    search_fields = ["product_bundle__title", "products__title"]
    list_filter = ["product_bundle", "products"]


@admin.register(ProductAdditionalCost)
class ProductAdditionalCostAdmin(admin.ModelAdmin):
    list_display = ["uid", "product", "amount"]
    search_fields = ["product__title", "amount"]
    list_filter = ["product", "amount", "prefferred_supplier", "tax"]


auditlog.register(Product)
auditlog.register(ProductBundle)
auditlog.register(ProductBundleConnector)
auditlog.register(ProductAdditionalCost)
