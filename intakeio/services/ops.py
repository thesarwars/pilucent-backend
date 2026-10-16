"""Attendance intake operations (backend spec §7): device profiles, upload,
parse, validate, process, reverse, device ID mapping and the period stages.

Intake feeds the attendance register. Processing writes each attributed
punch to `timekeepingio.Punch`; a reversal voids those register punches
(`PunchVoid`) and the days recompute; the period and its lock are the
register's (`AttendancePeriod`). Corrections to a day stay the register's
own adjustments, which a reversal leaves in place.
"""

import hashlib
import io
from collections import defaultdict
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from common import clock
from employeeio.models import Employee
from employeeio.services.sites import site_of
from timekeepingio.choices import PeriodStatusChoices, PunchSourceChoices
from timekeepingio.models import Adjustment, AttendancePeriod, Punch, PunchVoid
from timekeepingio.services import ops as register
from timekeepingio.services.base import assignments_by_employee, business_date_and_minute, ensure_period
from timekeepingio.services.base import month_end, month_start, shift_on

from ..models import DeviceProfile, DeviceUserMap, ImportBatch, IntakeAudit, IntakeEvent, IntakePunch
from . import parse as P

MIN_REASON = 10


class IntakeRefused(Exception):
    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _reason(text, what="a reason"):
    text = str(text or "").strip()
    if len(text) < MIN_REASON:
        raise IntakeRefused({"reason": [f"Give {what}, at least {MIN_REASON} characters ({len(text)} so far)."]})
    return text


def audit(company, action, user=None, *, batch=None, site=None, month=None, reason="", before=None, after=None):
    IntakeAudit.objects.create(company=company, action=action, batch=batch, site=site or (batch.site if batch else None),
                               period_month=month, actor=_who(user), actor_name=_name(user), reason=reason or "",
                               before_json=before, after_json=after)


# ------------------------------------------------------------------ events

# Event -> (notification kind, the permissions whose holders hear of it)
ROUTES = {
    "OrphanPunchesDetected": ("INTAKE_ORPHANS_DETECTED", (("intakeio", "map_device_users"),)),
    "AttendanceBatchReversed": ("INTAKE_BATCH_REVERSED", (("intakeio", "process_attendance_import"),)),
    "AttendancePeriodUnlocked": ("ATTENDANCE_PERIOD_UNLOCKED", (("timekeepingio", "lock_attendance"),
                                                                ("intakeio", "process_attendance_import"))),
}


def holders(company, app, codename):
    from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
    from accounts.models import User

    held = (Q(companyuser__company=company, companyuser__roles__company=company,
              companyuser__roles__name=ADMIN_GROUP_NAME, companyuser__roles__is_system=True)
            | Q(companyuser__company=company, companyuser__roles__permission__codename=codename,
                companyuser__roles__permission__content_type__app_label=app)
            | Q(companyuser__company=company, companyuser__permission__codename=codename,
                companyuser__permission__content_type__app_label=app))
    return list(User.objects.filter(held).exclude(status__in=["INACTIVE", "REMOVED"]).distinct())


def event(company, name, *, message="", actor=None, **payload):
    """The outbox row, and a notification where the event needs a person."""
    ev = IntakeEvent.objects.create(company=company, name=name, payload=payload)
    route = ROUTES.get(name)
    if route:
        from notificationio.choices import NotificationModelKindChoices, NotificationStatusChoices
        from notificationio.services.notifications import NotificationService

        kind, perms = route
        users = {u.pk: u for app, code in perms for u in holders(company, app, code)}
        users.pop(getattr(actor, "pk", None), None)
        if users:
            NotificationService.create_notification(
                status=NotificationStatusChoices.PUBLISHED, model_kind=NotificationModelKindChoices.ATTENDANCE_INTAKE,
                kind=kind, message=(message or name)[:100], is_company=True, users=list(users.values()))
    return ev


# ================================================================= profiles

PROFILE_FIELDS = (
    ("name", "name"), ("name_bn", "nameBn"), ("device_label", "deviceLabel"), ("device_model", "deviceModel"),
    ("location", "location"), ("format", "format"), ("encoding", "encoding"), ("delimiter", "delimiter"),
    ("header_rows", "headerRows"), ("row_structure", "rowStructure"), ("date_format", "dateFormat"),
    ("time_format", "timeFormat"), ("combined_datetime", "combinedDateTime"),
    ("direction_handling", "directionHandling"), ("employee_matching", "employeeMatching"), ("timezone", "timezone"),
    ("century_base", "centuryBase"), ("column_map", "columns"), ("pairs", "pairs"), ("sample_header", "sampleHeader"),
)


def profile_out(p, batches=None):
    out = {"uid": str(p.uid), "code": p.code, "version": p.version, "site": {"uid": str(p.site.uid), "name": p.site.name},
           "isActive": p.is_active, "createdBy": p.created_by_name or None, "createdAt": p.created_at.isoformat()}
    for attr, key in PROFILE_FIELDS:
        out[key] = getattr(p, attr)
    if batches is not None:
        out["batches"] = batches
    return out


def parser_profile(p):
    return P.Profile(format=p.format, encoding=p.encoding, delimiter=p.delimiter or ",", header_rows=p.header_rows,
                     row_structure=p.row_structure, date_format=p.date_format, time_format=p.time_format,
                     combined_datetime=p.combined_datetime, direction_handling=p.direction_handling,
                     employee_matching=p.employee_matching, timezone=p.timezone, column_map=p.column_map or [],
                     pairs=p.pairs, century_base=p.century_base)


