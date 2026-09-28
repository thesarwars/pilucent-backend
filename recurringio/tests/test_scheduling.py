"""Unit tests for the recurring scheduling engine (pure date math, no DB)."""

from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from recurringio.choices import (
    RecurringDayModeChoices,
    RecurringEndTypeChoices,
    RecurringFrequencyChoices,
    RecurringOrdinalChoices,
    RecurringTemplateTypeChoices,
)
from recurringio.services import scheduling


def make_template(**overrides):
    """A minimal stand-in exposing the schedule attributes the engine reads."""
    defaults = dict(
        template_type=RecurringTemplateTypeChoices.SCHEDULED,
        frequency=RecurringFrequencyChoices.MONTHLY,
        interval_count=1,
        day_mode=RecurringDayModeChoices.DAY_OF_MONTH,
        day_of_month=None,
        weekday=None,
        ordinal=None,
        month_of_year=None,
        start_date=date(2026, 1, 1),
        end_type=RecurringEndTypeChoices.NONE,
        end_date=None,
        end_after_occurrences=None,
        occurrences_generated=0,
        create_days_in_advance=None,
        remind_days_before=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class DailyTests(SimpleTestCase):
    def test_every_day_first_is_start(self):
        t = make_template(frequency=RecurringFrequencyChoices.DAILY, start_date=date(2026, 3, 10))
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 3, 10))

    def test_every_day_advances_one_day(self):
        t = make_template(frequency=RecurringFrequencyChoices.DAILY, start_date=date(2026, 3, 10))
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 3, 10)), date(2026, 3, 11))

    def test_every_n_days(self):
        t = make_template(
            frequency=RecurringFrequencyChoices.DAILY,
            interval_count=5,
            start_date=date(2026, 3, 1),
        )
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 3, 1)), date(2026, 3, 6))


class WeeklyTests(SimpleTestCase):
    def test_first_lands_on_target_weekday(self):
        # start Wed 2026-03-04; target Monday(0) -> first is Mon 2026-03-09
        t = make_template(
            frequency=RecurringFrequencyChoices.WEEKLY,
            weekday=0,
            start_date=date(2026, 3, 4),
        )
        first = scheduling.compute_first_run_date(t)
        self.assertEqual(first, date(2026, 3, 9))
        self.assertEqual(first.weekday(), 0)

    def test_start_already_on_weekday(self):
        # 2026-03-09 is a Monday
        t = make_template(
            frequency=RecurringFrequencyChoices.WEEKLY,
            weekday=0,
            start_date=date(2026, 3, 9),
        )
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 3, 9))

    def test_every_two_weeks(self):
        t = make_template(
            frequency=RecurringFrequencyChoices.WEEKLY,
            weekday=0,
            interval_count=2,
            start_date=date(2026, 3, 9),
        )
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 3, 9)), date(2026, 3, 23))


class MonthlyDayOfMonthTests(SimpleTestCase):
    def test_first_on_or_after_start(self):
        t = make_template(day_of_month=15, start_date=date(2026, 1, 20))
        # 15th of Jan is before start -> first is Feb 15
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 2, 15))

    def test_month_end_clamp_february(self):
        t = make_template(day_of_month=31, start_date=date(2026, 1, 31))
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 1, 31))
        # 2026 is not a leap year -> Feb 28
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 1, 31)), date(2026, 2, 28))

    def test_clamp_does_not_drift(self):
        # After Feb 28 (clamped from 31), March must return to 31, not 28.
        t = make_template(day_of_month=31, start_date=date(2026, 1, 31))
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 2, 28)), date(2026, 3, 31))

    def test_leap_year_february(self):
        t = make_template(day_of_month=31, start_date=date(2028, 1, 31))
        # 2028 is a leap year -> Feb 29
        self.assertEqual(scheduling.advance_run_date(t, date(2028, 1, 31)), date(2028, 2, 29))

    def test_every_three_months(self):
        t = make_template(day_of_month=15, interval_count=3, start_date=date(2026, 1, 15))
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 1, 15)), date(2026, 4, 15))

    def test_day_of_month_defaults_to_start_day(self):
        t = make_template(day_of_month=None, start_date=date(2026, 1, 7))
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 1, 7)), date(2026, 2, 7))


