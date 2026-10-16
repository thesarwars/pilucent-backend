"""Attendance intake (backend spec §12.1 golden vectors A1-A16, §12.2
properties) and the API: permissions, tenancy, the register feed.

The clock is frozen on 2027-03-08."""

import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from employeeio.services.sites import default_site
from employeeio.test_support import (
    ApiMixin,
    FrozenClockMixin,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)
from timekeepingio.models import AttendancePeriod, Adjustment, Punch, PunchVoid
from timekeepingio.services import ops as register
from timekeepingio.services.base import ensure_period
from timekeepingio.test_support import assign, day_shift, publish

from .models import DeviceProfile, DeviceUserMap, ImportBatch, IntakePunch
from .services import ops
from .services import parse as P

TODAY = date(2027, 3, 8)
API = "/api/v1/we/attendance-intake"
MEDIA = tempfile.mkdtemp(prefix="intake-test-")

GATE = [{"source": "UserID", "target": "deviceUserId"}, {"source": "Date", "target": "date"},
        {"source": "Time", "target": "time"}, {"source": "State", "target": "direction"},
        {"source": "Terminal", "target": "terminal"}]


def csv_file(text, name="gate.csv", encoding="utf-8"):
    return SimpleUploadedFile(name, text.encode(encoding), content_type="text/csv")


def give(user, company, *codenames, app="intakeio"):
    from adminio.models import CompanyRole
    from companyio.models import CompanyUser

    role, _ = CompanyRole.objects.get_or_create(company=company, name=f"Intake {app} " + "-".join(codenames))
    role.permission.add(*Permission.objects.filter(content_type__app_label=app, codename__in=codenames))
    CompanyUser.objects.get(user=user, company=company).roles.add(role)


# ------------------------------------------------------------- parse, pure


