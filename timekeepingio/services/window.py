"""A window of days for a set of employees, loaded in a handful of queries
and computed day by day (§9.1: one query per input, not one per cell).

Everything returned here is recomputed from the inputs on every call:
punches, the live adjustment, the shift in force, the calendar and the
decisions taken. Nothing derived is read back.
"""

from datetime import timedelta

from common import clock

from ..choices import ExceptionStateChoices
from ..models import Adjustment, ExceptionDecision, Punch
from .base import DHAKA, DayKinds, assignments_by_employee, days_of, shift_on
from .engine import EXCEPTIONS, AdjSpec, DayInput, compute_day


class Window:
    def __init__(self, company, site, employees, first, last, rules, *, strict_calendar=True, today=None):
        self.company, self.site = company, site
        self.employees = list(employees)
        self.first, self.last = first, last
        self.rules = rules
        self.today = today or clock.today()
        self.days = days_of(first, last)
        self.kinds = DayKinds(site, sorted({d.year for d in self.days}), strict=strict_calendar)
        self._kind_cache = {d: self.kinds.of(d) for d in self.days}
        self.assignments = assignments_by_employee(self.employees, first, last)
        ids = [e.pk for e in self.employees]

        self.punches = {}
        for p in Punch.objects.filter(employee_id__in=ids, business_date__gte=first, business_date__lte=last):
            local = p.punched_at.astimezone(DHAKA)
            minute = (local.date() - p.business_date).days * 1440 + local.hour * 60 + local.minute
            self.punches.setdefault((p.employee_id, p.business_date), []).append((minute, p.direction))

        self.adjustments = {}
        for a in Adjustment.objects.filter(employee_id__in=ids, business_date__gte=first, business_date__lte=last,
                                           is_live=True):
            if not a.removed:
                self.adjustments[(a.employee_id, a.business_date)] = a

        self.decisions = {}
        for x in ExceptionDecision.objects.filter(employee_id__in=ids, business_date__gte=first,
                                                  business_date__lte=last, is_live=True):
            self.decisions[(x.employee_id, x.business_date, x.kind)] = x
        self._records = {}

    def kind_of(self, d):
        return self._kind_cache[d] if d in self._kind_cache else self.kinds.of(d)

    def employed(self, e, d):
        return (e.doj is None or d >= e.doj) and (e.separated_on is None or d <= e.separated_on)

    def record(self, e, d):
        key = (e.pk, d)
        if key not in self._records:
            adj = self.adjustments.get(key)
            spec = AdjSpec(adj.new_status, adj.in_time_min, adj.out_time_min, adj.worked_minutes,
                           adj.overtime_minutes) if adj else None
            inp = DayInput(day=d, today=self.today, employed=self.employed(e, d),
                           shift=shift_on(self.assignments.get(e.pk), d), day_kind=self.kind_of(d)[0],
                           punches=self.punches.get(key, []), adjustment=spec)
            self._records[key] = compute_day(inp, self.rules)
        return self._records[key]

    def records(self, e):
        return [self.record(e, d) for d in self.days]

    def decision(self, e, d, kind):
        return self.decisions.get((e.pk, d, kind))

    def open_kinds(self, e, d):
        """The day's exceptions no one has decided."""
        return [k for k in self.record(e, d).exceptions if self.decision(e, d, k) is None]

    def blocking_open(self, e, d):
        return [k for k in self.open_kinds(e, d) if EXCEPTIONS[k][2]]

    def acknowledged(self, e, d, kind):
        x = self.decision(e, d, kind)
        return x is not None and x.state == ExceptionStateChoices.ACKNOWLEDGED

    def input_hash(self, e, d):
        """What the day was computed from: punches, adjustment, shift, calendar
        kind, rule set (§3.8). A snapshot whose hash no longer matches is stale."""
        import hashlib
        import json

        adj = self.adjustments.get((e.pk, d))
        shift = shift_on(self.assignments.get(e.pk), d)
        payload = {
            "punches": sorted(self.punches.get((e.pk, d), [])),
            "adjustment": adj.pk if adj else None,
            "shift": shift.id if shift else None,
            "kind": self.kind_of(d)[0],
            "ruleSet": self.rules.rule_set_id,
            "decisions": sorted(k for (eid, day, k) in self.decisions if eid == e.pk and day == d),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def iso_weeks(first, last):
    """Mondays of every ISO week overlapping [first, last]."""
    monday = first - timedelta(days=first.weekday())
    out = []
    while monday <= last:
        out.append(monday)
        monday += timedelta(days=7)
    return out
