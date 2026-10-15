"""The attendance API (docs/backend/attendance.md §9), mounted at
/api/v1/we/attendance: the grid, a day, exceptions, month close and
compliance, and the writes behind them.

Days are computed on every read from punches, adjustments, shifts and the
published calendar; nothing derived is read back (§1). Every write refuses
on a locked month and goes to the audit.

Permissions (§11): writing is `write_attendance`; a statutory breach is
acknowledged with `acknowledge_attendance`; locking and reopening are two
separate permissions, so one person cannot close and reopen a month alone.
Overtime cost is masked without `view_salary_figures`.

Tenancy: every employee, site and shift is resolved with `company=`.
"""

from datetime import date

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from common import clock
from employeeio.models import Employee
from employeeio.services.salary_access import has_company_permission
from employeeio.services.sites import sites_of
from timekeepingio.models import Shift
from timekeepingio.services import ops
from timekeepingio.services.base import (
    AttendanceRefused,
    current_assignment,
    parse_month,
    shifts_of,
    site_employees,
    site_for,
)

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "timekeepingio"
WRITE, ACKNOWLEDGE, LOCK, REOPEN = "write_attendance", "acknowledge_attendance", "lock_attendance", "reopen_attendance"
NEEDS = {
    WRITE: "Changing attendance needs the 'write attendance' permission.",
    ACKNOWLEDGE: "Acknowledging a statutory breach needs the 'acknowledge attendance' permission.",
    LOCK: "Locking a month needs the 'lock attendance' permission.",
    REOPEN: "Reopening a locked month needs the 'reopen attendance' permission, which is separate from locking.",
}


def _date(value, field="date"):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise AttendanceRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}) from None


def _minute(value, field):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise AttendanceRefused({field: [f"{field} is minutes from midnight."]}) from None


class AttendanceView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, AttendanceRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["consequence"] = exc.detail  # the employee kit's ApiError carries this key
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def param(self, name, default=None):
        value = self.request.data.get(name) if self.request.method != "GET" else None
        return value if value not in (None, "") else self.request.query_params.get(name, default)

    def site(self):
        return site_for(self.company(), self.param("site") or None)

    def month(self):
        return parse_month(self.param("month") or clock.today().strftime("%Y-%m"))

    def employee(self):
        code = str(self.param("employeeCode") or "").strip()
        return get_object_or_404(Employee.objects.select_related("site", "company"), code=code,
                                 company=self.company())

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise AttendanceRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def abilities(self):
        return {"write": self.may(WRITE), "acknowledge": self.may(ACKNOWLEDGE), "lock": self.may(LOCK),
                "reopen": self.may(REOPEN), "figures": self.salary_figures()}


# ------------------------------------------------------------------ reads


class AttendanceSites(AttendanceView):
    def get(self, request):
        return Response({"rows": [{"uid": str(s.uid), "code": s.code, "name": s.name, "nameBn": s.name_bn or None,
                                   "isDefault": s.is_default} for s in sites_of(self.company())],
                         "can": self.abilities()})


class AttendanceGrid(AttendanceView):
    def get(self, request):
        out = ops.grid(self.company(), self.site(), self.month(), dept=request.query_params.get("dept") or None,
                       q=(request.query_params.get("q") or "").strip(),
                       exceptions_only=request.query_params.get("exceptionsOnly") in ("1", "true"),
                       page=request.query_params.get("page") or 1, limit=request.query_params.get("limit") or 100)
        out["can"] = self.abilities()
        return Response(out)


class AttendanceDay(AttendanceView):
    def get(self, request):
        employee = self.employee()
        out = ops.day_detail(self.company(), employee, _date(request.query_params.get("date")),
                             figures=self.salary_figures())
        out["can"] = self.abilities()
        return Response(out)


class AttendanceExceptions(AttendanceView):
    def get(self, request):
        return Response(ops.exceptions_list(self.company(), self.site(), self.month(),
                                            include_decided=request.query_params.get("all") in ("1", "true")))


class AttendanceClose(AttendanceView):
    def get(self, request):
        out = ops.close_summary(self.company(), self.site(), self.month())
        out["can"] = self.abilities()
        return Response(out)


class AttendanceCompliance(AttendanceView):
    def get(self, request):
        return Response(ops.compliance(self.company(), self.site(), self.month()))


# ----------------------------------------------------------------- writes


class AttendanceAdjustments(AttendanceView):
    def post(self, request):
        self.refuse_unless(WRITE)
        d = request.data
        ops.adjust(self.company(), self.employee(), _date(d.get("date"), "date"),
                   new_status=d.get("newStatus") or "", in_time_min=_minute(d.get("inTimeMin"), "inTimeMin"),
                   out_time_min=_minute(d.get("outTimeMin"), "outTimeMin"), reason=d.get("reason"),
                   note=d.get("note") or "", user=request.user)
        return self._day(status.HTTP_201_CREATED)

    def _day(self, code):
        out = ops.day_detail(self.company(), self.employee(), _date(self.request.data.get("date")),
                             figures=self.salary_figures())
        out["can"] = self.abilities()
        return Response(out, status=code)


class AttendanceAdjustmentRemove(AttendanceAdjustments):
    def post(self, request):
        self.refuse_unless(WRITE)
        ops.remove_adjustment(self.company(), self.employee(), _date(request.data.get("date")),
                              reason=request.data.get("reason"), user=request.user)
        return self._day(status.HTTP_200_OK)


