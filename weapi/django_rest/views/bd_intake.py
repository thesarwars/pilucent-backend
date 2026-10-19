"""The attendance intake API (docs/backend/attendance-intake-done.md §7), mounted
at /api/v1/we/attendance-intake: device profiles, upload, parse, validate,
process and reverse, device ID mapping, and the period stages and lock.

Permissions (§8): import_attendance, process_attendance_import,
override_attendance_import (distinct from processing),
reverse_attendance_import, map_device_users, advance_attendance_period,
manage_device_profiles -- and the register's own lock_attendance and
reopen_attendance, deliberately separate. Reading needs the employees
feature only.

Tenancy: every record is resolved with `company=`.
"""

from datetime import date

from django.http import FileResponse
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from employeeio.models import Employee, Site
from employeeio.services.salary_access import has_company_permission
from employeeio.services.sites import default_site
from intakeio.models import DeviceProfile, DeviceUserMap, ImportBatch, IntakeAudit
from intakeio.services import ops
from intakeio.services import parse as P
from intakeio.services.ops import IntakeRefused
from timekeepingio.services.base import AttendanceRefused, month_start

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

INTAKE = "intakeio"
IMPORT, PROCESS, OVERRIDE, REVERSE, MAP, ADVANCE, PROFILES = (
    "import_attendance", "process_attendance_import", "override_attendance_import", "reverse_attendance_import",
    "map_device_users", "advance_attendance_period", "manage_device_profiles")
LOCK, UNLOCK = "lock_attendance", "reopen_attendance"
NEEDS = {
    IMPORT: "Uploading and checking an import needs the 'import attendance' permission.",
    PROCESS: "Processing an import into the register needs the 'process attendance import' permission.",
    OVERRIDE: "Processing over warnings needs the 'override attendance import' permission, which is separate "
              "from processing.",
    REVERSE: "Reversing an import needs the 'reverse attendance import' permission.",
    MAP: "Mapping device IDs needs the 'map device users' permission.",
    ADVANCE: "Moving a period to processing or review needs the 'advance attendance period' permission.",
    PROFILES: "Device profiles need the 'manage device profiles' permission.",
    LOCK: "Locking a period needs the 'lock attendance' permission.",
    UNLOCK: "Unlocking a period needs the 'reopen attendance' permission, which is separate from locking.",
}
APP_OF = {LOCK: "timekeepingio", UNLOCK: "timekeepingio"}


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise IntakeRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


def _month(value):
    try:
        y, m = (int(x) for x in str(value).split("-")[:2])
        return date(y, m, 1)
    except (TypeError, ValueError):
        raise IntakeRefused({"month": ["month must be YYYY-MM."]}, status=400) from None


class IntakeView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, (IntakeRefused, AttendanceRefused)):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["consequence"] = exc.detail
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP_OF.get(codename, INTAKE))

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise IntakeRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def can(self):
        return {"import": self.may(IMPORT), "process": self.may(PROCESS), "override": self.may(OVERRIDE),
                "reverse": self.may(REVERSE), "map": self.may(MAP), "advance": self.may(ADVANCE),
                "profiles": self.may(PROFILES), "lock": self.may(LOCK), "unlock": self.may(UNLOCK)}

    def site(self, uid=None):
        uid = uid or self.request.query_params.get("site") or self.request.data.get("siteUid")
        company = self.company()
        if uid:
            return get_object_or_404(Site, uid=uid, company=company)
        return default_site(company)

    def batch(self, uid=None):
        return get_object_or_404(ImportBatch.objects.select_related("site", "profile"), uid=uid or self.kwargs["uid"],
                                 company=self.company())


def site_out(s):
    return {"uid": str(s.uid), "name": s.name, "isDefault": s.is_default}


class IntakeSummary(IntakeView):
    """What every screen shares: the establishments, the active profiles,
    the counts behind the tab badges and the enumerations."""

    def get(self, request):
        company = self.company()
        ops.ensure_profiles(company)
        sites = list(Site.objects.filter(company=company).order_by("-is_default", "name"))
        orphans = ops.unmapped(company)
        return Response({
            "sites": [site_out(s) for s in sites], "profiles": ops.profiles(company),
            "counts": {"unmappedIds": len(orphans), "orphanPunches": sum(o["punches"] for o in orphans),
                       "batches": ImportBatch.objects.filter(company=company).count(),
                       "awaiting": ImportBatch.objects.filter(company=company, status__in=(
                           "UPLOADED", "PARSED", "VALIDATED")).count()},
            "enums": {"formats": P.FORMATS, "encodings": list(P.ENCODINGS), "rowStructures": P.ROW_STRUCTURES,
                      "directions": P.DIRECTIONS, "matching": P.MATCHING, "dateFormats": P.DATE_FORMATS,
                      "timeFormats": P.TIME_FORMATS, "targets": P.TARGETS},
            "can": self.can(),
        })


