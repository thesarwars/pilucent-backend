
from auditlog.registry import auditlog

from django.contrib import admin
from .models import MoovAccountSettings, MoovBankAccountSettings, MoovTransfers

@admin.register(MoovAccountSettings)
class MoovAccountSettingsAdmin(admin.ModelAdmin):
    list_display = ["uid", "moov_account_display_name", "moov_account_uid", "status", "company", "created_at"]
    search_fields = ["moov_account_display_name", "moov_account_uid", "status"]
    list_filter = ["status"]
    
@admin.register(MoovBankAccountSettings)
class MoovBankAccountSettingsAdmin(admin.ModelAdmin):
    list_display = ["uid", "moov_account_settings", "bank_account_uid", "account_holder_name", "bank_name", "status", "created_at"]
    search_fields = ["bank_account_uid", "account_holder_name", "bank_name", "status"]
    list_filter = ["status"]    
    
@admin.register(MoovTransfers)
class MoovTransfersAdmin(admin.ModelAdmin):
    list_display = ["uid", "moov_transfer_uid", "amount", "currency", "status", "created_at"]
    search_fields = ["moov_transfer_uid", "amount", "currency", "status"]
    list_filter = ["status"]    

# Auditlog related
auditlog.register(MoovAccountSettings)
auditlog.register(MoovBankAccountSettings)
auditlog.register(MoovTransfers)