class AttendanceResolve(AttendanceAdjustments):
    def post(self, request):
        self.refuse_unless(WRITE)
        d = request.data
        ops.resolve(self.company(), self.employee(), _date(d.get("date")), str(d.get("kind") or ""),
                    str(d.get("action") or "").upper(), reason=d.get("reason") or "",
                    in_time_min=_minute(d.get("inTimeMin"), "inTimeMin"),
                    out_time_min=_minute(d.get("outTimeMin"), "outTimeMin"), user=request.user)
        return self._day(status.HTTP_200_OK)


class AttendanceAcknowledge(AttendanceAdjustments):
    def post(self, request):
        self.refuse_unless(ACKNOWLEDGE)
        d = request.data
        ops.acknowledge(self.company(), self.employee(), _date(d.get("date")), str(d.get("kind") or ""),
                        reason=d.get("reason"), user=request.user)
        return self._day(status.HTTP_200_OK)


class AttendanceHolidayWorkConfirm(AttendanceView):
    def post(self, request):
        self.refuse_unless(WRITE)
        out = ops.confirm_holiday_work(self.company(), self.site(), self.month(),
                                       reason=request.data.get("reason") or "", user=request.user)
        return Response(out)


class AttendanceLock(AttendanceView):
    def post(self, request):
        self.refuse_unless(LOCK)
        period = ops.lock(self.company(), self.site(), self.month(), user=request.user)
        return Response({"period": ops.period_out(period)})


class AttendanceReopen(AttendanceView):
    def post(self, request):
        self.refuse_unless(REOPEN)
        period = ops.reopen(self.company(), self.site(), self.month(), reason=request.data.get("reason"),
                            user=request.user)
        return Response({"period": ops.period_out(period)})


class AttendanceRecompute(AttendanceView):
    def post(self, request):
        return Response(ops.recompute(self.company(), self.site(), self.month(), user=request.user))


class AttendancePunchImport(AttendanceView):
    def post(self, request):
        self.refuse_unless(WRITE)
        rows = request.data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise AttendanceRefused({"rows": ["Send rows: [{employeeCode, punchedAt, direction}]."]})
        if len(rows) > 20000:
            raise AttendanceRefused({"rows": ["At most 20,000 punches per import."]})
        rows = [r if isinstance(r, dict) else {"raw": r} for r in rows]
        return Response(ops.import_punches(self.company(), self.site(), rows, user=request.user),
                        status=status.HTTP_201_CREATED)


# ------------------------------------------------------- shifts, calendar


class AttendanceShifts(AttendanceView):
    def get(self, request):
        site = self.site()
        today = clock.today()
        employees = list(site_employees(self.company(), site))
        unassigned = [{"code": e.code, "nameEn": e.name_en,
                       "department": e.department.title if e.department else None}
                      for e in employees if current_assignment(e, today) is None]
        return Response({"rows": [ops.shift_out(s) for s in shifts_of(site, today)], "unassigned": unassigned,
                         "site": {"uid": str(site.uid), "name": site.name}, "can": self.abilities()})

    def post(self, request):
        self.refuse_unless(WRITE)
        shift = ops.create_shift(self.company(), self.site(), request.data, user=request.user)
        return Response(ops.shift_out(shift), status=status.HTTP_201_CREATED)


class AttendanceShiftAssign(AttendanceView):
    def post(self, request):
        self.refuse_unless(WRITE)
        d = request.data
        shift = get_object_or_404(Shift, uid=d.get("shift"), company=self.company())
        codes = d.get("employeeCodes") or []
        if not isinstance(codes, list) or not codes:
            raise AttendanceRefused({"employeeCodes": ["Choose at least one employee."]})
        employees = list(Employee.objects.filter(company=self.company(), code__in=codes).select_related("site"))
        missing = sorted(set(codes) - {e.code for e in employees})
        if missing:
            raise AttendanceRefused({"employeeCodes": [f"No employee {', '.join(missing)}."]}, status=404)
        effective = _date(d["effectiveFrom"], "effectiveFrom") if d.get("effectiveFrom") else None
        done = ops.assign_shift(self.company(), shift, employees, effective, user=request.user)
        return Response({"assigned": done})


class AttendanceCalendar(AttendanceView):
    def get(self, request, year):
        out = ops.calendar_out(self.site(), year)
        out["can"] = self.abilities()
        return Response(out)

    def put(self, request, year):
        self.refuse_unless(WRITE)
        d = request.data
        ops.save_calendar(self.company(), self.site(), year, weekly_pattern=d.get("weeklyPattern") or {},
                          days=d.get("days") or [], consulted_with=d.get("consultedWith") or "", user=request.user)
        return Response(ops.calendar_out(self.site(), year))


class AttendanceCalendarPublish(AttendanceView):
    def post(self, request, year):
        self.refuse_unless(WRITE)
        ops.publish_calendar(self.company(), self.site(), year, user=request.user)
        return Response(ops.calendar_out(self.site(), year))


class AttendanceElections(AttendanceView):
    def get(self, request):
        return Response(ops.elections_of(self.company()))

    def patch(self, request):
        self.refuse_unless(WRITE)
        d = request.data
        worked = d.get("daysWorked") or {}
        return Response(ops.save_elections(self.company(), overtime_base=d.get("overtimeBase"),
                                           paid_leave=worked.get("paidLeave"), festival=worked.get("festival"),
                                           weekly=worked.get("weekly")))
