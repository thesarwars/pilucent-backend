"""The Recurring Transactions scheduling engine.

Pure date math, no DB writes: given a ``RecurringTemplate`` (or anything with the
same schedule attributes) it answers two questions —

* :func:`compute_first_run_date` — the first occurrence on/after ``start_date``
  when a template is first saved.
* :func:`advance_run_date` — the next occurrence strictly after a previous one,
  advancing exactly one interval step.

Both go through :func:`compute_next_date`, which also enforces the end
condition (returns ``None`` once the schedule is exhausted). Month-end clamping
is applied per month and never mutates the underlying day-of-month rule, so a
"31st" rule that yields Feb 28 still yields Mar 31 next (spec section 11.2).

Weekdays follow Python's convention: 0 = Monday … 6 = Sunday.

See ``docs/updated-prompts/Balanzify_Recurring_Transactions_Bill.md`` section 11.
"""

import calendar
import math
from datetime import date, timedelta

from ..choices import (
    RecurringDayModeChoices,
    RecurringEndTypeChoices,
    RecurringFrequencyChoices,
    RecurringOrdinalChoices,
    RecurringTemplateTypeChoices,
)

_ORDINAL_INDEX = {
    RecurringOrdinalChoices.FIRST: 0,
    RecurringOrdinalChoices.SECOND: 1,
    RecurringOrdinalChoices.THIRD: 2,
    RecurringOrdinalChoices.FOURTH: 3,
}


def _days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def _clamp_day(year, month, day):
    """A date in (year, month), with ``day`` clamped to the last valid day."""
    return date(year, month, min(day, _days_in_month(year, month)))


def _add_months(year, month, count):
    """Advance (year, month) by ``count`` months, returning a new (year, month)."""
    index = (year * 12 + (month - 1)) + count
    return index // 12, index % 12 + 1


def _nth_weekday_of_month(year, month, weekday, ordinal):
    """The date of the Nth ``weekday`` in (year, month).

    ``ordinal`` is one of :class:`RecurringOrdinalChoices`; ``LAST`` finds the
    final matching weekday. FIRST–FOURTH always exist in every month.
    """
    if ordinal == RecurringOrdinalChoices.LAST:
        last_day = _days_in_month(year, month)
        last_weekday = date(year, month, last_day).weekday()
        back = (last_weekday - weekday) % 7
        return date(year, month, last_day - back)

    first_weekday = date(year, month, 1).weekday()
    first_match = 1 + (weekday - first_weekday) % 7
    return date(year, month, first_match + 7 * _ORDINAL_INDEX[ordinal])


def is_schedulable(template):
    """True when the template has a timetable (Scheduled/Reminder with a start)."""
    return (
        template.template_type != RecurringTemplateTypeChoices.UNSCHEDULED
        and bool(template.frequency)
        and bool(template.start_date)
    )


def _occurrence_in_month(template, year, month):
    """The occurrence date within a specific month per the template's day rule."""
    if (
        template.day_mode == RecurringDayModeChoices.WEEKDAY
        and template.ordinal
        and template.weekday is not None
    ):
        return _nth_weekday_of_month(year, month, template.weekday, template.ordinal)
    day = template.day_of_month or template.start_date.day
    return _clamp_day(year, month, day)


def _occurrence_in_year(template, year):
    """The occurrence date within a specific year (yearly frequency)."""
    month = template.month_of_year or template.start_date.month
    if (
        template.day_mode == RecurringDayModeChoices.WEEKDAY
        and template.ordinal
        and template.weekday is not None
    ):
        return _nth_weekday_of_month(year, month, template.weekday, template.ordinal)
    day = template.day_of_month or template.start_date.day
    return _clamp_day(year, month, day)