def _check_profile(d):
    errors = {}

    def bad(key, msg):
        errors.setdefault(key, []).append(msg)

    if not str(d.get("name") or "").strip():
        bad("name", "A profile needs a name.")
    if not str(d.get("device_label") or "").strip():
        bad("deviceLabel", "Name the device: punches are mapped by device and device user ID.")
    checks = (("format", P.FORMATS), ("encoding", tuple(P.ENCODINGS)), ("row_structure", P.ROW_STRUCTURES),
              ("direction_handling", P.DIRECTIONS), ("employee_matching", P.MATCHING),
              ("date_format", P.DATE_FORMATS), ("time_format", P.TIME_FORMATS))
    keys = dict(PROFILE_FIELDS)
    for attr, allowed in checks:
        if d.get(attr) not in allowed:
            bad(keys[attr], f"{keys[attr]} is one of {', '.join(allowed)}.")
    if not 0 <= int(d.get("header_rows") or 0) <= 10:
        bad("headerRows", "Between 0 and 10 header rows.")
    cols = d.get("column_map") or []
    targets = [c.get("target") for c in cols if isinstance(c, dict)]
    if any(t not in P.TARGETS for t in targets):
        bad("columns", f"A column maps to one of {', '.join(P.TARGETS)}.")
    if not ({"deviceUserId", "employeeCode"} & set(targets)):
        bad("columns", "Map a column to deviceUserId or employeeCode.")
    if d.get("combined_datetime"):
        if "datetime" not in targets:
            bad("columns", "A combined date and time needs a datetime column.")
    elif "date" not in targets:
        bad("columns", "Map a column to date.")
    if d.get("row_structure") == "PAIRED_COLUMNS":
        if d.get("direction_handling") != "PAIRED":
            bad("directionHandling", "Paired columns carry their own direction: choose Paired.")
        if not d.get("pairs") and not {"inTime", "outTime"} <= set(targets):
            bad("pairs", "A paired profile declares its pairs, or maps inTime and outTime.")
    elif d.get("direction_handling") == "PAIRED":
        bad("directionHandling", "Paired direction needs paired columns.")
    elif "time" not in targets and not d.get("combined_datetime"):
        bad("columns", "Map a column to time.")
    if d.get("direction_handling") == "EXPLICIT_COLUMN" and "direction" not in targets:
        bad("columns", "An explicit direction needs a direction column.")
    if d.get("format") == "FIXED" and any(not c.get("width") for c in cols):
        bad("columns", "A fixed-width column needs a start and a width.")
    try:
        P.zone(d.get("timezone"))
    except P.ParseRefused as exc:
        bad("timezone", str(exc))
    if errors:
        raise IntakeRefused(errors, status=400)


def save_profile(company, data, *, profile=None, site=None, user=None):
    """A new profile, or the next version of one. A version that parsed a
    batch is never edited: the batch must re-parse to the same punches."""
    from employeeio.models import Site

    base = {attr: getattr(profile, attr) for attr, _ in PROFILE_FIELDS} if profile else {}
    for attr, key in PROFILE_FIELDS:
        if key in data:
            base[attr] = data[key]
    base.setdefault("delimiter", ","), base.setdefault("header_rows", 1), base.setdefault("timezone", "Asia/Dhaka")
    base.setdefault("century_base", 2000), base.setdefault("encoding", "UTF-8"), base.setdefault("format", "CSV")
    base.setdefault("combined_datetime", False)
    for k in ("name", "name_bn", "device_label", "device_model", "location", "sample_header"):
        base[k] = str(base.get(k) or "").strip()
    base["header_rows"] = int(base.get("header_rows") or 0)
    base["century_base"] = int(base.get("century_base") or 2000)
    base["combined_datetime"] = bool(base.get("combined_datetime"))
    _check_profile(base)
    if profile is None:
        site = site or (Site.objects.filter(company=company, uid=data.get("siteUid")).first() if data.get("siteUid")
                        else None)
        if site is None:
            raise IntakeRefused({"site": ["Choose the establishment the device is at."]}, status=400)
        code = str(data.get("code") or "").strip().upper().replace(" ", "-")
        if not code:
            raise IntakeRefused({"code": ["A profile needs a code, e.g. DP-GAZ-GATE."]}, status=400)
        if DeviceProfile.objects.filter(company=company, code=code).exists():
            raise IntakeRefused({"code": [f"A profile {code} already exists."]}, status=409)
        version = 1
    else:
        site, code = profile.site, profile.code
        version = DeviceProfile.objects.filter(company=company, code=code).order_by("-version").first().version + 1
    with transaction.atomic():
        DeviceProfile.objects.filter(company=company, code=code, is_active=True).update(is_active=False)
        p = DeviceProfile.objects.create(company=company, site=site, code=code, version=version, created_by=_who(user),
                                         created_by_name=_name(user), **base)
        audit(company, "PROFILE_PUBLISHED", user, site=site, after={"code": code, "version": version})
    return p


def profiles(company, *, site=None, all_versions=False):
    ensure_profiles(company)
    qs = DeviceProfile.objects.filter(company=company).select_related("site")
    if site is not None:
        qs = qs.filter(site=site)
    if not all_versions:
        qs = qs.filter(is_active=True)
    counts = defaultdict(int)
    for pid in ImportBatch.objects.filter(company=company).exclude(profile__isnull=True).values_list("profile_id",
                                                                                                     flat=True):
        counts[pid] += 1
    return [profile_out(p, counts[p.pk]) for p in qs.order_by("site__name", "code", "-version")]