class MonthlyWeekdayTests(SimpleTestCase):
    def test_first_monday(self):
        t = make_template(
            day_mode=RecurringDayModeChoices.WEEKDAY,
            ordinal=RecurringOrdinalChoices.FIRST,
            weekday=0,  # Monday
            start_date=date(2026, 3, 1),
        )
        # First Monday of March 2026 is the 2nd
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 3, 2))

    def test_last_friday(self):
        t = make_template(
            day_mode=RecurringDayModeChoices.WEEKDAY,
            ordinal=RecurringOrdinalChoices.LAST,
            weekday=4,  # Friday
            start_date=date(2026, 3, 1),
        )
        # Last Friday of March 2026 is the 27th
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 3, 27))

    def test_advance_to_next_month_weekday(self):
        t = make_template(
            day_mode=RecurringDayModeChoices.WEEKDAY,
            ordinal=RecurringOrdinalChoices.FIRST,
            weekday=0,
            start_date=date(2026, 3, 1),
        )
        # First Monday of April 2026 is the 6th
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 3, 2)), date(2026, 4, 6))


class YearlyTests(SimpleTestCase):
    def test_yearly_month_day(self):
        t = make_template(
            frequency=RecurringFrequencyChoices.YEARLY,
            month_of_year=7,
            day_of_month=4,
            start_date=date(2026, 1, 1),
        )
        self.assertEqual(scheduling.compute_first_run_date(t), date(2026, 7, 4))
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 7, 4)), date(2027, 7, 4))

    def test_yearly_feb29_clamps_on_non_leap(self):
        t = make_template(
            frequency=RecurringFrequencyChoices.YEARLY,
            month_of_year=2,
            day_of_month=29,
            start_date=date(2028, 1, 1),
        )
        self.assertEqual(scheduling.compute_first_run_date(t), date(2028, 2, 29))
        # 2029 is not a leap year -> Feb 28
        self.assertEqual(scheduling.advance_run_date(t, date(2028, 2, 29)), date(2029, 2, 28))


class EndConditionTests(SimpleTestCase):
    def test_end_by_date_stops(self):
        t = make_template(
            day_of_month=15,
            start_date=date(2026, 1, 15),
            end_type=RecurringEndTypeChoices.BY_DATE,
            end_date=date(2026, 1, 31),
        )
        # Next after Jan 15 is Feb 15, which is past the end date -> None
        self.assertIsNone(scheduling.advance_run_date(t, date(2026, 1, 15)))

    def test_end_by_date_allows_on_boundary(self):
        t = make_template(
            day_of_month=15,
            start_date=date(2026, 1, 15),
            end_type=RecurringEndTypeChoices.BY_DATE,
            end_date=date(2026, 2, 28),
        )
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 1, 15)), date(2026, 2, 15))

    def test_end_after_count_stops(self):
        t = make_template(
            day_of_month=15,
            start_date=date(2026, 1, 15),
            end_type=RecurringEndTypeChoices.AFTER_COUNT,
            end_after_occurrences=3,
            occurrences_generated=3,
        )
        self.assertIsNone(scheduling.advance_run_date(t, date(2026, 3, 15)))

    def test_end_after_count_not_reached(self):
        t = make_template(
            day_of_month=15,
            start_date=date(2026, 1, 15),
            end_type=RecurringEndTypeChoices.AFTER_COUNT,
            end_after_occurrences=3,
            occurrences_generated=2,
        )
        self.assertEqual(scheduling.advance_run_date(t, date(2026, 2, 15)), date(2026, 3, 15))


class UnscheduledTests(SimpleTestCase):
    def test_unscheduled_has_no_next_date(self):
        t = make_template(template_type=RecurringTemplateTypeChoices.UNSCHEDULED)
        self.assertIsNone(scheduling.compute_first_run_date(t))

    def test_missing_frequency_has_no_next_date(self):
        t = make_template(frequency=None)
        self.assertIsNone(scheduling.compute_first_run_date(t))

    def test_missing_start_date_has_no_next_date(self):
        t = make_template(start_date=None)
        self.assertIsNone(scheduling.compute_first_run_date(t))


class OffsetTests(SimpleTestCase):
    def test_creation_trigger_subtracts_advance(self):
        t = make_template(create_days_in_advance=5)
        self.assertEqual(
            scheduling.creation_trigger_date(t, date(2026, 3, 15)), date(2026, 3, 10)
        )

    def test_reminder_subtracts_remind_days(self):
        t = make_template(remind_days_before=3)
        self.assertEqual(
            scheduling.reminder_date(t, date(2026, 3, 15)), date(2026, 3, 12)
        )

    def test_offsets_default_to_zero(self):
        t = make_template()
        self.assertEqual(
            scheduling.creation_trigger_date(t, date(2026, 3, 15)), date(2026, 3, 15)
        )
        self.assertEqual(
            scheduling.reminder_date(t, date(2026, 3, 15)), date(2026, 3, 15)
        )
