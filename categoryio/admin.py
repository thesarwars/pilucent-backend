from django.contrib import admin
from auditlog.registry import auditlog
from .models import Category, CategoryConnector


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "kind", "status"]
    search_fields = ["title", "kind", "status", "company__name"]
    list_filter = ["title", "kind", "status", "company"]
    readonly_fields = ["uid", "slug"]


@admin.register(CategoryConnector)
class CategoryConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "category"]
    search_fields = ["category__title"]


# Auditlog related
auditlog.register(Category)