def ensure_profiles(company):
    """Two profiles from the design, at the default site, on first use: an
    event-log CSV terminal and a paired-columns workbook."""
    if DeviceProfile.objects.filter(company=company).exists():
        return
    from employeeio.services.sites import default_site

    site = default_site(company)
    with transaction.atomic():
        DeviceProfile.objects.create(
            company=company, site=site, code="DP-MAIN-GATE", name="Main gate terminal", device_label="Main gate",
            device_model="ZKTeco K40", location=site.name, format="CSV", encoding="UTF-8", delimiter=",",
            header_rows=1, row_structure="EVENT_LOG", date_format="DD/MM/YYYY", time_format="HH:mm:ss",
            direction_handling="EXPLICIT_COLUMN", employee_matching="DEVICE_ID_MAP",
            column_map=[{"source": "UserID", "target": "deviceUserId"}, {"source": "Date", "target": "date"},
                        {"source": "Time", "target": "time"}, {"source": "State", "target": "direction"},
                        {"source": "Terminal", "target": "terminal"}],
            sample_header="UserID,Date,Time,State,Terminal")
        DeviceProfile.objects.create(
            company=company, site=site, code="DP-OFFICE-PAIRED", name="Office — paired columns export",
            device_label="Office", device_model="Suprema BioStation 2", location=site.name, format="XLSX",
            header_rows=1, row_structure="PAIRED_COLUMNS", date_format="YYYY-MM-DD", time_format="HH:mm",
            direction_handling="PAIRED", employee_matching="EMPLOYEE_CODE",
            column_map=[{"source": "EmpCode", "target": "employeeCode"}, {"source": "WorkDate", "target": "date"},
                        {"source": "InTime", "target": "inTime"}, {"source": "OutTime", "target": "outTime"}],
            sample_header="EmpCode\tWorkDate\tInTime\tOutTime")


def sample_file(company):
    """A small export for the main-gate profile, so the importer can be tried
    before a device is connected: a few employees, one unmapped device ID,
    one bad date and a small-hours punch."""
    codes = list(Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
                 .order_by("code").values_list("code", flat=True)[:3])
    ids = ["".join(ch for ch in c if ch.isdigit())[-4:].rjust(4, "0") for c in codes] or ["0001"]
    today = clock.today()
    days = [today - timedelta(days=n) for n in (2, 1)]
    lines = ["UserID,Date,Time,State,Terminal"]
    for d in days:
        for n, i in enumerate(ids):
            lines.append(f"{i},{d:%d/%m/%Y},07:{46 + n * 5:02d}:12,IN,Main Gate")
            lines.append(f"{i},{d:%d/%m/%Y},17:{5 + n * 4:02d}:44,OUT,Main Gate")
    lines.append(f'0217,{days[0]:%d/%m/%Y},08:01:55,IN,"Main Gate, East"')
    lines.append(f"0217,{days[0]:%d/%m/%Y},19:44:02,OUT,Main Gate")
    lines.append(f"{ids[0]},31/02/{today.year},07:50:00,IN,Main Gate")
    lines.append(f"0221,{days[1]:%d/%m/%Y},02:14:00,IN,Main Gate")
    return "\n".join(lines) + "\n"


# ================================================================== batches


def batch_out(b, *, detail=False):
    out = {
        "uid": str(b.uid), "reference": b.reference, "fileName": b.file_name, "bytes": b.file_bytes,
        "sha256": b.file_sha256, "status": b.status, "site": {"uid": str(b.site.uid), "name": b.site.name},
        "profile": {"uid": str(b.profile.uid), "code": b.profile.code, "name": b.profile.name,
                    "version": b.profile_version} if b.profile_id else None,
        "statedRange": {"from": b.stated_from.isoformat(), "to": b.stated_to.isoformat()} if b.stated_from else None,
        "parsedRange": {"from": b.parsed_from.isoformat(), "to": b.parsed_to.isoformat()} if b.parsed_from else None,
        "rows": {"total": b.rows_total, "parsed": b.rows_parsed, "failed": b.rows_failed},
        "punches": {"imported": b.punches_imported, "skipped": b.punches_skipped, "orphaned": b.punches_orphaned},
        "uploadedBy": b.uploaded_by_name or None, "uploadedAt": b.created_at.isoformat(),
        "processedAt": b.processed_at.isoformat() if b.processed_at else None,
        "processedBy": b.processed_by_name or None,
        "reversedAt": b.reversed_at.isoformat() if b.reversed_at else None, "reversedBy": b.reversed_by_name or None,
        "reverseReason": b.reverse_reason or None,
    }
    if detail:
        # Where the punches stand now: a mapping attaches held punches after processing.
        now = {s: 0 for s in ("ACTIVE", "ORPHAN", "SKIPPED", "REVERSED")}
        for state, n in b.punches.values_list("state").annotate(n=Count("id")).values_list("state", "n"):
            now[state] = n
        out.update(parse=b.parse_json, errors=b.parse_errors_json or [], findings=b.validation_json,
                   processedOver=b.processed_over,
                   now={"active": now["ACTIVE"], "held": now["ORPHAN"], "skipped": now["SKIPPED"],
                        "reversed": now["REVERSED"], "relinked": b.punches.filter(relinked_at__isnull=False).count()})
    return out


def _next_reference(company):
    last = (ImportBatch.objects.filter(company=company).order_by("-created_at").values_list("reference", flat=True)
            .first())
    n = int(last.split("-")[1]) + 1 if last else 1
    while ImportBatch.objects.filter(company=company, reference=f"IMP-{n:04d}").exists():
        n += 1
    return f"IMP-{n:04d}"


def upload(company, site, upload_file, *, user=None):
    """§7.1. The bytes are hashed before anything else: the same export twice
    doubles every punch in it."""
    raw = upload_file.read()
    if not raw:
        raise IntakeRefused({"file": ["The file is empty."]}, status=400)
    if len(raw) > P.MAX_BYTES:
        raise IntakeRefused({"file": ["The file is over 25 MB. Split the export by date range."]}, status=400)
    sha = hashlib.sha256(raw).hexdigest()
    twin = ImportBatch.objects.filter(company=company, file_sha256=sha).exclude(status="REVERSED").first()
    if twin:
        hint = ("Reverse that import first to load it again." if twin.status == "PROCESSED"
                else "It was never processed: continue that import instead.")
        raise IntakeRefused({"file": [f"This exact file was already uploaded as {twin.reference} on "
                                      f"{twin.created_at:%d %b %Y}. {hint}"]},
                            status=409, detail={"batch": twin.reference, "uid": str(twin.uid), "status": twin.status})
    name = (getattr(upload_file, "name", "") or "export").split("/")[-1][:200]
    with transaction.atomic():
        b = ImportBatch(company=company, reference=_next_reference(company), site=site, file_name=name,
                        file_sha256=sha, file_bytes=len(raw), uploaded_by=_who(user), uploaded_by_name=_name(user))
        b.file.save(f"{sha[:16]}-{name}", ContentFile(raw), save=False)
        try:
            b.save()
        except IntegrityError:
            raise IntakeRefused({"file": ["This exact file was already uploaded."]}, status=409) from None
        audit(company, "BATCH_UPLOADED", user, batch=b, after={"file": name, "bytes": len(raw), "sha256": sha})
    return b


