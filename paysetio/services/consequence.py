"""Consequence previews (§6.1), computed from the live roster -- never from a
stored estimate (§1.10). An HR officer quotes these figures in a board
meeting; the prototype's `this.org` fixture made every one of them fiction.

Every figure is the sum over real employees and their structures in force,
not an average times a headcount. Where the roster cannot supply an input
(no locked attendance month for overtime hours) the preview says so and
uses the stated assumption, labelled as one.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from common import clock
from common.money import ZERO, money_str, round_to_taka, to_decimal

from ..choices import DAYS_WORKED_FLAGS, DEFAULT_BANDS, ELECTIONS
from .calendar import Calendar, month_bounds
from .resolve import (
    Hypothetical,
    citation_now,
    elections_for,
    festival_under_year,
    gratuity_base,
    month_hours,
    overtime_base,
    round_line,
)

TWELVE = Decimal("12")
ASSUMED_OT_HOURS = 20


def _m(v):
    return money_str(round_to_taka(v))


# ===================================================================== roster


class Roster:
    """Employees in employment on `on`, with the structure in force and the
    overtime hours of the last locked attendance month."""

    def __init__(self, company, site=None, on=None):
        from employeeio.models import Employee, EmployeeSalaryStructure
        from employeeio.services.sites import site_of
        from rulebookio.book import rule_book

        self.company, self.site, self.on = company, site, on or clock.today()
        self.book = rule_book(self.on)
        qs = (Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
              .exclude(separated_on__lt=self.on).exclude(doj__gt=self.on).select_related("site"))
        employees = list(qs)
        if site is not None:
            employees = [e for e in employees if site_of(e).pk == site.pk]
        structures = {s.employee_id: s for s in EmployeeSalaryStructure.objects
                      .filter(employee__in=[e.pk for e in employees]).in_force_on(self.on)
                      .prefetch_related("components")}
        self.rows = [(e, structures[e.pk]) for e in employees if e.pk in structures]
        self.employees = employees
        self.ot_hours, self.ot_month = self._overtime()

    def _overtime(self):
        from timekeepingio.models import AttendancePeriod, DaySnapshot

        periods = AttendancePeriod.objects.filter(company=self.company, status="LOCKED")
        if self.site is not None:
            periods = periods.filter(site=self.site)
        latest = periods.order_by("-period_month").values_list("period_month", flat=True).first()
        if latest is None:
            return {}, None
        minutes = defaultdict(int)
        for emp, ot in (DaySnapshot.objects.filter(company=self.company, period__period_month=latest,
                                                   period__in=periods)
                        .values_list("employee_id", "overtime_minutes")):
            minutes[emp] += ot
        return {k: Decimal(v) / 60 for k, v in minutes.items() if v}, latest

    @property
    def workers(self):
        return [(e, s) for e, s in self.rows if e.classification == "WORKER"]

    def months_served(self, e):
        from employeeio.services.profile import service_parts

        if not e.doj:
            return None
        p = service_parts(e.doj, self.on)
        return p.years * 12 + p.residual_months

    def profile(self):
        """The org panel: every number derived, none stored."""
        rows = self.rows
        n = len(rows) or 1
        gross = sum((s.gross for _, s in rows), ZERO)
        basic = sum((s.basic for _, s in rows), ZERO)
        da = sum((s.component_amount("DA") for _, s in rows), ZERO)
        ot_people = len(self.ot_hours) if self.ot_month else len(self.workers)
        ot_total = sum(self.ot_hours.values(), ZERO)
        return {
            "on": self.on.isoformat(), "headcount": len(self.employees), "withStructure": len(rows),
            "workers": len(self.workers), "otEmployees": ot_people,
            "avgBasic": _m(basic / n), "avgDa": _m(da / n), "avgGross": _m(gross / n),
            "otHours": str(round(ot_total / len(self.ot_hours), 1)) if self.ot_hours else None,
            "otMonth": self.ot_month.strftime("%Y-%m") if self.ot_month else None,
            "subOneYear": sum(1 for e, _ in rows if (self.months_served(e) or 0) < 12),
            "gratuityEligible": len(self.gratuity_people()),
            "missingStructure": len(self.employees) - len(rows),
        }

    def gratuity_people(self):
        from .ops import participation_in_force, scheme_in_force

        scheme = scheme_in_force(self.company, "GRATUITY", self.on)
        if scheme is None or not scheme.applies:
            return []
        min_years = int((scheme.config_json or {}).get("minServiceYears") or 1)
        out = []
        for e, s in self.rows:
            if participation_in_force(e, "GRATUITY", self.on) and (self.months_served(e) or 0) >= min_years * 12:
                out.append((e, s))
        return out


# ================================================================ per key


def _overtime(roster, assumed):
    mult = roster.book.labour.decimal("overtimeMultiplier")

    def cost(v, d, h):
        r = Hypothetical("overtime_base", v, d or {}, h)
        div = month_hours(r, roster.book)
        total, people = ZERO, 0
        source = roster.ot_hours if roster.ot_month else {e.pk: Decimal(assumed) for e, _ in roster.workers}
        for e, s in roster.rows:
            hrs = source.get(e.pk)
            if not hrs:
                continue
            base, _, _ = overtime_base(s, r)
            total += base / div * mult * hrs
            people += 1
        return total, people

    return cost


def preview(company, key, value=None, data=None, *, hours=None, site=None, on=None, params=None):
    """§6.1: the consequence of `value` against what is in force, from the
    roster. Each option is costed, so the screen can show all of them."""
    params = params or {}
    on = on or clock.today()
    roster = Roster(company, site, on)
    current = elections_for(company, site, on)[key]
    meta = ELECTIONS[key]
    out = {"electionKey": key, "citation": current.row.statutory_citation if current.row else citation_now(key),
           "org": roster.profile(), "current": {"value": current.value, "data": current.data if current.answered else None,
                                                "answered": current.answered},
           "proposed": {"value": value, "data": data}, "notes": []}
    fn = {"overtime_base": _ot_preview, "proration_method": _proration_preview, "gratuity_basis": _gratuity_preview,
          "days_worked_basis": _leave_preview, "festival_bonus_policy": _festival_preview,
          "rounding_mode": _rounding_preview, "balancing_component": _balancing_preview}[key]
    fn(out, roster, current, value, data or {}, hours, params)
    out["label"] = meta["label"]
    return out


def _delta(out, cur_figure, new_figure, annual=True):
    if cur_figure is None or new_figure is None:
        out["deltaMonthly"] = None
        out["deltaAnnual"] = None
        return
    d = new_figure - cur_figure
    out["deltaMonthly"] = _m(d)
    out["deltaAnnual"] = _m(d * TWELVE) if annual else None


def _ot_preview(out, roster, current, value, data, hours, params):
    assumed = params.get("assumedHours") or ASSUMED_OT_HOURS
    cost = _overtime(roster, assumed)
    options = []
    for v, label in ELECTIONS["overtime_base"]["options"]:
        if v == value:
            d, h = data, hours
        elif v == current.value:
            d, h = current.data, current.hours
        else:
            d, h = ({"components": ["BASIC", "DA"]} if v == "CUSTOM" else {}), hours
        total, people = cost(v, d, h)
        options.append({"value": v, "label": label, "monthlyCost": _m(total), "affected": people})
    c_total = None
    if current.answered:
        c_total, _ = cost(current.value, current.data, current.hours)
        out["current"]["monthlyCost"] = _m(c_total)
    if value:
        n_total, people = cost(value, data, hours)
        out["proposed"]["monthlyCost"] = _m(n_total)
        out["affectedEmployees"] = people
        _delta(out, c_total, n_total)
    out["options"] = options
    out["standardMonthHours"] = int(month_hours(Hypothetical("overtime_base", value, data, hours), roster.book))
    out["multiplier"] = roster.book.labour.value("overtimeMultiplier")
    if roster.ot_month:
        out["notes"].append(f"Overtime hours are each employee's own, from the locked {roster.ot_month:%B %Y} "
                            "attendance month.")
    else:
        out["notes"].append(f"No attendance month is locked yet, so every worker is assumed to work {assumed} "
                            "overtime hours a month. Lock a month for real figures.")
    if not any(s.component_amount("DA") for _, s in roster.rows):
        out["notes"].append("Nobody is paid a dearness allowance, so basic + DA equals basic here.")


def _example_month(params, on):
    raw = params.get("month")
    if raw:
        y, m = (int(x) for x in str(raw).split("-")[:2])
        return date(y, m, 1)
    # A 31-day month on purpose: in a 30-day month CALENDAR_DAYS and FIXED_30
    # agree, and the screen would imply they always do.
    y, m = on.year, on.month
    while month_bounds(date(y, m, 1))[1].day != 31:
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return date(y, m, 1)


def _proration_preview(out, roster, current, value, data, hours, params):
    from employeeio.services.sites import default_site
    from employeeio.services.statutory import proration_factor

    month = _example_month(params, roster.on)
    first, last = month_bounds(month)
    join_day = int(params.get("joinDay") or 13)
    joined = first.replace(day=max(1, min(join_day, last.day)))
    gross_param = params.get("gross")
    gross = to_decimal(gross_param) if gross_param else (
        sum((s.gross for _, s in roster.rows), ZERO) / len(roster.rows) if roster.rows else Decimal("50000"))
    cal = Calendar(roster.site or default_site(roster.company))
    opts, figures = [], {}
    for v, label in ELECTIONS["proration_method"]["options"]:
        try:
            f = proration_factor(month, v, roster.book, join_date=joined, calendar=cal)
            amt = gross * f
            figures[v] = amt
            opts.append({"value": v, "label": label, "amount": _m(amt), "factor": f"{f:.4f}"})
        except Exception as exc:  # noqa: BLE001 -- a missing calendar is reported, not hidden
            opts.append({"value": v, "label": label, "amount": None, "error": str(getattr(exc, "errors", exc))})
    vals = list(figures.values())
    out["options"] = opts
    out["example"] = {"month": month.strftime("%Y-%m"), "daysInMonth": last.day, "joined": joined.isoformat(),
                      "gross": _m(gross), "payableCalendarDays": (last - joined).days + 1,
                      "workingDaysInMonth": _safe(lambda: cal.working_days(first, last)),
                      "payableWorkingDays": _safe(lambda: cal.working_days(joined, last)),
                      "spread": _m(max(vals) - min(vals)) if vals else None}
    from employeeio.models import Employee

    year_ago = date(roster.on.year - 1, roster.on.month, 1)
    movers = (Employee.objects.filter(company=roster.company, doj__gte=year_ago, doj__lte=roster.on).count()
              + Employee.objects.filter(company=roster.company, separated_on__gte=year_ago,
                                        separated_on__lte=roster.on).count())
    out["affectedEmployees"] = movers
    out["notes"].append(f"{movers} joiners and leavers in the last twelve months were paid a part month.")
    out["current"]["amount"] = _m(figures[current.value]) if current.value in figures else None
    out["proposed"]["amount"] = _m(figures[value]) if value in figures else None
    _delta(out, figures.get(current.value) if current.answered else None, figures.get(value), annual=False)


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def _gratuity_amount(roster, e, s, r, until=None):
    from employeeio.services.profile import service_parts
    from employeeio.services.statutory import gratuity_days, gratuity_years

    until = until or roster.on
    parts = service_parts(e.doj, until)
    years, _ = gratuity_years(parts, roster.book)
    days = gratuity_days(years, roster.book)
    base, _, _ = gratuity_base(s, r)
    return base / roster.book.labour.decimal("dayWageDivisor") * days * years


def _gratuity_preview(out, roster, current, value, data, hours, params):
    from employeeio.services.statutory import gratuity_days

    people = roster.gratuity_people()
    div = roster.book.labour.decimal("dayWageDivisor")
    opts = []
    for v, label in ELECTIONS["gratuity_basis"]["options"]:
        d = data if v == value else (current.data if current.value == v else {"components": ["BASIC", "HRA"]})
        r = Hypothetical("gratuity_basis", v, d)
        exposure = sum((_gratuity_amount(roster, e, s, r) for e, s in people if e.doj), ZERO)
        avg = (sum((gratuity_base(s, r)[0] for _, s in roster.rows), ZERO) / len(roster.rows)) if roster.rows else ZERO
        at = [{"years": y, "days": gratuity_days(y, roster.book), "amount": _m(avg / div * gratuity_days(y, roster.book) * y)}
              for y in (5, 10, 15)]
        opts.append({"value": v, "label": label, "exposure": _m(exposure), "averageBase": _m(avg), "at": at})
    out["options"] = opts
    out["affectedEmployees"] = len(people)
    by = {o["value"]: o for o in opts}
    if current.answered and current.value in by:
        out["current"]["exposure"] = by[current.value]["exposure"]
    if value in by:
        out["proposed"]["exposure"] = by[value]["exposure"]
    cur = to_decimal(by[current.value]["exposure"]) if current.answered and current.value in by else None
    new = to_decimal(by[value]["exposure"]) if value in by else None
    out["deltaMonthly"] = None
    out["deltaExposure"] = _m(new - cur) if cur is not None and new is not None else None
    out["notes"].append(f"Exposure is what {len(people)} gratuity-eligible employees would be owed if they left on "
                        f"{roster.on:%d/%m/%Y}, at their own service and structure.")
    out["notes"].append(f"Days per year step from {roster.book.labour.value('gratuityDaysStandard')} to "
                        f"{roster.book.labour.value('gratuityDaysAfterBreakpoint')} past "
                        f"{roster.book.labour.value('gratuityYearBreakpoint')} years — the rule book's, not an election.")


def _leave_counts(roster):
    from employeeio.services.sites import default_site

    cal = Calendar(roster.site or default_site(roster.company))
    first, last = date(roster.on.year, 1, 1), date(roster.on.year, 12, 31)
    year = DayKindsCount(cal, first, last)
    L = roster.book.labour
    paid_leave = int(L.value("casualLeaveDays"))
    return {"workingDays": year.working, "weeklyHolidays": year.weekly, "festivalHolidays": year.festival,
            "paidLeave": paid_leave, "present": max(0, year.working - paid_leave), "maternity": 0}


class DayKindsCount:
    def __init__(self, cal, first, last):
        from datetime import timedelta

        from timekeepingio.services.base import HOLIDAY, WEEKLY

        self.working = self.weekly = self.festival = 0
        d = first
        kinds = cal._year(first.year)
        while d <= last:
            k, _ = kinds.of(d)
            if k == WEEKLY:
                self.weekly += 1
            elif k == HOLIDAY:
                self.festival += 1
            else:
                self.working += 1
            d += timedelta(days=1)


def _leave_preview(out, roster, current, value, data, hours, params):
    try:
        c = _leave_counts(roster)
    except Exception as exc:  # noqa: BLE001 -- CalendarMissing
        out["error"] = " ".join(getattr(exc, "errors", {}).get("calendar", [str(exc)]))
        out["options"] = []
        return
    ratios = roster.book.labour.value("earnedLeaveRatioByEstablishment")

    def days(flags, est):
        num = c["present"]
        num += c["paidLeave"] if flags.get("paidLeave") else 0
        num += c["festivalHolidays"] if flags.get("festival") else 0
        num += c["weeklyHolidays"] if flags.get("weekly") else 0
        num += c["maternity"] if flags.get("maternity") else 0
        return num, num // int(ratios.get(est or "FACTORY", 18))

    workers = roster.workers

    def total(flags):
        return sum(days(flags, e.establishment)[1] for e, _ in workers)

    cur_flags = current.data if current.answered else None
    new_flags = {f: bool((data or {}).get(f)) for f in DAYS_WORKED_FLAGS}
    new_flags["present"] = True
    rows = []
    for f, label in ELECTIONS["days_worked_basis"]["flags"]:
        if f == "present":
            continue
        on_flags = {**new_flags, f: True}
        off_flags = {**new_flags, f: False}
        rows.append({"flag": f, "label": label, "numeratorDays": c[{"paidLeave": "paidLeave", "festival": "festivalHolidays",
                                                                     "weekly": "weeklyHolidays", "maternity": "maternity"}[f]],
                     "companyLeaveDays": total(on_flags) - total(off_flags)})
    num, per = days(new_flags, "FACTORY")
    out["options"] = rows
    out["calendar"] = c
    out["proposed"].update(numerator=num, leaveDaysPerWorker=per, companyLeaveDays=total(new_flags))
    if cur_flags is not None:
        cn, cp = days(cur_flags, "FACTORY")
        out["current"].update(numerator=cn, leaveDaysPerWorker=cp, companyLeaveDays=total(cur_flags))
        out["deltaLeaveDays"] = total(new_flags) - total(cur_flags)
    out["affectedEmployees"] = len(workers)
    out["deltaMonthly"] = None
    out["notes"].append(f"Counted on the {roster.on.year} published calendar: {c['workingDays']} working days, "
                        f"{c['weeklyHolidays']} weekly and {c['festivalHolidays']} festival holidays; paid leave "
                        f"taken is assumed at the casual-leave entitlement of {c['paidLeave']} days.")
    out["notes"].append("Maternity leave adds nothing on this roster, and is still shown: an inspector asks.")


def _festival_preview(out, roster, current, value, data, hours, params):
    from employeeio.services.statutory import line_base

    L = roster.book.labour
    per_year = L.decimal("festivalBonusesPerYear")
    cap = L.decimal("festivalBonusCapMultiple")
    under = [(e, s, roster.months_served(e)) for e, s in roster.rows if (roster.months_served(e) or 0) < 12]

    def annual(v, d):
        r = Hypothetical("festival_bonus_policy", v, d)
        total = ZERO
        for _, s, months in under:
            full = line_base(s, "in_festival_base")[0] * cap
            amt, _ = festival_under_year(full, months or 0, r)
            total += amt
        return total * per_year

    opts = []
    for v, label in ELECTIONS["festival_bonus_policy"]["options"]:
        d = data if v == value and data else (current.data if current.value == v else
                                              {"bands": DEFAULT_BANDS} if v == "BANDED" else {})
        try:
            opts.append({"value": v, "label": label, "annualCost": _m(annual(v, d))})
        except ValueError as exc:
            opts.append({"value": v, "label": label, "annualCost": None, "error": str(exc)})
    out["options"] = opts
    out["affectedEmployees"] = len(under)
    by = {o["value"]: o["annualCost"] for o in opts}
    cur = to_decimal(by[current.value]) if current.answered and by.get(current.value) else None
    new = to_decimal(by[value]) if by.get(value) else None
    out["current"]["annualCost"] = by.get(current.value) if current.answered else None
    out["proposed"]["annualCost"] = by.get(value)
    out["deltaMonthly"] = None
    out["deltaAnnual"] = _m(new - cur) if cur is not None and new is not None else None
    out["notes"].append(f"{len(under)} employees are under twelve months' service; the whole cost of this election "
                        "sits on them. From twelve months the bonus is statutory and not elected.")


def _rounding_preview(out, roster, current, value, data, hours, params):
    opts = []
    for v, label in ELECTIONS["rounding_mode"]["options"]:
        worst, total = ZERO, ZERO
        for _, s in roster.rows:
            for c in s.components.all():
                exact = round_line(c.amount, "PAISA")
                diff = round_line(c.amount, v) - exact
                total += diff
                worst = max(worst, diff)
        opts.append({"value": v, "label": label, "companyMonthly": money_str(total), "worstLine": money_str(worst)})
    out["options"] = opts
    out["affectedEmployees"] = len(roster.rows)
    out["deltaMonthly"] = None
    out["notes"].append("Every line rounds once, up from the paisa — never down. Rounding down is a deduction, "
                        "and s.123 does not list it among the authorised ones. The figure is what the company pays "
                        "above the exact amounts each month.")


def _balancing_preview(out, roster, current, value, data, hours, params):
    from paylibio.choices import BASES
    from paylibio.services.library import current_components

    comps = {c.code: c for c in current_components(roster.company)}
    opts = []
    for v, label in ELECTIONS["balancing_component"]["options"]:
        c = comps.get(v)
        moves = [lbl for f, _, lbl, _ in BASES if c is not None and getattr(c, f) and f != "prorate_part_month"]
        opts.append({"value": v, "label": label, "bases": moves})
    out["options"] = opts
    out["deltaMonthly"] = None
    out["notes"].append("The residue is a few taka. On basic it raises the PF, gratuity and overtime bases; "
                        "on medical it raises none. A template may still name its own balancing line.")