class ParseTests(TestCase):
    def profile(self, **kw):
        return P.Profile(column_map=GATE, **kw)

    def run_(self, text, encoding="utf-8", **kw):
        return P.parse_file(text.encode(encoding), self.profile(**kw))

    def test_a1_dd_mm_yyyy_is_day_first(self):
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,03/04/2027,07:58:12,IN,Gate\n")
        self.assertEqual(r.punches[0].punch_date, date(2027, 4, 3))
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,03/04/2027,07:58:12,IN,Gate\n", date_format="MM/DD/YYYY")
        self.assertEqual(r.punches[0].punch_date, date(2027, 3, 4))

    def test_a2_two_digit_year_uses_the_profile_century(self):
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,03-04-27,07:58:12,IN,Gate\n", date_format="DD-MM-YY")
        self.assertEqual(r.punches[0].punch_date, date(2027, 4, 3))
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,03-04-27,07:58:12,IN,Gate\n", date_format="DD-MM-YY",
                      century_base=1900)
        self.assertEqual(r.punches[0].punch_date.year, 1927)

    def test_a3_windows_1252_decodes_not_mangles(self):
        # Windows-1252 has no Bengali; what an old terminal does put in it --
        # curly quotes, dashes, accented Latin -- must come through intact.
        text = "UserID,Date,Time,State,Terminal\n0142,03/04/2027,07:58:12,IN,Café – Gate “B”\n"
        r = P.parse_file(text.encode("cp1252"), self.profile(encoding="Windows-1252"))
        self.assertEqual(r.punches[0].terminal, "Café – Gate “B”")
        with self.assertRaises(P.ParseRefused):  # the same bytes read as UTF-8 are refused, not mangled
            P.parse_file(text.encode("cp1252"), self.profile(encoding="UTF-8"))

    def test_a4_a_quoted_comma_is_one_field(self):
        r = self.run_('UserID,Date,Time,State,Terminal\n0142,03/04/2027,07:58:12,IN,"Gate, East ""B"""\n')
        self.assertEqual(r.punches[0].terminal, 'Gate, East "B"')

    def test_a5_alternate_groups_by_employee_and_day(self):
        text = ("UserID,Date,Time,State,Terminal\n"
                "0001,03/04/2027,08:00:00,,G\n0002,03/04/2027,08:01:00,,G\n"
                "0001,03/04/2027,17:00:00,,G\n0002,03/04/2027,17:02:00,,G\n")
        r = self.run_(text, direction_handling="ALTERNATE")
        by = {(x.device_user_id, x.punch_time.hour): x.direction for x in r.punches}
        self.assertEqual(by, {("0001", 8): "IN", ("0002", 8): "IN", ("0001", 17): "OUT", ("0002", 17): "OUT"})

    def test_a6_first_last_keeps_two_and_reports_two(self):
        text = "UserID,Date,Time,State,Terminal\n" + "".join(
            f"0001,03/04/2027,{t},,G\n" for t in ("08:00:00", "12:00:00", "13:00:00", "17:00:00"))
        r = self.run_(text, direction_handling="FIRST_LAST")
        self.assertEqual(r.discarded, 2)
        self.assertEqual([(x.direction, x.discarded) for x in r.punches],
                         [("IN", False), (None, True), (None, True), ("OUT", False)])

    def test_a7_an_invalid_date_names_its_row_and_quotes_the_value(self):
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,02/04/2027,07:58:12,IN,G\n0142,32/03/2027,07:58:12,IN,G\n")
        self.assertEqual(r.errors, [{"row": 3, "field": "date", "value": "32/03/2027",
                                     "message": 'date "32/03/2027" is not a valid date in DD/MM/YYYY'}])

    def test_a_device_in_utc_lands_on_the_dhaka_day(self):
        r = self.run_("UserID,Date,Time,State,Terminal\n0142,03/04/2027,19:30:00,OUT,G\n", timezone="UTC")
        x = r.punches[0]
        self.assertEqual((x.punch_date, x.punch_time.hour), (date(2027, 4, 4), 1))

    def test_paired_columns_and_xlsx(self):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["EmpCode", "WorkDate", "InTime", "OutTime"])
        ws.append(["EMP-0001", "2027-03-02", "07:58", "17:10"])
        ws.append(["EMP-0002", "2027-03-02", "08:05", ""])
        buf = io.BytesIO()
        wb.save(buf)
        prof = P.Profile(format="XLSX", row_structure="PAIRED_COLUMNS", date_format="YYYY-MM-DD", time_format="HH:mm",
                         direction_handling="PAIRED", employee_matching="EMPLOYEE_CODE",
                         column_map=[{"source": "EmpCode", "target": "employeeCode"},
                                     {"source": "WorkDate", "target": "date"},
                                     {"source": "InTime", "target": "inTime"}, {"source": "OutTime", "target": "outTime"}])
        r = P.parse_file(buf.getvalue(), prof)
        self.assertEqual([(x.device_user_id, x.direction) for x in r.punches],
                         [("EMP-0001", "IN"), ("EMP-0001", "OUT"), ("EMP-0002", "IN")])

    def test_every_punch_reconciles_to_one_source_row(self):
        text = "UserID,Date,Time,State,Terminal\n" + "".join(
            f"{i:04d},0{d}/03/2027,0{h}:00:00,IN,G\n" for i in range(1, 4) for d in (1, 2) for h in (7, 8))
        r = self.run_(text)
        self.assertEqual(sorted(x.row for x in r.punches), list(range(2, 2 + 12)))
        again = self.run_(text)
        self.assertEqual([(x.row, x.punched_at) for x in r.punches], [(x.row, x.punched_at) for x in again.punches])


# --------------------------------------------------------------- the flow


@override_settings(MEDIA_ROOT=MEDIA)
class Base(FrozenClockMixin, TestCase):
    frozen_on = TODAY

    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.site = default_site(cls.company)
        publish(cls.company, 2027)
        cls.shift = day_shift(cls.company)
        cls.rafiq = make_employee(cls.company, "EMP-0142", "Md. Rafiqul Islam", status="ACTIVE", doj=date(2025, 1, 1))
        cls.nasima = make_employee(cls.company, "EMP-0318", "Nasima Akter", status="ACTIVE", doj=date(2025, 1, 1))
        for e in (cls.rafiq, cls.nasima):
            assign(e, cls.shift)
        ops.ensure_profiles(cls.company)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def gate(self):
        return DeviceProfile.objects.get(company=self.company, code="DP-MAIN-GATE", is_active=True)

    def map(self, device_user_id, employee, frm=date(2027, 1, 1)):
        return ops.create_mapping(self.company, device_label="Main gate", device_user_id=device_user_id,
                                  employee=employee, effective_from=frm)

    def run_import(self, text, *, override=True, name="gate.csv", stated=None):
        b = ops.upload(self.company, self.site, csv_file(text, name))
        ops.parse(self.company, b, profile=self.gate(), stated_from=stated[0] if stated else None,
                  stated_to=stated[1] if stated else None)
        ops.validate(self.company, b)
        return ops.process(self.company, b, override_warnings=override)

    def lock(self, month):
        p = ensure_period(self.company, self.site, month)
        AttendancePeriod.objects.filter(pk=p.pk).update(status="LOCKED")


