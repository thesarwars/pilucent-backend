"""Attendance end to end (§14.1 golden vectors A4, A6-A12, A14) and the
API: locks, permissions, masking and tenancy."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from common import clock
from employeeio.services.sites import default_site
from employeeio.test_support import (
    ApiMixin,
    FrozenClockMixin,
    give_salary_permissions,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)

from .models import (
    Adjustment,
    AttendanceAudit,
    CompensatoryCredit,
    DaySnapshot,
    ExceptionDecision,
    Punch,
    PunchQuarantine,
)
from .services import ops
from .services.base import AttendanceRefused, CalendarMissing, ensure_period
from .services.window import Window
from .test_support import (
    assign,
    day_shift,
    give_attendance_permissions,
    night_shift,
    publish,
    punch,
    worked_day,
)

FEB = date(2027, 2, 1)  # Monday; the clock is frozen on 2027-03-08
API = "/api/v1/we/attendance"


class Base(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.site = default_site(cls.company)
        cls.shift = day_shift(cls.company)
        cls.emp = make_employee(cls.company, "EMP-0001", "Rahima Begum", doj=date(2025, 1, 1))
        assign(cls.emp, cls.shift)
        publish(cls.company, 2027, days=[(date(2027, 2, 21), "Shaheed Day", "PUBLIC_HOLIDAY")])
        publish(cls.company, 2026)

    def record(self, d, employee=None):
        employee = employee or self.emp
        period = ensure_period(self.company, self.site, d.replace(day=1))
        return Window(self.company, self.site, [employee], d, d, ops.rules_of(period)).record(employee, d)

    def fill_february(self, employee=None):
        """Every working day of February 08:00-17:00: nothing open."""
        employee = employee or self.emp
        d = FEB
        while d.month == 2:
            if d.isoweekday() != 5 and d != date(2027, 2, 21):
                worked_day(employee, d.isoformat())
            d += timedelta(days=1)


class GoldenVectorTests(Base):
    def test_a4_a_night_shift_is_one_business_date(self):
        nightly = make_employee(self.company, "EMP-0002", "Karim", doj=date(2025, 1, 1))
        assign(nightly, night_shift(self.company))
        out = ops.import_punches(self.company, self.site, [
            {"employeeCode": "EMP-0002", "punchedAt": "2027-02-02 22:00", "direction": "IN"},
            {"employeeCode": "EMP-0002", "punchedAt": "2027-02-03 06:00", "direction": "OUT"},
        ])
        self.assertEqual(out["inserted"], 2)
        self.assertEqual(set(Punch.objects.filter(employee=nightly).values_list("business_date", flat=True)),
                         {date(2027, 2, 2)})
        r = self.record(date(2027, 2, 2), nightly)
        self.assertEqual((r.status, r.worked, r.overtime), ("PRESENT", 420, 0))

    def test_a6_a7_an_acknowledged_breach_stays_in_the_compliance_report(self):
        worked_day(self.emp, "2027-02-01", "08:00", "20:00")
        r = self.record(date(2027, 2, 1))
        self.assertEqual((r.worked, r.overtime), (660, 180))
        ops.acknowledge(self.company, self.emp, date(2027, 2, 1), "DAILY_LIMIT_EXCEEDED",
                        reason="Shipment deadline for the buyer")
        report = ops.compliance(self.company, self.site, FEB)
        self.assertEqual(len(report["daily"]), 1)
        self.assertTrue(report["daily"][0]["acknowledged"])
        self.assertEqual(report["daily"][0]["reason"], "Shipment deadline for the buyer")
        self.assertEqual(self.record(date(2027, 2, 1)).worked, 660)  # minutes unchanged

    def test_a8_a_breach_cannot_be_resolved(self):
        worked_day(self.emp, "2027-02-01", "08:00", "20:00")
        with self.assertRaises(AttendanceRefused) as caught:
            ops.resolve(self.company, self.emp, date(2027, 2, 1), "DAILY_LIMIT_EXCEEDED", "ACCEPT",
                        reason="Trying to resolve it away")
        self.assertEqual(caught.exception.status, 422)
        period = ensure_period(self.company, self.site, FEB)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExceptionDecision.objects.create(company=self.company, employee=self.emp, business_date=date(2027, 2, 1),
                                             period=period, kind="DAILY_LIMIT_EXCEEDED", state="RESOLVED")

    def test_a9_festival_holiday_working_credits_two_and_one(self):
        worked_day(self.emp, "2027-02-21")
        self.assertIn("WORKED_FESTIVAL_HOLIDAY", self.record(date(2027, 2, 21)).exceptions)
        self.assertEqual(ops.confirm_holiday_work(self.company, self.site, FEB)["confirmed"], 1)
        credits = {c.kind: c.days for c in CompensatoryCredit.objects.filter(employee=self.emp)}
        self.assertEqual(credits, {"COMPENSATORY": Decimal("2.0"), "SUBSTITUTE": Decimal("1.0")})

    def test_weekly_holiday_working_credits_one(self):
        worked_day(self.emp, "2027-02-05")  # a Friday
        ops.resolve(self.company, self.emp, date(2027, 2, 5), "WORKED_WEEKLY_HOLIDAY", "CONFIRM")
        self.assertEqual([(c.kind, c.days) for c in CompensatoryCredit.objects.filter(employee=self.emp)],
                         [("COMPENSATORY", Decimal("1.0"))])

    def test_a10_importing_the_same_file_twice_adds_nothing(self):
        rows = [{"employeeCode": "EMP-0001", "punchedAt": "2027-02-01 08:00", "direction": "IN"},
                {"employeeCode": "EMP-0001", "punchedAt": "2027-02-01 17:00", "direction": "OUT"}]
        self.assertEqual(ops.import_punches(self.company, self.site, rows)["inserted"], 2)
        again = ops.import_punches(self.company, self.site, rows)
        self.assertEqual((again["inserted"], again["duplicates"]), (0, 2))
        self.assertEqual(Punch.objects.filter(employee=self.emp).count(), 2)

    def test_unplaceable_punches_are_quarantined_not_dropped(self):
        out = ops.import_punches(self.company, self.site, [
            {"employeeCode": "EMP-9999", "punchedAt": "2027-02-01 08:00", "direction": "IN"},
            {"employeeCode": "EMP-0001", "punchedAt": "yesterday", "direction": "IN"},
            {"employeeCode": "EMP-0001", "punchedAt": "2027-03-09 08:00", "direction": "IN"},
        ])
        self.assertEqual(out["inserted"], 0)
        self.assertEqual(sorted(q["reason"] for q in out["quarantined"]),
                         ["FUTURE_DATED", "MALFORMED", "UNKNOWN_EMPLOYEE"])
        self.assertEqual(PunchQuarantine.objects.filter(company=self.company).count(), 3)

    def test_a11_a_week_across_two_months_is_one_breach(self):
        # Mon 2026-09-28 .. Sun 2026-10-04: six days of 620 minutes, 62 hours, across the month end.
        clock.freeze(date(2026, 10, 20))
        for i in (0, 1, 2, 3, 5, 6):  # skip the Friday
            d = date(2026, 9, 28) + timedelta(days=i)
            worked_day(self.emp, d.isoformat(), "07:00", "18:20")  # 680 span - 60 = 620 worked
        oct_report = ops.compliance(self.company, self.site, date(2026, 10, 1))
        sep_report = ops.compliance(self.company, self.site, date(2026, 9, 1))
        for report in (oct_report, sep_report):
            week = [w for w in report["weekly"] if w["weekStart"] == "2026-09-28"]
            self.assertEqual(len(week), 1)
            self.assertEqual(week[0]["worked"], 6 * 620)

    def test_a12_a_year_averaging_57_hours_breaches_the_proviso(self):
        # 52 weeks to Sun 2027-02-28, six 9.5-hour days a week: 57 a week, never above 60.
        last = date(2027, 2, 28)
        first = last - timedelta(days=52 * 7 - 1)
        d = first
        while d <= last:
            if d.isoweekday() != 5:
                worked_day(self.emp, d.isoformat(), "08:00", "18:30")
            d += timedelta(days=1)
        report = ops.compliance(self.company, self.site, FEB)
        self.assertEqual(report["weekly"], [])
        self.assertEqual(len(report["annual"]), 1)
        self.assertEqual((report["annual"][0]["weeks"], report["annual"][0]["average"]), (52, 57 * 60))

    def test_a13_removing_an_adjustment_restores_the_original(self):
        punch(self.emp, "2027-02-01 08:00", "IN")
        before = self.record(date(2027, 2, 1))
        ops.adjust(self.company, self.emp, date(2027, 2, 1), out_time_min=1020,
                   reason="Supervisor confirmed a 17:00 finish")
        self.assertEqual(self.record(date(2027, 2, 1)).status, "PRESENT")
        ops.remove_adjustment(self.company, self.emp, date(2027, 2, 1), reason="Entered against the wrong day")
        after = self.record(date(2027, 2, 1))
        self.assertEqual((after.status, after.worked, after.exceptions, after.adjusted),
                         (before.status, before.worked, before.exceptions, before.adjusted))
        self.assertEqual(Adjustment.objects.filter(employee=self.emp).count(), 2)  # history kept

    def test_a14_no_published_calendar_refuses(self):
        with self.assertRaises(CalendarMissing):
            ops.grid(self.company, self.site, date(2028, 1, 1))


class OperationTests(Base):
    def test_holiday_and_derived_statuses_cannot_be_set(self):
        for status in ("HOLIDAY", "WEEKLY_HOLIDAY", "PRESENT_OT", "EXCEPTION"):
            with self.assertRaises(AttendanceRefused):
                ops.adjust(self.company, self.emp, date(2027, 2, 1), new_status=status,
                           reason="A reason long enough")

    def test_an_adjustment_needs_a_reason(self):
        with self.assertRaises(AttendanceRefused):
            ops.adjust(self.company, self.emp, date(2027, 2, 1), new_status="ABSENT", reason="short")

    def test_a_second_adjustment_supersedes_the_first(self):
        first = ops.adjust(self.company, self.emp, date(2027, 2, 1), new_status="ABSENT", reason="No-show all day")
        second = ops.adjust(self.company, self.emp, date(2027, 2, 1), new_status="ON_LEAVE",
                            reason="Leave application found")
        first.refresh_from_db()
        self.assertEqual((first.is_live, first.superseded_by_id), (False, second.pk))
        self.assertEqual(self.record(date(2027, 2, 1)).status, "ON_LEAVE")

    def test_lock_is_gated_then_writes_snapshots_and_refuses_writes(self):
        with self.assertRaises(AttendanceRefused):
            ops.lock(self.company, self.site, FEB)  # every day is NO_PUNCH_ROSTERED
        self.fill_february()
        ops.lock(self.company, self.site, FEB)
        self.assertEqual(DaySnapshot.objects.filter(employee=self.emp).count(), 28)
        with self.assertRaises(AttendanceRefused) as caught:
            ops.adjust(self.company, self.emp, date(2027, 2, 2), new_status="ABSENT", reason="After the lock")
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(AttendanceRefused):
            ops.reopen(self.company, self.site, FEB, reason="")
        ops.reopen(self.company, self.site, FEB, reason="Payroll found a missing leave application")
        self.assertFalse(DaySnapshot.objects.filter(employee=self.emp, stale=False).exists())
        self.assertTrue(AttendanceAudit.objects.filter(action="PERIOD_REOPENED").exists())

    def test_medium_exceptions_warn_but_do_not_block(self):
        self.fill_february()
        punch(self.emp, "2027-02-03 07:00", "IN")  # an earlier IN on a filled day: overtime, unapproved
        summary = ops.close_summary(self.company, self.site, FEB)
        medium = next(g for g in summary["gates"] if g["key"] == "medium")
        self.assertEqual(medium["count"], 1)
        self.assertTrue(summary["canLock"])

    def test_assignments_never_overlap(self):
        later = day_shift(self.company, code="B", label="Second", start_min=540, end_min=1080)
        with self.assertRaises(AttendanceRefused):
            ops.assign_shift(self.company, later, [self.emp], date(2025, 1, 1))
        ops.assign_shift(self.company, later, [self.emp], date(2027, 3, 1))
        rows = list(self.emp.shift_assignments.order_by("effective_from").values_list("effective_to", flat=True))
        self.assertEqual(rows, [date(2027, 2, 28), None])

    def test_the_calendar_needs_a_weekly_holiday_and_freezes_with_a_lock(self):
        ops.save_calendar(self.company, self.site, 2029, weekly_pattern={}, days=[])
        with self.assertRaises(AttendanceRefused):
            ops.publish_calendar(self.company, self.site, 2029)
        self.fill_february()
        ops.lock(self.company, self.site, FEB)
        with self.assertRaises(AttendanceRefused):
            ops.save_calendar(self.company, self.site, 2027, weekly_pattern={"6": 1}, days=[])


class ApiTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.member = make_user(self.company, "clerk@rahman.test")

    def test_the_grid_is_a_dense_month_per_employee(self):
        worked_day(self.emp, "2027-02-01")
        body = self.client_for(self.admin).get(f"{API}/grid", {"month": "2027-02"}).json()
        self.assertEqual(len(body["days"]), 28)
        row = body["rows"][0]
        self.assertEqual((row["code"], len(row["days"]), row["days"][0]["s"]), ("EMP-0001", 28, "PRESENT"))
        self.assertEqual(body["days"][4]["kind"], "WEEKLY")
        self.assertEqual(body["period"]["status"], "REVIEW")

    def test_a_missing_calendar_is_a_409_not_a_friday(self):
        response = self.client_for(self.admin).get(f"{API}/grid", {"month": "2028-01"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"][0]["path"], "calendar")

    def test_writing_needs_the_permission(self):
        body = {"employeeCode": "EMP-0001", "date": "2027-02-01", "newStatus": "ABSENT", "reason": "No-show all day"}
        self.assertEqual(self.client_for(self.member).post(f"{API}/adjustments", body, format="json").status_code,
                         403)
        give_attendance_permissions(self.member, self.company, "write_attendance")
        response = self.client_for(self.member).post(f"{API}/adjustments", body, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["computed"]["status"], "ABSENT")

    def test_lock_and_reopen_are_separate_permissions(self):
        self.fill_february()
        give_attendance_permissions(self.member, self.company, "lock_attendance")
        client = self.client_for(self.member)
        self.assertEqual(client.post(f"{API}/periods/lock", {"month": "2027-02"}, format="json").status_code, 200)
        response = client.post(f"{API}/periods/reopen", {"month": "2027-02", "reason": "A reason long enough"},
                               format="json")
        self.assertEqual(response.status_code, 403)

    def test_overtime_cost_is_masked_without_the_figures_permission(self):
        give_structure(self.emp, 31200, effective_from=date(2026, 7, 1))
        worked_day(self.emp, "2027-02-01", "08:00", "19:00")  # 600 worked, 120 overtime
        url = f"{API}/day?employeeCode=EMP-0001&date=2027-02-01"
        masked = self.client_for(self.member).get(url).json()
        self.assertEqual((masked["masked"], masked["otRate"], masked["otCost"]), (True, None, None))
        give_salary_permissions(self.member, self.company, "view_salary_figures")
        shown = self.client_for(self.member).get(url).json()
        basic = Decimal(31200) - 9360 - 1872 - 1248  # the Standard 60/50 split
        rate = (basic / 208 * 2).quantize(Decimal("0.01"))
        self.assertEqual(shown["otRate"]["rate"], str(rate))
        self.assertEqual(shown["otCost"], str((rate * 2).quantize(Decimal("0.01"))))

    def test_another_companys_employee_is_not_found(self):
        other = make_company("Other Ltd")
        make_employee(other, "EMP-7777", "Outsider", doj=date(2025, 1, 1))
        response = self.client_for(self.admin).get(f"{API}/day?employeeCode=EMP-7777&date=2027-02-01")
        self.assertEqual(response.status_code, 404)

    def test_acknowledging_through_resolve_is_refused(self):
        worked_day(self.emp, "2027-02-01", "08:00", "20:00")
        client = self.client_for(self.admin)
        body = {"employeeCode": "EMP-0001", "date": "2027-02-01", "kind": "DAILY_LIMIT_EXCEEDED", "action": "ACCEPT",
                "reason": "Trying to resolve it away"}
        self.assertEqual(client.post(f"{API}/exceptions/resolve", body, format="json").status_code, 422)
        body["reason"] = "Shipment deadline for the buyer"
        response = client.post(f"{API}/exceptions/acknowledge", body, format="json")
        self.assertEqual(response.status_code, 200)
        decided = response.json()["exceptions"]
        self.assertEqual([x["decision"]["state"] for x in decided if x["kind"] == "DAILY_LIMIT_EXCEEDED"],
                         ["ACKNOWLEDGED"])


class ProfileShiftTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)

    def patch(self, code, shift):
        return self.client_for(self.admin).patch(f"/api/v1/we/employees/{code}/employment", {"shift": shift},
                                                 format="json")

    def test_a_first_shift_runs_from_the_date_of_joining(self):
        make_employee(self.company, "EMP-0003", "Nasima", doj=date(2027, 1, 10))
        response = self.patch("EMP-0003", str(self.shift.uid))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["shift"]["code"], "A")
        self.assertEqual(response.json()["shift"]["effectiveFrom"], "2027-01-10")

    def test_a_change_runs_from_today_and_is_on_the_timeline(self):
        later = day_shift(self.company, code="B", label="Second", start_min=540, end_min=1080)
        self.assertEqual(self.patch("EMP-0001", str(later.uid)).status_code, 200)
        windows = list(self.emp.shift_assignments.order_by("effective_from")
                       .values_list("shift__code", "effective_from", "effective_to"))
        self.assertEqual(windows, [("A", date(2025, 1, 1), date(2027, 3, 7)), ("B", date(2027, 3, 8), None)])
        entry = self.emp.field_history.get(field="shift")
        self.assertEqual((entry.from_value, entry.to_value, entry.date), ("A", "B", date(2027, 3, 8)))

    def test_a_shift_is_changed_not_removed(self):
        response = self.patch("EMP-0001", None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["path"], "shift")

    def test_a_locked_month_moves_a_first_shift_past_it(self):
        self.fill_february()
        ops.lock(self.company, self.site, FEB)
        late = make_employee(self.company, "EMP-0004", "Late joiner", doj=date(2027, 2, 15))
        self.assertEqual(self.patch("EMP-0004", str(self.shift.uid)).status_code, 200)
        self.assertEqual(late.shift_assignments.get().effective_from, date(2027, 3, 1))
