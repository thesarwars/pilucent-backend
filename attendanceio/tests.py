from datetime import time
from types import SimpleNamespace

from django.test import SimpleTestCase

from attendanceio.choices import AttendanceStatusChoices as S
from attendanceio.django_rest.helpers.derivation import derive_attendance


def _day_shift(**overrides):
    base = dict(
        in_time=time(9, 0),
        out_time=time(17, 0),
        regular_hour=8,
        grace_time=15,
        lunch_time=60,
        tiffin_time=0,
        kind="DAY",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class DeriveAttendanceTests(SimpleTestCase):
    """Pure derivation contract — no DB, deterministic."""

    def test_present_on_time_deducts_break(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 0),
            check_out=time(17, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.PRESENT)
        self.assertEqual(d.worked_hours, 7.0)  # 8h gross - 60m lunch
        self.assertEqual(d.late_mins, 0)
        self.assertEqual(d.ot_hours, 0.0)

    def test_late_beyond_grace_refines_status(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 30),
            check_out=time(17, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.LATE_ARRIVAL)
        self.assertEqual(d.late_mins, 15)  # 30m late - 15m grace

    def test_within_grace_stays_present(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 10),
            check_out=time(17, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.PRESENT)
        self.assertEqual(d.late_mins, 0)

    def test_short_day_downgrades_to_half_day(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 0),
            check_out=time(12, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.HALF_DAY)
        self.assertEqual(d.worked_hours, 2.0)

    def test_overtime_beyond_regular_hours(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 0),
            check_out=time(19, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.worked_hours, 9.0)
        self.assertEqual(d.ot_hours, 1.0)

    def test_off_day_clears_times_and_zeros(self):
        d = derive_attendance(
            date=None, status=S.ABSENT, check_in=time(9, 0),
            check_out=time(17, 0), break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.ABSENT)
        self.assertIsNone(d.check_in)
        self.assertIsNone(d.check_out)
        self.assertEqual(d.worked_hours, 0.0)

    def test_present_without_times_autofills_from_shift(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=None, check_out=None,
            break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.check_in, time(9, 0))
        self.assertEqual(d.check_out, time(17, 0))
        self.assertTrue(d.warnings)

    def test_half_day_autofill_uses_half_regular_span(self):
        d = derive_attendance(
            date=None, status=S.HALF_DAY, check_in=None, check_out=None,
            break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.check_in, time(9, 0))
        self.assertEqual(d.check_out, time(13, 0))  # 09:00 + 8/2 hours

    def test_presence_on_holiday_context_flags_needs_review(self):
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(9, 0),
            check_out=time(17, 0), break_mins=None, shift=_day_shift(),
            context_status=S.HOLIDAY,
        )
        self.assertTrue(d.needs_review)

    def test_unmarked_inherits_holiday_context(self):
        d = derive_attendance(
            date=None, status=None, check_in=None, check_out=None,
            break_mins=None, shift=_day_shift(), context_status=S.HOLIDAY,
        )
        self.assertEqual(d.status, S.HOLIDAY)

    def test_unmarked_no_times_is_absent(self):
        d = derive_attendance(
            date=None, status=None, check_in=None, check_out=None,
            break_mins=None, shift=_day_shift(),
        )
        self.assertEqual(d.status, S.ABSENT)

    def test_night_shift_crosses_midnight(self):
        night = _day_shift(
            in_time=time(22, 0), out_time=time(6, 0), kind="NIGHT",
            lunch_time=0, tiffin_time=0,
        )
        d = derive_attendance(
            date=None, status=S.PRESENT, check_in=time(22, 0),
            check_out=time(6, 0), break_mins=None, shift=night,
        )
        self.assertEqual(d.worked_hours, 8.0)