class IntakeSample(IntakeView):
    def get(self, request):
        return Response({"fileName": "main-gate-sample.csv", "text": ops.sample_file(self.company())})


# ---------------------------------------------------------------- profiles


class IntakeProfiles(IntakeView):
    def get(self, request):
        return Response({"profiles": ops.profiles(self.company(), all_versions=bool(request.query_params.get("all"))),
                         "can": self.can()})

    def post(self, request):
        self.refuse_unless(PROFILES)
        p = ops.save_profile(self.company(), request.data, site=self.site(), user=request.user)
        return Response(ops.profile_out(p), status=status.HTTP_201_CREATED)


class IntakeProfile(IntakeView):
    def get(self, request, uid):
        p = get_object_or_404(DeviceProfile.objects.select_related("site"), uid=uid, company=self.company())
        versions = DeviceProfile.objects.filter(company=self.company(), code=p.code).order_by("-version")
        return Response({**ops.profile_out(p), "versions": [ops.profile_out(v) for v in versions]})

    def patch(self, request, uid):
        """A new version: the version a batch was parsed under stays as it was."""
        self.refuse_unless(PROFILES)
        p = get_object_or_404(DeviceProfile, uid=uid, company=self.company())
        return Response(ops.profile_out(ops.save_profile(self.company(), request.data, profile=p, user=request.user)))


class IntakeProfileTest(IntakeView):
    """Parse pasted text under a draft profile, nothing stored: the profile
    editor's preview."""

    def post(self, request):
        data = request.data
        base = {attr: data.get(key) for attr, key in ops.PROFILE_FIELDS if key in data}
        prof = P.Profile(**{k: v for k, v in {
            "format": base.get("format"), "encoding": "UTF-8", "delimiter": base.get("delimiter") or ",",
            "header_rows": int(base.get("header_rows") or 0), "row_structure": base.get("row_structure"),
            "date_format": base.get("date_format"), "time_format": base.get("time_format"),
            "combined_datetime": bool(base.get("combined_datetime")),
            "direction_handling": base.get("direction_handling"), "timezone": base.get("timezone") or "Asia/Dhaka",
            "column_map": base.get("column_map") or [], "pairs": base.get("pairs"),
            "century_base": int(base.get("century_base") or 2000)}.items() if v is not None})
        try:
            result = P.parse_file(str(data.get("text") or "").encode("utf-8"), prof)
        except P.ParseRefused as exc:
            raise IntakeRefused({"text": [str(exc)]}, status=422) from None
        out = P.summary(result, limit=20)
        out["sample"] = [{"row": x.row, "deviceUserId": x.device_user_id, "date": x.punch_date.isoformat(),
                          "time": x.punch_time.strftime("%H:%M:%S"), "direction": x.direction,
                          "discarded": x.discarded} for x in result.punches[:20]]
        return Response(out)


# ----------------------------------------------------------------- batches


