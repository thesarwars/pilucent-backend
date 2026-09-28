from django.contrib import admin
from auditlog.registry import auditlog
from .models import Tag, TagConnector


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["uid", "kind", "status", "company"]
    search_fields = ["kind", "status", "company__name"]
    list_filter = ["kind", "status", "company"]

@admin.register(TagConnector)
class TagConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "created_at"]
    search_fields = list_display
    list_filter = ["uid", "tag__uid", "tag__status"]


auditlog.register(Tag)
auditlog.register(TagConnector)