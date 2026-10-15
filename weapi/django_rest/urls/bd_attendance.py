from django.urls import path

from ..views import bd_attendance as v

# Attendance (docs/backend/attendance.md §9). Singular, beside the legacy
# /attendances routes it replaces for BD companies.
urlpatterns = [
    path(r"/sites", v.AttendanceSites.as_view(), name="weapi.bd-attendance-sites"),
    path(r"/grid", v.AttendanceGrid.as_view(), name="weapi.bd-attendance-grid"),
    path(r"/day", v.AttendanceDay.as_view(), name="weapi.bd-attendance-day"),
    path(r"/exceptions", v.AttendanceExceptions.as_view(), name="weapi.bd-attendance-exceptions"),
    path(r"/exceptions/resolve", v.AttendanceResolve.as_view(), name="weapi.bd-attendance-resolve"),
    path(r"/exceptions/acknowledge", v.AttendanceAcknowledge.as_view(), name="weapi.bd-attendance-acknowledge"),
    path(r"/adjustments", v.AttendanceAdjustments.as_view(), name="weapi.bd-attendance-adjustments"),
    path(r"/adjustments/remove", v.AttendanceAdjustmentRemove.as_view(),
         name="weapi.bd-attendance-adjustment-remove"),
    path(r"/close", v.AttendanceClose.as_view(), name="weapi.bd-attendance-close"),
    path(r"/holiday-work/confirm", v.AttendanceHolidayWorkConfirm.as_view(),
         name="weapi.bd-attendance-holiday-work-confirm"),
    path(r"/periods/lock", v.AttendanceLock.as_view(), name="weapi.bd-attendance-lock"),
    path(r"/periods/reopen", v.AttendanceReopen.as_view(), name="weapi.bd-attendance-reopen"),
    path(r"/recompute", v.AttendanceRecompute.as_view(), name="weapi.bd-attendance-recompute"),
    path(r"/compliance", v.AttendanceCompliance.as_view(), name="weapi.bd-attendance-compliance"),
    path(r"/punches/import", v.AttendancePunchImport.as_view(), name="weapi.bd-attendance-punch-import"),
    path(r"/shifts", v.AttendanceShifts.as_view(), name="weapi.bd-attendance-shifts"),
    path(r"/shifts/assign", v.AttendanceShiftAssign.as_view(), name="weapi.bd-attendance-shift-assign"),
    path(r"/calendars/<int:year>", v.AttendanceCalendar.as_view(), name="weapi.bd-attendance-calendar"),
    path(r"/calendars/<int:year>/publish", v.AttendanceCalendarPublish.as_view(),
         name="weapi.bd-attendance-calendar-publish"),
    path(r"/elections", v.AttendanceElections.as_view(), name="weapi.bd-attendance-elections"),
]
