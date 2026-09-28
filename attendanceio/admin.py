from django.contrib import admin
from auditlog.registry import auditlog
from .models import (
    DailyTimeTracking,
    DailyTimeTrackingSession,
    Attendance,
    Holiday,
    HolidayDetails,
    AttendanceProcess,
    AttendanceProcessItem,
    PunchDataDailyTime,
)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["uid", "check_in", "check_out", "status"]
    search_fields = list_display + [
        "slug",
        "company__uid",
        "company__slug",
        "company__name",
    ]
    list_filter = ["status"]


@admin.register(DailyTimeTracking)
class DailyTimeTrackingAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "worked_hour",
        "check_in",
        "check_out",
    ]
    search_fields = list_display
    list_filter = ["status"]


@admin.register(DailyTimeTrackingSession)
class DailyTimeTrackingSessionAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "worked_hour",
        "kind",
        "check_in",
        "check_out",
    ]
    search_fields = list_display
    list_filter = ["kind"]


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "from_date",
        "to_date",
        "total_holidays",
        "status",
    ]
    search_fields = list_display + [
        "slug",
        "company__uid",
        "company__slug",
        "company__name",
    ]
    list_filter = ["status"]


@admin.register(HolidayDetails)
class HolidayDetailsAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "type",
        "date",
        "description",
        "holiday",
    ]
    # `search_fields` is not `list_display`. A display column may be a relation
    # rendered through __str__, or an admin method -- neither of which is an ORM
    # path, and a search term is applied with `icontains`, so reusing the list
    # made every search on this changelist a FieldError.
    #
    # `list_display` here carries `holiday`, a ForeignKey.
    search_fields = [
        "uid",
        "type",
        "date",
        "description",
        "holiday__uid",
        "holiday__slug",
        "holiday__title",
    ]
    list_filter = ["type"]


@admin.register(AttendanceProcess)
class AttendanceProcessAdmin(admin.ModelAdmin):
    list_display = ["uid", "start_date", "end_date"]
    list_filter = list_display
    search_fields = list_filter


@admin.register(AttendanceProcessItem)
class AttendanceProcessItemAdmin(admin.ModelAdmin):
    list_display = ["uid"]
    list_filter = list_display
    search_fields = list_filter

@admin.register(PunchDataDailyTime)
class PunchDataDailyTimeAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "date",
        "status",
        "worked_hour",
        "check_in",
    ]
    search_fields = list_display + [
        "slug",
        "employee__uid",
        "employee__user__email",
        "employee__user__email",
    ]
    list_filter = ["status"]

auditlog.register(Attendance)
auditlog.register(DailyTimeTracking)
auditlog.register(DailyTimeTrackingSession)
auditlog.register(Holiday)
auditlog.register(HolidayDetails)
auditlog.register(AttendanceProcess)
auditlog.register(PunchDataDailyTime)