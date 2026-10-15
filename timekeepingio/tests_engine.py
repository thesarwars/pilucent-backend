"""computeDay (§6.1) on its own: no database, no clock. Golden vectors
A1-A3, A5, A6 and A13 of §14.1 at the level of the pure function."""

from dataclasses import asdict
from datetime import date

from django.test import SimpleTestCase

from .services.engine import (
    HOLIDAY,
    WEEKLY,
    WORKING,
    AdjSpec,
    DayInput,
    Rules,
    ShiftSpec,
    compute_day,
    days_worked_for_accrual,
)

RULES = Rules(rule_set_id=None, version="test", max_daily_min=600, standard_daily_min=480, max_weekly_min=3600,
              annual_average_weekly_min=3360, overtime_multiplier=2, standard_month_hours=208,
              compensatory_weekly=1, compensatory_festival=2, substitute_festival=1)
SHIFT_A = ShiftSpec(1, "A", "General", 480, 1020, 480, 60, 10, 0, True)
DAY, TODAY = date(2027, 2, 1), date(2027, 3, 8)


def day(*punches, kind=WORKING, shift=SHIFT_A, adjustment=None, on=DAY):
    return compute_day(DayInput(day=on, today=TODAY, employed=True, shift=shift, day_kind=kind,
                                punches=list(punches), adjustment=adjustment), RULES)


class ComputeDayTests(SimpleTestCase):
    def test_a1_a_standard_day(self):
        r = day((480, "IN"), (1020, "OUT"))
        self.assertEqual((r.status, r.worked, r.overtime, r.late, r.exceptions), ("PRESENT", 480, 0, 0, []))

    def test_a2_grace_is_inclusive(self):
        self.assertEqual(day((489, "IN"), (1020, "OUT")).late, 0)
        self.assertEqual(day((490, "IN"), (1020, "OUT")).late, 0)

    def test_a3_one_minute_past_grace_is_late(self):
        r = day((491, "IN"), (1020, "OUT"))
        self.assertEqual(r.late, 1)
        self.assertIn("LATE_ARRIVAL", r.exceptions)

    def test_a5_in_without_out_guesses_no_minutes(self):
        r = day((480, "IN"))
        self.assertEqual((r.status, r.worked, r.overtime), ("EXCEPTION", 0, 0))
        self.assertEqual(r.exceptions, ["MISSING_OUT_PUNCH"])

    def test_today_clocked_in_is_in_progress_not_missing(self):
        r = day((480, "IN"), on=TODAY)
        self.assertEqual((r.pending, r.status, r.exceptions, r.in_min), (True, None, [], 480))

    def test_out_without_in_is_a_missing_in_punch(self):
        r = day((1020, "OUT"))
        self.assertEqual((r.status, r.worked, r.exceptions), ("EXCEPTION", 0, ["MISSING_IN_PUNCH"]))

    def test_a6_hours_above_the_limit_are_kept_and_raised(self):
        r = day((480, "IN"), (1200, "OUT"))  # 08:00-20:00, 660 worked
        self.assertEqual((r.worked, r.overtime, r.status), (660, 180, "PRESENT_OT"))
        self.assertIn("DAILY_LIMIT_EXCEEDED", r.exceptions)

    def test_unapproved_overtime_is_still_overtime(self):
        r = day((480, "IN"), (1080, "OUT"))
        self.assertEqual(r.overtime, 60)
        self.assertIn("OT_UNAPPROVED", r.exceptions)

    def test_no_punch_on_a_rostered_day_is_not_absent(self):
        r = day()
        self.assertEqual((r.status, r.exceptions), ("EXCEPTION", ["NO_PUNCH_ROSTERED"]))

    def test_calendar_days(self):
        self.assertEqual(day(kind=WEEKLY).status, "WEEKLY_HOLIDAY")
        self.assertEqual(day(kind=HOLIDAY).status, "HOLIDAY")
        worked = day((480, "IN"), (1020, "OUT"), kind=HOLIDAY)
        self.assertIn("WORKED_FESTIVAL_HOLIDAY", worked.exceptions)
        self.assertIn("WORKED_WEEKLY_HOLIDAY", day((480, "IN"), (1020, "OUT"), kind=WEEKLY).exceptions)

    def test_the_break_is_not_deducted_from_a_short_day(self):
        self.assertEqual(day((480, "IN"), (720, "OUT")).worked, 240)

    def test_future_and_unpunched_today_are_pending(self):
        self.assertTrue(day(on=date(2027, 3, 9)).pending)
        self.assertTrue(day(on=TODAY).pending)

    def test_no_shift_is_flagged_not_guessed(self):
        r = day((480, "IN"), (1020, "OUT"), shift=None)
        self.assertTrue(r.no_shift)
        self.assertIsNone(r.status)

    def test_a_status_adjustment_is_the_day(self):
        r = day(adjustment=AdjSpec("HALF_DAY", None, None, None, None))
        self.assertEqual((r.status, r.worked, r.adjusted), ("HALF_DAY", 240, True))
        absent = day(adjustment=AdjSpec("ABSENT", None, None, None, None))
        self.assertEqual(absent.exceptions, ["ABSENT_NO_LEAVE"])

    def test_a_regularised_out_time_completes_the_day(self):
        r = day((480, "IN"), adjustment=AdjSpec("", None, 1020, None, None))
        self.assertEqual((r.status, r.worked, r.exceptions), ("PRESENT", 480, []))

    def test_a13_without_the_adjustment_the_day_is_the_original(self):
        original = day((480, "IN"))
        self.assertEqual(asdict(day((480, "IN"), adjustment=None)), asdict(original))

    def test_days_worked_keeps_halves_and_follows_the_elections(self):
        recs = [day((480, "IN"), (1020, "OUT")), day(adjustment=AdjSpec("HALF_DAY", None, None, None, None)),
                day(kind=HOLIDAY), day(adjustment=AdjSpec("ON_LEAVE", None, None, None, None)),
                day(adjustment=AdjSpec("LEAVE_WITHOUT_PAY", None, None, None, None))]
        self.assertEqual(days_worked_for_accrual(recs, {}), 1.5)
        self.assertEqual(days_worked_for_accrual(recs, {"festival": True, "paidLeave": True}), 3.5)