def _raw(b):
    with b.file.open("rb") as f:
        return f.read()


def _parse(b, profile):
    try:
        return P.parse_file(_raw(b), parser_profile(profile))
    except P.ParseRefused as exc:
        raise IntakeRefused({"profile": [str(exc)]}, status=422) from None


def parse(company, b, *, profile, stated_from=None, stated_to=None, user=None):
    """§7.2. Idempotent: parsing again under another profile replaces the
    result, and is audited."""
    if b.status not in ("UPLOADED", "PARSED", "VALIDATED", "FAILED"):
        raise IntakeRefused({"batch": [f"{b.reference} is {b.status.lower()}; it is not parsed again."]}, status=409)
    if stated_from and stated_to and stated_to < stated_from:
        raise IntakeRefused({"statedRange": ["The range ends before it starts."]}, status=400)
    result = _parse(b, profile)
    before = {"profile": b.profile.code if b.profile_id else None, "version": b.profile_version} if b.profile_id else None
    summ = P.summary(result)
    with transaction.atomic():
        b.profile, b.profile_version, b.file_encoding = profile, profile.version, profile.encoding
        b.stated_from, b.stated_to = stated_from, stated_to
        b.parsed_from, b.parsed_to = (result.date_range if result.date_range else (None, None))
        b.rows_total, b.rows_parsed, b.rows_failed = result.rows_total, result.rows_parsed, summ["rowsFailed"]
        b.parse_json = {**summ, "errors": None}
        b.parse_errors_json = result.errors
        b.validation_json = None
        b.status = "PARSED"
        b.save()
        audit(company, "BATCH_PARSED", user, batch=b, before=before,
              after={"profile": profile.code, "version": profile.version, "punches": summ["punches"],
                     "errors": summ["errorsTotal"]})
    return b, result


# ---------------------------------------------------------------- resolve


class Resolver:
    """Who each punch belongs to: a device mapping in force on the punch's
    date first, then the profile's own matching (employee code or NID)."""

    def __init__(self, company, profile):
        self.company, self.profile = company, profile
        self.maps = defaultdict(list)
        for m in DeviceUserMap.objects.filter(company=company, device_label=profile.device_label).select_related(
                "employee"):
            self.maps[m.device_user_id].append(m)
        self.by_code, self.by_nid = {}, {}
        if profile.employee_matching in ("EMPLOYEE_CODE", "NID"):
            for e in Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT")):
                self.by_code[e.code.upper()] = e
                if e.nid:
                    self.by_nid[e.nid.strip()] = e

    def employee(self, device_user_id, d):
        for m in self.maps.get(device_user_id, []):
            if m.effective_from <= d and (m.effective_to is None or m.effective_to >= d):
                return m.employee
        if self.profile.employee_matching == "EMPLOYEE_CODE":
            return self.by_code.get(device_user_id.upper())
        if self.profile.employee_matching == "NID":
            return self.by_nid.get(device_user_id)
        return None


class Periods:
    """Locked months, by site, read once."""

    def __init__(self, company):
        self.company = company
        self.locked = {(p.site_id, p.period_month) for p in AttendancePeriod.objects.filter(
            company=company, status=PeriodStatusChoices.LOCKED)}

    def is_locked(self, site, d):
        return (site.pk, month_start(d)) in self.locked


def _business_date(employee, punch):
    windows = assignments_by_employee([employee], punch.punch_date - timedelta(days=1), punch.punch_date)
    bd, _ = business_date_and_minute(punch.punched_at, windows.get(employee.pk))
    return bd, shift_on(windows.get(employee.pk), bd) is not None


# --------------------------------------------------------------- validate

BEHAVIOUR = {
    "locked": "Blocked. Unlock the period and re-import, or exclude those days.",
    "duplicates": "Skipped by default. Reviewable.",
    "outsideRange": "Warned. Import proceeds.",
    "separated": "Warned, with the separation date. Import proceeds.",
    "drift": "Warned. Usually device clock drift; check the device's time.",
    "unmapped": "Stored against the device ID and attached the moment a mapping is created. Nothing is discarded.",
    "discarded": "Stored as skipped, not counted: first and last of the day are kept.",
    "noShift": "Imported. The register shows those days as without a shift until one is assigned.",
    "overlap": "Merged: punches already imported are skipped as duplicates.",
    "parseErrors": "Those rows are not imported. Fix the export or the profile and upload again.",
}


