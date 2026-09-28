from django.contrib import admin
from auditlog.registry import auditlog
from .models import CreditNote, CreditNoteItem

# Register your models here.


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = ["uid", "credit_note_number", "status"]
    search_fields = ["credit_note_number", "status"]
    list_filter = ["status", "kind"]


@admin.register(CreditNoteItem)
class CreditNoteItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "section", "status"]
    search_fields = ["section", "status"]
    list_filter = ["status"]


# Auditlog related
auditlog.register(CreditNote)
auditlog.register(CreditNoteItem)
