from auditlog.registry import auditlog

from django.contrib import admin

from .models import JournalEntryConnector, JournalEntry


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "date",
        "kind",
        "amount",
        "status",
        "created_at",
    ]
    search_fields = ["date", "entry_number", "amount", "status"]
    list_filter = ["date", "entry_number", "amount", "status"]
    readonly_fields = ["uid", 'created_at', 'updated_at']
    autocomplete_fields = ["company"]


@admin.register(JournalEntryConnector)
class JournalEntryConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "debit", "credit", "kind", "request_kind", "created_at"]
    search_fields = ["uid", "kind"]
    list_filter = ["kind"]
    autocomplete_fields = ["account"]


auditlog.register(JournalEntry)
auditlog.register(JournalEntryConnector)