def findings(company, b, result):
    """§5. Each finding states its severity and, in words, what happens."""
    profile = b.profile
    resolver, periods = Resolver(company, profile), Periods(company)
    groups = []

    def group(gid, severity, title, items):
        if items:
            groups.append({"id": gid, "severity": severity, "title": title, "count": len(items), "items": items[:12],
                           "behaviour": BEHAVIOUR[gid]})

    existing = set(IntakePunch.objects.filter(company=company, device_label=profile.device_label,
                                              state__in=("ACTIVE", "ORPHAN"))
                   .values_list("device_user_id", "punched_at"))
    seen, dupes, locked, outside, separated, drift, unmapped, no_shift = set(), [], defaultdict(int), [], [], [], \
        defaultdict(int), defaultdict(int)
    for x in result.punches:
        if x.discarded:
            continue
        key = (x.device_user_id, x.punch_date, x.punch_time)
        if key in seen or (x.device_user_id, x.punched_at) in existing:
            dupes.append({"label": f"{x.device_user_id} at {x.punch_time:%H:%M:%S} on {x.punch_date:%d %b %Y}",
                          "detail": f"row {x.row}: " + ("already imported" if key not in seen else
                                                        "same device user, same timestamp")})
            seen.add(key)
            continue
        seen.add(key)
        e = resolver.employee(x.device_user_id, x.punch_date)
        site = site_of(e) if e else b.site
        bd = x.punch_date
        if e is not None:
            bd, has_shift = _business_date(e, x)
            if not has_shift:
                no_shift[e.code] += 1
            if e.separated_on and bd > e.separated_on:
                separated.append({"label": f"{e.name_en} on {bd:%d %b %Y}",
                                  "detail": f"separated {e.separated_on:%d %b %Y}"})
        else:
            unmapped[x.device_user_id] += 1
        if periods.is_locked(site, bd):
            locked[(site.name, month_start(bd))] += 1
        if b.stated_from and b.stated_to and not b.stated_from <= x.punch_date <= b.stated_to:
            outside.append({"label": f"{x.device_user_id} on {x.punch_date:%d %b %Y}",
                            "detail": f"outside {b.stated_from:%d %b} to {b.stated_to:%d %b %Y}"})
        if x.punch_time.hour < 4 or (x.punch_time.hour, x.punch_time.minute) > (23, 30):
            if not (e and _night(e, bd)):
                drift.append({"label": f"{x.device_user_id} at {x.punch_time:%H:%M} on {x.punch_date:%d %b %Y}",
                              "detail": "far outside any assigned shift"})
    group("locked", "BLOCKS", "Punches for a locked period",
          [{"label": f"{m:%B %Y} · {site}", "detail": f"{n} punches"} for (site, m), n in sorted(locked.items())])
    group("parseErrors", "WARNS", "Rows that could not be read",
          [{"label": f"row {e['row']}", "detail": e["message"]} for e in result.errors])
    group("outsideRange", "WARNS", "Punches outside the stated date range", outside)
    group("separated", "WARNS", "Punches after an employee's separation", separated)
    group("drift", "WARNS", "Punches far outside any assigned shift", drift)
    group("duplicates", "INFO", "Duplicate punches", dupes)
    group("unmapped", "INFO", "Unmapped device IDs",
          [{"label": f"Device ID {k}", "detail": f"{n} punches stored, awaiting a mapping"} for k, n in
           sorted(unmapped.items())])
    group("noShift", "INFO", "Employees without a shift on some days",
          [{"label": k, "detail": f"{n} punches"} for k, n in sorted(no_shift.items())])
    if result.discarded:
        group("discarded", "INFO", "Middle punches of the day",
              [{"label": f"{x.device_user_id} at {x.punch_time:%H:%M} on {x.punch_date:%d %b %Y}", "detail": f"row {x.row}"}
               for x in result.punches if x.discarded])
    if result.date_range:
        lo, hi = result.date_range
        overlap = (ImportBatch.objects.filter(company=company, profile__code=profile.code, status="PROCESSED",
                                              parsed_from__lte=hi, parsed_to__gte=lo).exclude(pk=b.pk))
        group("overlap", "INFO", "This range was already imported",
              [{"label": o.file_name, "detail": f"{o.reference}, {o.parsed_from:%d %b} to {o.parsed_to:%d %b %Y}"}
               for o in overlap])
    order = {"BLOCKS": 0, "WARNS": 1, "INFO": 2}
    groups.sort(key=lambda g: order[g["severity"]])
    blocks = [g["id"] for g in groups if g["severity"] == "BLOCKS"]
    warns = [g["id"] for g in groups if g["severity"] == "WARNS"]
    return {"groups": groups, "blocks": blocks, "warns": warns, "canProcess": not blocks,
            "checkedAt": timezone.now().isoformat()}


def _night(employee, d):
    windows = assignments_by_employee([employee], d - timedelta(days=1), d).get(employee.pk)
    for day in (d, d - timedelta(days=1)):
        s = shift_on(windows, day)
        if s is not None and s.end_min > 1439:
            return True
    return False


def validate(company, b, *, user=None):
    """§7.3: the findings as presented are stored with the batch."""
    if b.status not in ("PARSED", "VALIDATED"):
        raise IntakeRefused({"batch": [f"Parse {b.reference} first."]}, status=409)
    result = _parse(b, b.profile)
    report = findings(company, b, result)
    b.validation_json = report
    b.status = "VALIDATED"
    b.save(update_fields=["validation_json", "status", "updated_at"])
    audit(company, "BATCH_VALIDATED", user, batch=b, after={"blocks": report["blocks"], "warns": report["warns"]})
    return b, report


# ---------------------------------------------------------------- process


def _register_write(company, punch, employee, user, periods=None):
    """Write the register's punch for an attributed intake punch. The lock is
    checked here too: validation is the user's path, this is the floor."""
    bd, _ = _business_date(employee, punch)
    site = site_of(employee)
    period = ensure_period(company, site, month_start(bd))
    if period.status == PeriodStatusChoices.LOCKED:
        raise IntakeRefused({"period": [f"{bd:%B %Y} is locked at {site.name}: punch dated {bd:%d %b %Y}."]},
                            status=422)
    return Punch.objects.create(company=company, employee=employee, site=site, punched_at=punch.punched_at,
                                business_date=bd, direction=punch.direction, source=PunchSourceChoices.IMPORT,
                                device_id="INTAKE", device_punch_id=str(punch.uid),
                                raw_payload={"batch": punch.batch.reference, "row": punch.source_row,
                                             "device": punch.device_label, "deviceUserId": punch.device_user_id,
                                             "raw": punch.raw_row},
                                ingested_by=_who(user))


