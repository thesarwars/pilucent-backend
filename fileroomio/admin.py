from auditlog.registry import auditlog

from django.contrib import admin

from .models import FileItem, FileItemConnector


@admin.register(FileItem)
class FileItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "status", "kind", "created_at"]
    search_fields = ["title", "description", "uid"]
    list_filter = ["status", "kind"]


@admin.register(FileItemConnector)
class FileItemConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "model_kind", "created_at"]
    search_fields = ["uid", "model_kind"]
    list_filter = ["model_kind"]

# Auditlog related
auditlog.register(FileItem)