def _first_on_or_after(template, ref):
    """First scheduled occurrence date >= ``ref`` (end condition ignored)."""
    freq = template.frequency
    step = max(1, template.interval_count or 1)
    start = template.start_date
    ref = max(ref, start)  # never produce anything before the start date

    if freq == RecurringFrequencyChoices.DAILY:
        if ref <= start:
            return start
        jumps = math.ceil((ref - start).days / step)
        return start + timedelta(days=jumps * step)

    if freq == RecurringFrequencyChoices.WEEKLY:
        target = template.weekday if template.weekday is not None else start.weekday()
        base = start + timedelta(days=(target - start.weekday()) % 7)
        week = 7 * step
        if ref <= base:
            return base
        jumps = math.ceil((ref - base).days / week)
        return base + timedelta(days=jumps * week)

    if freq == RecurringFrequencyChoices.MONTHLY:
        year, month = start.year, start.month
        while True:
            occurrence = _occurrence_in_month(template, year, month)
            if occurrence >= ref:
                return occurrence
            year, month = _add_months(year, month, step)

    if freq == RecurringFrequencyChoices.YEARLY:
        year = start.year
        while True:
            occurrence = _occurrence_in_year(template, year)
            if occurrence >= ref:
                return occurrence
            year += step

    return None


def _next_after(template, previous_date):
    """The occurrence exactly one interval step after ``previous_date``."""
    freq = template.frequency
    step = max(1, template.interval_count or 1)

    if freq == RecurringFrequencyChoices.DAILY:
        return previous_date + timedelta(days=step)

    if freq == RecurringFrequencyChoices.WEEKLY:
        return previous_date + timedelta(days=7 * step)

    if freq == RecurringFrequencyChoices.MONTHLY:
        year, month = _add_months(previous_date.year, previous_date.month, step)
        return _occurrence_in_month(template, year, month)

    if freq == RecurringFrequencyChoices.YEARLY:
        return _occurrence_in_year(template, previous_date.year + step)

    return None


def _exceeds_end(template, candidate):
    """True when ``candidate`` falls past the template's end condition."""
    if template.end_type == RecurringEndTypeChoices.BY_DATE:
        return bool(template.end_date) and candidate > template.end_date
    if template.end_type == RecurringEndTypeChoices.AFTER_COUNT:
        return bool(template.end_after_occurrences) and (
            (template.occurrences_generated or 0) >= template.end_after_occurrences
        )
    return False


def compute_next_date(template, previous_date=None):
    """The next occurrence for ``template``, or ``None`` if the schedule is done.

    ``previous_date`` is the last occurrence already produced. When ``None`` the
    first occurrence on/after ``start_date`` is returned (a brand-new template).
    """
    if not is_schedulable(template):
        return None

    if previous_date is None:
        candidate = _first_on_or_after(template, template.start_date)
    else:
        candidate = _next_after(template, previous_date)

    if candidate is None or _exceeds_end(template, candidate):
        return None
    return candidate


def compute_first_run_date(template):
    """First Next Date for a freshly-saved template (``None`` if unscheduled)."""
    return compute_next_date(template, previous_date=None)


def advance_run_date(template, previous_date):
    """Next Date after ``previous_date`` (``None`` when the schedule ends)."""
    return compute_next_date(template, previous_date=previous_date)


def next_on_or_after(template, ref):
    """First occurrence on/after ``ref``, or ``None`` once the schedule is done.

    Used when resuming a paused template: the occurrences that fell due while it
    was paused are the ones the pause was meant to skip, so the schedule rolls
    forward to the next one rather than back-filling them.
    """
    if not is_schedulable(template):
        return None
    candidate = _first_on_or_after(template, ref)
    if candidate is None or _exceeds_end(template, candidate):
        return None
    return candidate


def creation_trigger_date(template, occurrence_date):
    """Date a Scheduled bill should actually be created (occurrence − advance)."""
    days = template.create_days_in_advance or 0
    return occurrence_date - timedelta(days=days)


def reminder_date(template, occurrence_date):
    """Date a Reminder should surface (occurrence − remind-days-before)."""
    days = template.remind_days_before or 0
    return occurrence_date - timedelta(days=days)