def process(company, b, *, override_warnings=False, user=None):
    """§7.4. One transaction: the live check again (the stored one is
    advisory), then every punch stored -- attributed, held as an orphan, or
    skipped with its reason. Nothing is discarded."""
    if b.status != "VALIDATED":
        raise IntakeRefused({"batch": [f"{b.reference} is {b.status.lower()}: validate it before processing."]},
                            status=409)
    result = _parse(b, b.profile)
    report = findings(company, b, result)
    if report["blocks"]:
        raise IntakeRefused({"batch": ["A finding blocks this import: "
                                       + "; ".join(g["title"] for g in report["groups"] if g["severity"] == "BLOCKS")
                                       + "."]}, status=422, detail=report)
    if report["warns"] and not override_warnings:
        raise IntakeRefused({"batch": ["This import has warnings. Processing over them needs the override "
                                       "permission and a deliberate choice."]}, status=422,
                            detail={**report, "needsOverride": True})
    profile = b.profile
    resolver = Resolver(company, profile)
    imported = skipped = orphaned = 0
    first_orphans = defaultdict(int)
    with transaction.atomic():
        b = ImportBatch.objects.select_for_update().get(pk=b.pk)
        if b.status != "VALIDATED":
            raise IntakeRefused({"batch": [f"{b.reference} is {b.status.lower()}."]}, status=409)
        seen = set()
        for x in result.punches:
            common = dict(company=company, batch=b, profile=profile, device_label=profile.device_label,
                          device_user_id=x.device_user_id, terminal=x.terminal[:120], punched_at=x.punched_at,
                          punch_date=x.punch_date, punch_time=x.punch_time, source_timezone=profile.timezone,
                          direction=x.direction, direction_source=x.direction_source, source_row=x.row,
                          raw_row=x.raw_row)
            key = (x.device_user_id, x.punched_at)
            if x.discarded:
                IntakePunch.objects.create(**common, state="SKIPPED",
                                           skip_reason="A middle punch of the day: first and last are kept.")
                skipped += 1
                continue
            twin = key in seen or IntakePunch.objects.filter(company=company, device_label=profile.device_label,
                                                             device_user_id=x.device_user_id, punched_at=x.punched_at,
                                                             state__in=("ACTIVE", "ORPHAN")).exists()
            if twin:
                IntakePunch.objects.create(**common, state="SKIPPED",
                                           skip_reason="Duplicate: same device user, same timestamp.")
                skipped += 1
                continue
            seen.add(key)
            e = resolver.employee(x.device_user_id, x.punch_date)
            if e is None:
                IntakePunch.objects.create(**common, state="ORPHAN")
                orphaned += 1
                first_orphans[x.device_user_id] += 1
                continue
            p = IntakePunch.objects.create(**common, employee=e, state="ACTIVE")
            p.register_punch = _register_write(company, p, e, user)
            p.save(update_fields=["register_punch", "updated_at"])
            imported += 1
        b.punches_imported, b.punches_skipped, b.punches_orphaned = imported, skipped, orphaned
        b.validation_json = report
        b.processed_over = ({"warnings": report["warns"], "by": _name(user), "at": timezone.now().isoformat()}
                            if report["warns"] else None)
        b.status, b.processed_at, b.processed_by_name = "PROCESSED", timezone.now(), _name(user)
        b.save()
        audit(company, "BATCH_PROCESSED", user, batch=b,
              after={"imported": imported, "skipped": skipped, "orphaned": orphaned,
                     "overrode": report["warns"] or None})
        event(company, "AttendanceBatchProcessed", batch=b.reference, imported=imported, skipped=skipped,
              orphaned=orphaned, range=[b.parsed_from.isoformat(), b.parsed_to.isoformat()] if b.parsed_from else None)
        if orphaned:
            event(company, "OrphanPunchesDetected", actor=user, batch=b.reference, deviceIds=dict(first_orphans),
                  message=f"{b.reference}: {orphaned} punches for {len(first_orphans)} unmapped device IDs")
    return b


# ---------------------------------------------------------------- reverse


def reverse_impact(company, b):
    """What a reversal touches: the days that lose punches, the register's
    adjustments on those days (they stay), and any locked month (refused)."""
    punches = list(b.punches.filter(state__in=("ACTIVE", "ORPHAN")).select_related("register_punch", "employee"))
    days, locked = set(), set()
    periods = Periods(company)
    for p in punches:
        if p.register_punch_id:
            rp = p.register_punch
            days.add((p.employee_id, rp.business_date))
            if periods.is_locked(rp.site, rp.business_date):
                locked.add(rp.business_date.replace(day=1))
        elif periods.is_locked(b.site, p.punch_date):
            locked.add(p.punch_date.replace(day=1))
    adjustments = []
    if days:
        emps = {e for e, _ in days}
        for a in Adjustment.objects.filter(employee_id__in=emps, is_live=True, removed=False).select_related(
                "employee"):
            if (a.employee_id, a.business_date) in days:
                adjustments.append({"code": a.employee.code, "nameEn": a.employee.name_en,
                                    "date": a.business_date.isoformat(), "reason": a.reason})
    return {"punches": len(punches), "days": len(days), "employees": len({e for e, _ in days}),
            "adjustments": sorted(adjustments, key=lambda r: (r["date"], r["code"])),
            "lockedPeriods": sorted(m.strftime("%B %Y") for m in locked)}


