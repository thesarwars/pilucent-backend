from auditlog.registry import auditlog
from django.contrib import admin
from .models import TaxBanditsBusinessAccount, TaxBanditsReturn940, TaxBanditsReturn941

# Register your models here.


@admin.register(TaxBanditsBusinessAccount)
class TaxBanditsBusinessAccountAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "legal_name",
        "payer_ref",
        "ein_or_ssn",
        "tb_business_id",
        "status",
        "created_at",
    ]
    search_fields = ["legal_name", "payer_ref", "ein_or_ssn"]
    list_filter = ["status"]


@admin.register(TaxBanditsReturn940)
class TaxBanditsReturn940Admin(admin.ModelAdmin):
    list_display = [
        "uid",
        "tax_year",
        "record_id",
        "submission_id",
        "status",
        "created_at",
    ]
    search_fields = ["record_id", "submission_id"]
    list_filter = ["status"]



@admin.register(TaxBanditsReturn941)
class TaxBanditsReturn941Admin(admin.ModelAdmin):
    list_display = [
        "uid",
        "tax_year",
        "quarter",
        "record_id",
        "submission_id",
        "status",
        "created_at",
    ]
    search_fields = ["record_id", "submission_id"]
    list_filter = ["status"]
    

# Auditlog related
auditlog.register(TaxBanditsBusinessAccount)
auditlog.register(TaxBanditsReturn940)
auditlog.register(TaxBanditsReturn941)