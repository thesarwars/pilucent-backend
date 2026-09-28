from auditlog.registry import auditlog

from django.contrib import admin
from .models import LiveDemo

# Register your models here.


@admin.register(LiveDemo)
class LiveDemoAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "email",
        "full_name",
        "work_email",
        "company_name",
        "phone_number",
    ]
    search_fields = ["email", "full_name", "work_email", "company_name", "phone_number"]
    list_filter = ["company_name"]

# Auditlog related
auditlog.register(LiveDemo)