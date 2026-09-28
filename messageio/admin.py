from auditlog.registry import auditlog

from django.contrib import admin

from .models import Thread, Inbox


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ["uid", "author", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["uid", "author__first_name"]


@admin.register(Inbox)
class InboxAdmin(admin.ModelAdmin):
    list_display = ["uid", "is_seen", "status", "created_at"]
    search_fields = ["uid"]

# Auditlog related
auditlog.register(Thread)
auditlog.register(Inbox)