def reverse(company, b, *, reason, user=None):
    """§7.5. Every punch of the batch becomes REVERSED and its register punch
    is voided; nothing is deleted. Refused while any of its days is in a
    locked month -- that would silently change a payroll input."""
    reason = _reason(reason, "the reason for reversing")
    if b.status != "PROCESSED":
        raise IntakeRefused({"batch": [f"{b.reference} is {b.status.lower()}; only a processed import is "
                                       "reversed."]}, status=409)
    impact = reverse_impact(company, b)
    if impact["lockedPeriods"]:
        raise IntakeRefused({"batch": [f"{', '.join(impact['lockedPeriods'])} is locked. Unlock it first — the "
                                       "unlock is logged."]}, status=409, detail=impact)
    with transaction.atomic():
        b = ImportBatch.objects.select_for_update().get(pk=b.pk)
        for p in b.punches.filter(state__in=("ACTIVE", "ORPHAN")).select_related("register_punch"):
            if p.register_punch_id and not PunchVoid.objects.filter(punch_id=p.register_punch_id).exists():
                PunchVoid.objects.create(company=company, punch_id=p.register_punch_id, reason=reason,
                                         source_ref=b.reference, actor=_who(user), actor_name=_name(user))
        b.punches.filter(state__in=("ACTIVE", "ORPHAN")).update(state="REVERSED")
        b.status, b.reversed_at, b.reversed_by, b.reversed_by_name = "REVERSED", timezone.now(), _who(user), _name(user)
        b.reverse_reason = reason
        b.save()
        audit(company, "BATCH_REVERSED", user, batch=b, reason=reason, after=impact)
        event(company, "AttendanceBatchReversed", actor=user, batch=b.reference, days=impact["days"],
              message=f"{b.reference} reversed: {impact['punches']} punches, {impact['days']} days recompute")
    return b, impact


def history(company, *, site=None):
    qs = ImportBatch.objects.filter(company=company).select_related("site", "profile")
    if site is not None:
        qs = qs.filter(site=site)
    return [batch_out(b) for b in qs[:300]]


def raw_bytes(b):
    return io.BytesIO(_raw(b))


# ================================================================== mapping


def map_out(m):
    return {"uid": str(m.uid), "deviceLabel": m.device_label, "deviceUserId": m.device_user_id,
            "employee": {"code": m.employee.code, "nameEn": m.employee.name_en},
            "effectiveFrom": m.effective_from.isoformat(),
            "effectiveTo": m.effective_to.isoformat() if m.effective_to else None, "relinked": m.relinked_count,
            "createdBy": m.created_by_name or None, "createdAt": m.created_at.isoformat()}


def suggest(device_user_id, employees):
    """§7.1: device user 0217 suggests EMP-0217. A suggestion only -- a
    coincidental last-four match would attribute one person's attendance to
    another."""
    want = "".join(ch for ch in str(device_user_id) if ch.isdigit())
    if not want:
        return None
    want = want[-4:].rjust(4, "0")
    hits = [e for e in employees if "".join(ch for ch in e.code if ch.isdigit())[-4:].rjust(4, "0") == want]
    return hits[0] if len(hits) == 1 else None


