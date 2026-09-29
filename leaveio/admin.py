from django.contrib import admin
from .models import (
    LeaveType,
    LeaveBalance,
    LeaveRequest,
    EmployeeLeaveAllocation,
    LeaveEncashment,
    LeaveEncashmentItem,
)
from auditlog.registry import auditlog


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ["uid", "name", "display_name", "maximum_allocation"]
    search_fields = ["name", "display_name"]
    list_filter = [
        "leave_type",
    ]
    readonly_fields = ["uid"]


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ["uid", "leave_year", "from_date", "to_date", "status"]
    search_fields = ["leave_year", "from_date", "to_date"]
    list_filter = ["leave_year", "status"]
    readonly_fields = ["uid"]


@admin.register(EmployeeLeaveAllocation)
class EmployeeLeaveAllocationAdmin(admin.ModelAdmin):
    list_display = ["uid", "employee", "leave_type", "leave_year", "available_days"]
    search_fields = ["employee__name_en", "leave_type__name"]
    list_filter = ["leave_year", "leave_type"]
    readonly_fields = ["uid", "available_days"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ["uid", "employee", "leave_type", "from_date", "to_date", "status"]
    search_fields = ["employee__name_en", "leave_type__name"]
    list_filter = ["status"]
    readonly_fields = ["uid"]


@admin.register(LeaveEncashment)
class LeaveEncashmentAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "employee",
        "encashment_date",
        "leave_balance",
        "total_encashment_amount",
        "status",
    ]
    search_fields = ["employee__name_en", "encashment_date"]
    list_filter = ["status"]
    readonly_fields = ["uid"]

@admin.register(LeaveEncashmentItem)
class LeaveEncashmentItemAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "leave_type",
        "encashment_days",
        "total_amount",
    ]
    search_fields = ["leave_type__name"]
    list_filter = ["leave_type"]
    readonly_fields = ["uid"]



# Auditlog related
auditlog.register(LeaveType)
auditlog.register(LeaveBalance)
auditlog.register(LeaveRequest)
auditlog.register(EmployeeLeaveAllocation)
auditlog.register(LeaveEncashment)
auditlog.register(LeaveEncashmentItem)