class IntakeBatches(IntakeView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        site = self.site() if request.query_params.get("site") else None
        return Response({"batches": ops.history(self.company(), site=site), "can": self.can()})

    def post(self, request):
        """Upload: hashed, refused if the same file is already in, kept."""
        self.refuse_unless(IMPORT)
        f = request.FILES.get("file")
        if f is None:
            raise IntakeRefused({"file": ["Choose a device export to upload."]}, status=400)
        b = ops.upload(self.company(), self.site(), f, user=request.user)
        return Response(ops.batch_out(b, detail=True), status=status.HTTP_201_CREATED)


class IntakeBatch(IntakeView):
    def get(self, request, uid):
        company = self.company()
        b = self.batch(uid)
        out = ops.batch_out(b, detail=True)
        if b.status == "PROCESSED":
            out["reverseImpact"] = ops.reverse_impact(company, b)
        out["audit"] = [ops.audit_out(a) for a in IntakeAudit.objects.filter(batch=b)]
        out["sample"] = [{"row": p.source_row, "deviceUserId": p.device_user_id, "date": p.punch_date.isoformat(),
                          "time": p.punch_time.strftime("%H:%M:%S"), "direction": p.direction, "state": p.state,
                          "skipReason": p.skip_reason or None,
                          "employee": {"code": p.employee.code, "nameEn": p.employee.name_en} if p.employee_id else None}
                         for p in b.punches.select_related("employee").order_by("source_row", "punch_time")[:200]]
        out["can"] = self.can()
        return Response(out)


class IntakeBatchAction(IntakeView):
    def post(self, request, uid, action):
        company = self.company()
        b = self.batch(uid)
        d = request.data
        if action == "parse":
            self.refuse_unless(IMPORT)
            profile = get_object_or_404(DeviceProfile, uid=d.get("profileUid"), company=company) \
                if d.get("profileUid") else b.profile
            if profile is None:
                raise IntakeRefused({"profile": ["Choose the device profile before parsing: the date format comes "
                                                 "from it, never from a guess."]}, status=400)
            b, _ = ops.parse(company, b, profile=profile, stated_from=_date(d.get("statedFrom"), "statedFrom"),
                             stated_to=_date(d.get("statedTo"), "statedTo"), user=request.user)
            return Response(ops.batch_out(b, detail=True))
        if action == "validate":
            self.refuse_unless(IMPORT)
            b, _ = ops.validate(company, b, user=request.user)
            return Response(ops.batch_out(b, detail=True))
        if action == "process":
            self.refuse_unless(PROCESS)
            override = bool(d.get("overrideWarnings"))
            if override:
                self.refuse_unless(OVERRIDE)
            b = ops.process(company, b, override_warnings=override, user=request.user)
            return Response(ops.batch_out(b, detail=True))
        if action == "reverse":
            self.refuse_unless(REVERSE)
            b, impact = ops.reverse(company, b, reason=d.get("reason"), user=request.user)
            return Response({**ops.batch_out(b, detail=True), "impact": impact})
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class IntakeBatchRaw(IntakeView):
    """The retained file, byte for byte."""

    def get(self, request, uid):
        self.refuse_unless(IMPORT)
        b = self.batch(uid)
        resp = FileResponse(ops.raw_bytes(b), as_attachment=True, filename=b.file_name,
                            content_type="application/octet-stream")
        resp["X-File-SHA256"] = b.file_sha256
        return resp


# ----------------------------------------------------------------- mapping


class IntakeDeviceIds(IntakeView):
    def get(self, request):
        company = self.company()
        maps = DeviceUserMap.objects.filter(company=company).select_related("employee")
        return Response({"unmapped": ops.unmapped(company), "mappings": [ops.map_out(m) for m in maps],
                         "can": self.can()})


class IntakeDeviceMaps(IntakeView):
    def post(self, request):
        self.refuse_unless(MAP)
        company = self.company()
        d = request.data
        employee = get_object_or_404(Employee, company=company, code=str(d.get("employeeCode") or "").strip())
        m, out = ops.create_mapping(company, device_label=d.get("deviceLabel"), device_user_id=d.get("deviceUserId"),
                                    employee=employee,
                                    effective_from=_date(d.get("effectiveFrom"), "effectiveFrom") or date(2000, 1, 1),
                                    user=request.user)
        return Response({"mapping": ops.map_out(m), **out}, status=status.HTTP_201_CREATED)


class IntakeDeviceMapClose(IntakeView):
    def post(self, request, uid):
        self.refuse_unless(MAP)
        company = self.company()
        m = get_object_or_404(DeviceUserMap.objects.select_related("employee"), uid=uid, company=company)
        to = _date(request.data.get("effectiveTo"), "effectiveTo")
        if to is None:
            raise IntakeRefused({"effectiveTo": ["Give the last day the mapping holds."]}, status=400)
        return Response(ops.map_out(ops.close_mapping(company, m, effective_to=to, user=request.user)))


# ----------------------------------------------------------------- periods


class IntakePeriods(IntakeView):
    def get(self, request):
        company = self.company()
        site = self.site()
        audit = IntakeAudit.objects.filter(company=company, site=site, action__in=(
            "PERIOD_ADVANCED", "PERIOD_LOCKED", "PERIOD_UNLOCKED"))[:40]
        return Response({"site": site_out(site), "periods": ops.periods(company, site),
                         "audit": [ops.audit_out(a) for a in audit], "can": self.can()})


class IntakePeriodAction(IntakeView):
    def post(self, request, month, action):
        company = self.company()
        site = self.site()
        m = month_start(_month(month))
        d = request.data
        if action == "advance":
            from timekeepingio.services.base import ensure_period

            stage = ensure_period(company, site, m).stage
            self.refuse_unless(LOCK if stage == "REVIEW" else ADVANCE)
            ack = d.get("acknowledgeReason")
            return Response(ops.advance(company, site, m, acknowledge_reason=ack if ack else None, user=request.user))
        if action == "unlock":
            self.refuse_unless(UNLOCK)
            return Response(ops.unlock(company, site, m, reason=d.get("reason"), user=request.user,
                                       confirmed_invalidates_payroll=bool(d.get("confirmedInvalidatesPayroll"))))
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)