DAY = "UserID,Date,Time,State,Terminal\n0142,02/03/2027,07:58:12,IN,Gate\n0142,02/03/2027,17:12:44,OUT,Gate\n"


class FlowTests(Base):
    def test_a8_an_unmapped_id_is_held_and_nothing_is_discarded(self):
        b = self.run_import(DAY)
        self.assertEqual((b.punches_imported, b.punches_orphaned, b.punches_skipped), (0, 2, 0))
        self.assertEqual(IntakePunch.objects.filter(state="ORPHAN", employee__isnull=True).count(), 2)
        self.assertEqual(Punch.objects.count(), 0)

    def test_a9_a_mapping_relinks_the_orphans_and_says_how_many(self):
        self.run_import(DAY)
        m, out = self.map("0142", self.rafiq)
        self.assertEqual((out["relinked"], m.relinked_count), (2, 2))
        self.assertIn("2 punches attached to Md. Rafiqul Islam, from 02 March.", out["message"])
        self.assertEqual(Punch.objects.filter(employee=self.rafiq, business_date=date(2027, 3, 2)).count(), 2)
        day = register.day_detail(self.company, self.rafiq, date(2027, 3, 2), figures=False)
        self.assertEqual(len(day["punches"]), 2)

    def test_mapped_punches_reach_the_register_on_their_business_date(self):
        self.map("0142", self.rafiq)
        b = self.run_import(DAY)
        self.assertEqual(b.punches_imported, 2)
        p = IntakePunch.objects.filter(batch=b).first()
        self.assertEqual((p.register_punch.business_date, p.register_punch.source), (date(2027, 3, 2), "IMPORT"))

    def test_a10_a_locked_period_blocks_and_process_is_refused(self):
        self.map("0142", self.rafiq)
        self.lock(date(2027, 3, 1))
        b = ops.upload(self.company, self.site, csv_file(DAY))
        ops.parse(self.company, b, profile=self.gate())
        _, report = ops.validate(self.company, b)
        self.assertEqual(report["blocks"], ["locked"])
        self.assertFalse(report["canProcess"])
        with self.assertRaises(ops.IntakeRefused) as caught:
            ops.process(self.company, b, override_warnings=True)
        self.assertEqual(caught.exception.status, 422)

    def test_a11_the_same_file_twice_is_409(self):
        self.run_import(DAY)
        with self.assertRaises(ops.IntakeRefused) as caught:
            ops.upload(self.company, self.site, csv_file(DAY, "renamed.csv"))
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("already uploaded as IMP-0001", str(caught.exception))

    def test_a12_reversal_voids_and_deletes_nothing(self):
        self.map("0142", self.rafiq)
        b = self.run_import(DAY)
        register.adjust(self.company, self.rafiq, date(2027, 3, 2), in_time_min=480, out_time_min=1020,
                        reason="Gate reader faulty that morning")
        impact = ops.reverse_impact(self.company, b)
        self.assertEqual((impact["days"], len(impact["adjustments"])), (1, 1))
        b, _ = ops.reverse(self.company, b, reason="Wrong profile used for this export")
        self.assertEqual(set(b.punches.values_list("state", flat=True)), {"REVERSED"})
        self.assertEqual((Punch.objects.count(), PunchVoid.objects.count()), (2, 2))
        day = register.day_detail(self.company, self.rafiq, date(2027, 3, 2), figures=False)
        self.assertEqual(day["punches"], [])
        self.assertTrue(Adjustment.objects.filter(employee=self.rafiq, is_live=True).exists())
        # The reversed file can now be uploaded again after its correction.
        ops.upload(self.company, self.site, csv_file(DAY))

    def test_a12b_reversal_is_refused_in_a_locked_month(self):
        self.map("0142", self.rafiq)
        b = self.run_import(DAY)
        self.lock(date(2027, 3, 1))
        with self.assertRaises(ops.IntakeRefused) as caught:
            ops.reverse(self.company, b, reason="Wrong profile used for this export")
        self.assertIn("March 2027 is locked", str(caught.exception))

    def test_a13_a_punch_timestamp_is_never_updated(self):
        self.run_import(DAY)
        p = IntakePunch.objects.first()
        p.punched_at = p.punched_at.replace(hour=5)
        with self.assertRaises(ValidationError):
            p.save()
        with self.assertRaises(ValidationError):
            IntakePunch.objects.filter(pk=p.pk).update(punch_time="09:00")
        with self.assertRaises(ValidationError):
            IntakePunch.objects.all().delete()

    def test_a14_a_mapped_punch_is_never_reattributed(self):
        self.map("0142", self.rafiq)
        self.run_import(DAY)
        p = IntakePunch.objects.filter(state="ACTIVE").first()
        p.employee = self.nasima
        with self.assertRaises(ValidationError):
            p.save()

    def test_a15_unlocking_a_payroll_consumed_period_needs_confirmation_and_keeps_the_run(self):
        p = ensure_period(self.company, self.site, date(2027, 2, 1))
        AttendancePeriod.objects.filter(pk=p.pk).update(status="LOCKED", payroll_run_ref="PR-2027-02",
                                                         payroll_processed_on=date(2027, 3, 3))
        from timekeepingio.services.base import AttendanceRefused

        with self.assertRaises(AttendanceRefused) as caught:  # gate 1: a reason
            ops.unlock(self.company, self.site, date(2027, 2, 1), reason="")
        self.assertIn("reason", caught.exception.errors)
        with self.assertRaises(AttendanceRefused) as caught:  # gate 2: the payroll confirmation
            ops.unlock(self.company, self.site, date(2027, 2, 1), reason="A late correction from the Gazipur gate")
        self.assertTrue(caught.exception.detail["needsConfirmation"])
        self.assertIn("processed on 2027-03-03", str(caught.exception))
        row = ops.unlock(self.company, self.site, date(2027, 2, 1), reason="A late correction from the Gazipur gate",
                         confirmed_invalidates_payroll=True)
        self.assertEqual((row["state"], row["payrollInvalidated"]), ("OPEN", "PR-2027-02"))

    def test_a16_a_reissued_device_id_leaves_old_punches_with_the_old_employee(self):
        m, _ = self.map("0142", self.rafiq)
        self.run_import(DAY)
        ops.close_mapping(self.company, m, effective_to=date(2027, 3, 4))
        self.map("0142", self.nasima, frm=date(2027, 3, 5))
        later = "UserID,Date,Time,State,Terminal\n0142,06/03/2027,08:00:00,IN,Gate\n"
        self.run_import(later)
        self.assertEqual(Punch.objects.filter(employee=self.rafiq).count(), 2)
        self.assertEqual(Punch.objects.filter(employee=self.nasima).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeviceUserMap.objects.create(company=self.company, device_label="Main gate", device_user_id="0142",
                                         employee=self.rafiq, effective_from=date(2027, 3, 6))

    def test_counts_reconcile_and_duplicates_skip(self):
        self.map("0142", self.rafiq)
        text = DAY + "0142,02/03/2027,17:12:44,OUT,Gate\n0999,02/03/2027,08:00:00,IN,Gate\n"
        b = self.run_import(text)
        self.assertEqual((b.punches_imported, b.punches_skipped, b.punches_orphaned), (2, 1, 1))
        self.assertEqual(b.punches_imported + b.punches_skipped + b.punches_orphaned, b.rows_parsed)
        skipped = IntakePunch.objects.get(state="SKIPPED")
        self.assertIn("Duplicate", skipped.skip_reason)

    def test_warnings_need_a_deliberate_override(self):
        self.map("0142", self.rafiq)
        b = ops.upload(self.company, self.site, csv_file(DAY))
        ops.parse(self.company, b, profile=self.gate(), stated_from=date(2027, 3, 3), stated_to=date(2027, 3, 4))
        _, report = ops.validate(self.company, b)
        self.assertEqual(report["warns"], ["outsideRange"])
        with self.assertRaises(ops.IntakeRefused) as caught:
            ops.process(self.company, b)
        self.assertTrue(caught.exception.detail["needsOverride"])
        b = ops.process(self.company, b, override_warnings=True)
        self.assertEqual(b.processed_over["warnings"], ["outsideRange"])

    def test_a_relink_into_a_locked_month_holds_the_punch(self):
        self.run_import(DAY)
        self.lock(date(2027, 3, 1))
        _, out = self.map("0142", self.rafiq)
        self.assertEqual((out["relinked"], out["held"]), (0, 2))
        self.assertIn("stay held", out["message"])

    def test_period_stages_and_lock_acknowledgement(self):
        feb = date(2027, 2, 1)
        self.assertEqual(ops.advance(self.company, self.site, feb)["state"], "PROCESSING")
        self.assertEqual(ops.advance(self.company, self.site, feb)["state"], "REVIEW")
        from timekeepingio.services.base import AttendanceRefused

        # Nobody punched in February: absences are unresolved exceptions.
        with self.assertRaises(AttendanceRefused) as caught:
            ops.advance(self.company, self.site, feb)
        self.assertTrue(caught.exception.detail["needsAcknowledgement"])
        count = caught.exception.detail["count"]
        self.assertGreater(count, 0)
        row = ops.advance(self.company, self.site, feb, acknowledge_reason="Absences confirmed with the line chiefs")
        self.assertEqual((row["state"], row["exceptionsAcknowledged"]), ("LOCKED", count))
        self.assertEqual(row["acknowledgeReason"], "Absences confirmed with the line chiefs")

    def test_profile_edits_make_a_new_version_and_the_old_batch_keeps_its_own(self):
        self.map("0142", self.rafiq)
        b = self.run_import(DAY)
        p2 = ops.save_profile(self.company, {"name": "Main gate (corrected)"}, profile=self.gate())
        self.assertEqual((p2.version, b.profile_version), (2, 1))
        b.refresh_from_db()
        self.assertEqual(b.profile.version, 1)
        refused = None
        try:
            ops.save_profile(self.company, {"rowStructure": "PAIRED_COLUMNS"}, profile=p2)
        except ops.IntakeRefused as exc:
            refused = exc
        self.assertIn("directionHandling", refused.errors)


# ---------------------------------------------------------------------- api


@override_settings(MEDIA_ROOT=MEDIA)
class ApiTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.clerk = make_user(self.company, "clerk@rahman.test")

    def test_the_whole_flow_over_http(self):
        c = self.client_for(self.admin)
        summary = c.get(f"{API}/summary").json()
        gate = next(p for p in summary["profiles"] if p["code"] == "DP-MAIN-GATE")
        up = c.post(f"{API}/batches", {"file": csv_file(DAY)}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        uid = up.json()["uid"]
        parsed = c.post(f"{API}/batches/{uid}/parse", {"profileUid": gate["uid"]}, format="json").json()
        self.assertEqual(parsed["parse"]["punches"], 2)
        self.assertEqual(c.post(f"{API}/batches/{uid}/validate", {}, format="json").json()["findings"]["blocks"], [])
        done = c.post(f"{API}/batches/{uid}/process", {}, format="json").json()
        self.assertEqual(done["punches"]["orphaned"], 2)
        ids = c.get(f"{API}/device-ids").json()
        self.assertEqual(ids["unmapped"][0]["suggestion"]["code"], "EMP-0142")
        made = c.post(f"{API}/device-maps", {"deviceLabel": "Main gate", "deviceUserId": "0142",
                                             "employeeCode": "EMP-0142", "effectiveFrom": "2027-03-01"}, format="json")
        self.assertEqual(made.json()["relinked"], 2)
        raw = c.get(f"{API}/batches/{uid}/raw")
        self.assertEqual(b"".join(raw.streaming_content), DAY.encode())
        periods = c.get(f"{API}/periods").json()["periods"]
        self.assertEqual(periods[0]["month"], "2027-03")

    def test_lock_and_unlock_are_separate_permissions(self):
        give(self.clerk, self.company, "lock_attendance", app="timekeepingio")
        give(self.clerk, self.company, "advance_attendance_period")
        c = self.client_for(self.clerk)
        p = ensure_period(self.company, self.site, date(2027, 2, 1))
        AttendancePeriod.objects.filter(pk=p.pk).update(status="LOCKED")
        r = c.post(f"{API}/periods/2027-02/unlock", {"reason": "A late correction from the gate"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("separate from locking", r.content.decode())

    def test_processing_over_warnings_needs_the_override_permission(self):
        give(self.clerk, self.company, "import_attendance", "process_attendance_import")
        c = self.client_for(self.clerk)
        b = ops.upload(self.company, self.site, csv_file(DAY))
        ops.parse(self.company, b, profile=self.gate(), stated_from=date(2027, 3, 3), stated_to=date(2027, 3, 4))
        ops.validate(self.company, b)
        r = c.post(f"{API}/batches/{b.uid}/process", {"overrideWarnings": True}, format="json")
        self.assertEqual(r.status_code, 403)
        r = c.post(f"{API}/batches/{b.uid}/process", {}, format="json")
        self.assertEqual(r.status_code, 422)

    def test_another_companys_batch_is_not_found(self):
        b = self.run_import(DAY)
        other = make_company("Other Ltd")
        stranger = make_user(other, "boss@other.test")
        make_company_admin(stranger, other)
        self.assertEqual(self.client_for(stranger).get(f"{API}/batches/{b.uid}").status_code, 404)

    def test_the_sample_file_runs(self):
        c = self.client_for(self.admin)
        text = c.get(f"{API}/sample").json()["text"]
        b = ops.upload(self.company, self.site, csv_file(text, "sample.csv"))
        _, result = ops.parse(self.company, b, profile=self.gate())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(ImportBatch.objects.count(), 1)
