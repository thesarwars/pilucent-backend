"""The company's fiscal-year anchor, and the year boundary for an as-of date.

`CompanySetting.preffered_first_financial_month` has existed since migration
`companyio.0005` and is writable from the settings screen, but nothing has ever
read it -- the complete reference set before this file was the field
declaration, `__str__`, the admin registration and one serializer. **This is its
first reader.**

Worth stating because it is the opposite of the usual case: the setting is not
missing, it is dead. No model field, no migration and no new UI control is
needed to honour it.

Defaults to January when unset, which is every company that never opened the
settings screen -- on production, 53 of 60 hold NULL, 6 hold the empty string
and exactly 1 holds "JANUARY". So nobody has chosen a non-calendar year and the
default is correct for the whole fleet today. It is still read rather than
assumed, because the field IS user-writable: someone who sets "October" and
then sees a January boundary on their balance sheet would be looking at a
defect we authored, not one we inherited.

Never uses `.get()`. `CompanySetting.company` is a plain ForeignKey with no
`unique=True`, and two separate call sites reach it through `get_or_create`
(`companyio/django_rest/signals/settings.py`, and payroll's preference setup).
Production currently holds exactly one row per company with no duplicates --
measured, 60 for 60 -- but a reader on the balance sheet is the wrong place to
discover that has changed, and `.first()` costs nothing to be safe. Adding the
uniqueness constraint is the right follow-up and is deliberately not part of
this change.
"""

from datetime import date

MONTH_NUMBER = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

DEFAULT_FISCAL_START_MONTH = 1


def fiscal_start_month(company):
    """The month a fiscal year opens for this company, 1-12.

    January unless the company has explicitly chosen otherwise. Anything
    unrecognised -- null, empty string, a value the choices no longer contain --
    also reads as January rather than raising: a settings row cannot be allowed
    to take the balance sheet down.
    """
    if company is None:
        return DEFAULT_FISCAL_START_MONTH

    from companyio.models import CompanySetting

    setting = (
        CompanySetting.objects.filter(company=company)
        .only("preffered_first_financial_month")
        .first()
    )
    if setting is None:
        return DEFAULT_FISCAL_START_MONTH

    raw = (setting.preffered_first_financial_month or "").strip().upper()
    return MONTH_NUMBER.get(raw, DEFAULT_FISCAL_START_MONTH)


def fiscal_year_start(company, as_of):
    """The first day of the fiscal year that `as_of` falls in.

    For a January anchor this is simply 1 January of `as_of`'s own year. For any
    later anchor the fiscal year that contains `as_of` opened in the PREVIOUS
    calendar year whenever `as_of` falls before the anchor month -- an October
    anchor puts 2026-08-13 inside the year that began 2025-10-01.
    """
    if as_of is None:
        return None

    month = fiscal_start_month(company)
    year = as_of.year if as_of.month >= month else as_of.year - 1
    return date(year, month, 1)
