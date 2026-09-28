from django.contrib import admin
from auditlog.registry import auditlog
from .models import Attachment


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["uid", "slug", "company", "created_at"]
    search_fields = ["slug", "description", "company__name"]
    list_filter = ["company", "created_at"]


auditlog.register(Attachment)
