from auditlog.registry import auditlog

from django.contrib import admin

from .models import PaymentMethod, PaymentInformation


@admin.register(PaymentMethod)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = ["status", "company__name", "company__uid"]
    list_filter = ["status"]


@admin.register(PaymentInformation)
class PaymentInformationAdmin(admin.ModelAdmin):
    list_display = ["uid", "company", "currency", "status", "created_at"]
    search_fields = ["status", "company__name", "company__uid"]
    list_filter = ["kind", "status"]

# Auditlog related
auditlog.register(PaymentMethod)
auditlog.register(PaymentInformation)
