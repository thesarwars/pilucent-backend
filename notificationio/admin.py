from auditlog.registry import auditlog

from django.contrib import admin

from .models import Notification, NotificationSetting


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = ["status"]
    list_filter = ["status"]


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    list_display = ["uid",  "created_at"]
    search_fields = ["company__name", "company__uid"]
    list_filter = []

# Auditlog related
auditlog.register(Notification)
auditlog.register(NotificationSetting)
