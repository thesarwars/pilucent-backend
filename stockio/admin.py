from auditlog.registry import auditlog

from django.contrib import admin

from .models import StockAlert, StockAdjustment, StockAdjustmentItem

# Register your models here.


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = list_display + ["quantity"]
    list_filter = ["status"]


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = list_display + ["reference_number"]
    list_filter = ["status"]


@admin.register(StockAdjustmentItem)
class StockAdjustmentItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = list_display + ["quantity"]
    list_filter = ["status"]


auditlog.register(StockAlert)
auditlog.register(StockAdjustment)
auditlog.register(StockAdjustmentItem)