def unmapped(company):
    """The orphans, by device and device user ID."""
    groups = {}
    for p in (IntakePunch.objects.filter(company=company, state="ORPHAN").select_related("batch")
              .order_by("punch_date", "punch_time")):
        g = groups.setdefault((p.device_label, p.device_user_id), {
            "deviceLabel": p.device_label, "deviceUserId": p.device_user_id, "punches": 0,
            "firstSeen": p.punch_date.isoformat(), "lastSeen": p.punch_date.isoformat(), "batches": []})
        g["punches"] += 1
        g["lastSeen"] = p.punch_date.isoformat()
        if p.batch.reference not in g["batches"]:
            g["batches"].append(p.batch.reference)
    employees = list(Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT")))
    out = []
    for g in groups.values():
        s = suggest(g["deviceUserId"], employees)
        out.append({**g, "suggestion": {"code": s.code, "nameEn": s.name_en} if s else None})
    return sorted(out, key=lambda r: (r["deviceLabel"], r["deviceUserId"]))


def create_mapping(company, *, device_label, device_user_id, employee, effective_from, user=None):
    """§7.6. Re-links every orphan of that device and ID from the date on,
    and answers with how many: "mapping created" does not tell the operator
    whether the missing three weeks were recovered. An orphan dated in a
    locked month stays held until the month is unlocked."""
    device_label, device_user_id = str(device_label or "").strip(), str(device_user_id or "").strip()
    if not device_label or not device_user_id:
        raise IntakeRefused({"deviceUserId": ["A mapping needs the device and the device user ID."]}, status=400)
    if DeviceUserMap.objects.filter(company=company, device_label=device_label, device_user_id=device_user_id,
                                    effective_to__isnull=True).exists():
        raise IntakeRefused({"deviceUserId": [f"Device ID {device_user_id} on {device_label} is already mapped. "
                                              "Close that mapping first (a reissued slot)."]}, status=409)
    if DeviceUserMap.objects.filter(company=company, device_label=device_label, device_user_id=device_user_id,
                                    effective_to__gte=effective_from).exists():
        raise IntakeRefused({"effectiveFrom": ["An earlier mapping of this ID runs past that date."]}, status=409)
    periods = Periods(company)
    with transaction.atomic():
        m = DeviceUserMap.objects.create(company=company, device_label=device_label, device_user_id=device_user_id,
                                         employee=employee, effective_from=effective_from, created_by=_who(user),
                                         created_by_name=_name(user))
        relinked, held, first = 0, 0, None
        now = timezone.now()
        site = site_of(employee)
        for p in (IntakePunch.objects.filter(company=company, device_label=device_label,
                                             device_user_id=device_user_id, state="ORPHAN",
                                             punch_date__gte=effective_from)
                  .select_related("batch").order_by("punch_date", "punch_time")):
            if periods.is_locked(site, p.punch_date):
                held += 1
                continue
            p.employee, p.state, p.relinked_at = employee, "ACTIVE", now
            p.save(update_fields=["employee", "state", "relinked_at", "updated_at"])
            p.register_punch = _register_write(company, p, employee, user)
            p.save(update_fields=["register_punch", "updated_at"])
            relinked += 1
            first = first or p.punch_date
        m.relinked_count = relinked
        m.save(update_fields=["relinked_count", "updated_at"])
        audit(company, "MAPPING_CREATED", user, site=site,
              after={"device": device_label, "deviceUserId": device_user_id, "employee": employee.code,
                     "from": effective_from.isoformat(), "relinked": relinked, "held": held})
        event(company, "DeviceMappingCreated", device=device_label, deviceUserId=device_user_id,
              employee=employee.code, relinked=relinked, fromDate=first.isoformat() if first else None)
    message = (f"{relinked} punches attached to {employee.name_en}" + (f", from {first:%d %B}." if first else ".")
               if relinked else f"Mapped to {employee.name_en}. No held punches to attach.")
    if held:
        message += f" {held} more are dated in a locked month and stay held until it is unlocked."
    return m, {"relinked": relinked, "held": held, "message": message}


def close_mapping(company, m, *, effective_to, user=None):
    """A reissued device slot: the old mapping closes; its punches stay with
    the old employee."""
    if m.effective_to is not None:
        raise IntakeRefused({"mapping": ["This mapping is already closed."]}, status=409)
    if effective_to < m.effective_from:
        raise IntakeRefused({"effectiveTo": ["A mapping closes on or after it opened."]}, status=400)
    m.effective_to, m.closed_by_name = effective_to, _name(user)
    m.save(update_fields=["effective_to", "closed_by_name", "updated_at"])
    audit(company, "MAPPING_CLOSED", user, after={"device": m.device_label, "deviceUserId": m.device_user_id,
                                                  "to": effective_to.isoformat()})
    return m


# ================================================================== periods

STAGES = ("OPEN", "PROCESSING", "REVIEW")


def period_row(company, site, month, *, exceptions=True):
    p = ensure_period(company, site, month)
    out = register.period_out(p)
    state = "LOCKED" if p.status == PeriodStatusChoices.LOCKED else p.stage
    count = None
    gates = None
    if exceptions and state != "LOCKED":
        summ = register.close_summary(company, site, month)
        count = next((g["count"] for g in summ.get("gates", []) if g["key"] == "high"), 0)
        gates = [{"key": g["key"], "label": g["label"], "count": g["count"], "blocks": g["blocks"]}
                 for g in summ.get("gates", []) if g["count"]]
    batches = ImportBatch.objects.filter(company=company, site=site, status="PROCESSED",
                                         parsed_from__lte=month_end(month), parsed_to__gte=month).count()
    return {**out, "label": f"{month:%B %Y}", "state": state, "exceptions": count, "gates": gates,
            "imports": batches, "lockedOn": p.locked_at.date().isoformat() if p.locked_at else None}


def periods(company, site, *, months=6):
    today = clock.today()
    cur = month_start(today)
    known = set(AttendancePeriod.objects.filter(company=company, site=site).values_list("period_month", flat=True))
    wanted = {cur}
    m = cur
    for _ in range(months - 1):
        m = month_start(m - timedelta(days=1))
        if m in known:
            wanted.add(m)
    wanted |= {k for k in known if k >= month_start(today - timedelta(days=370))}
    return [period_row(company, site, m) for m in sorted(wanted, reverse=True)]


def advance(company, site, month, *, acknowledge_reason=None, user=None):
    """§6.1. OPEN -> PROCESSING -> REVIEW; from REVIEW, the register's lock --
    whose gates still apply, with unresolved exceptions passable only by an
    acknowledged reason."""
    p = ensure_period(company, site, month)
    if p.status == PeriodStatusChoices.LOCKED:
        raise IntakeRefused({"period": [f"{month:%B %Y} is already locked."]}, status=409)
    if p.stage in ("OPEN", "PROCESSING"):
        nxt = "PROCESSING" if p.stage == "OPEN" else "REVIEW"
        before = p.stage
        p.stage = nxt
        p.save(update_fields=["stage", "updated_at"])
        audit(company, "PERIOD_ADVANCED", user, site=site, month=month, before={"stage": before},
              after={"stage": nxt})
        return period_row(company, site, month)
    register.lock(company, site, month, user=user, acknowledge_reason=acknowledge_reason)
    audit(company, "PERIOD_LOCKED", user, site=site, month=month, reason=acknowledge_reason or "")
    event(company, "AttendancePeriodLocked", site=site.name, month=month.strftime("%Y-%m"))
    return period_row(company, site, month, exceptions=False)


def unlock(company, site, month, *, reason, confirmed_invalidates_payroll=False, user=None):
    """§6.2: a reason; then, if payroll consumed the month, a confirmation --
    and the invalidated run is stored on the period."""
    p = register.reopen(company, site, month, reason=reason, user=user,
                        confirmed_invalidates_payroll=confirmed_invalidates_payroll)
    audit(company, "PERIOD_UNLOCKED", user, site=site, month=month, reason=reason,
          after={"payrollInvalidated": p.payroll_invalidated_ref or None})
    event(company, "AttendancePeriodUnlocked", actor=user, site=site.name, month=month.strftime("%Y-%m"),
          invalidatedRun=p.payroll_invalidated_ref or None,
          message=f"{month:%B %Y} at {site.name} unlocked" + (
              f"; payroll run {p.payroll_invalidated_ref} is invalid" if p.payroll_invalidated_ref else ""))
    return period_row(company, site, month)


def audit_out(a):
    return {"action": a.action, "label": a.get_action_display(), "by": a.actor_name or None,
            "at": a.created_at.isoformat(), "reason": a.reason or None, "batch": a.batch.reference if a.batch_id else None,
            "month": a.period_month.strftime("%Y-%m") if a.period_month else None, "after": a.after_json}


__all__ = ["IntakeRefused", "date"]
