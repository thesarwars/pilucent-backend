"""The leave engine's core (backend spec §2, §3, §5): decimals, the rules,
the types, cycles, the ledger, `spendable()` and day counting.

Three positions it holds:

- No balance is stored. A position is summed from the ledger on every read:
  balance − held − committed = spendable, and nothing else computes it.
- A balance belongs to a cycle. Casual and sick leave live in the calendar
  year, earned leave in the service year, so last year's casual leave does
  not count this year without anyone forfeiting it; earned leave reaches
  the next year only through the year-end close (forfeit + opening). A
  compensatory credit is its own window and lapses by a CREDIT_EXPIRED entry.
- Day counting refuses without a published holiday calendar.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum

from common import clock
from employeeio.services.salary_access import actor_role
from rulebookio.book import NoRuleSetInForce, RuleSetView, resolve
from rulebookio.choices import RuleFamilyChoices

from ..choices import (
    AccrualKindChoices as AK,
    CycleKindChoices as CK,
    GenderRestrictionChoices,
    LeaveAuditActionChoices as A,
    LedgerReasonChoices as R,
    WorkerRestrictionChoices,
)
from ..models import LeaveAudit, LeaveCycle, LeaveHold, LeaveRequest, LeaveType, LedgerEntry

ZERO = Decimal("0")
Q4 = Decimal("0.0001")
ENGINE_VERSION = "pilucent-leave/1"
BLA = "Bangladesh Labour Act 2006"


# =================================================================== decimals


def d4(value) -> Decimal:
    """Through the decimal string, never the float: '0.1' + '0.2' is '0.3'."""
    if isinstance(value, Decimal):
        return value.quantize(Q4, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value).strip()).quantize(Q4, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise LeaveRefused({"days": [f"{value!r} is not a number of days."]}) from None


def days_str(value) -> str:
    """7.0000 -> '7', 20.2222 -> '20.2222', for the wire."""
    if value is None:
        return None
    text = format(d4(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def plural(n, one, many=None):
    many = many or one + "s"
    return f"{days_str(n)} {one if d4(n) == 1 else many}"


def fmt(d):
    return f"{d.day} {d:%b %Y}"


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def months_between(start, end):
    """Whole months of service from `start` to `end`."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(0, months)


# =================================================================== refusals


class LeaveRefused(Exception):
    """A refused operation: `errors` is field -> messages."""

    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def actor_name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def audit(company, entity, action, user, *, on_behalf_of=None, reason="", before=None, after=None, rule_set=None):
    entity_type = type(entity).__name__ if entity is not None else "Company"
    entity_id = str(getattr(entity, "reference", None) or getattr(entity, "uid", "") or company.pk)
    LeaveAudit.objects.create(
        company=company, entity_type=entity_type, entity_id=entity_id, action=action,
        actor=user if user is not None and getattr(user, "is_authenticated", False) else None,
        actor_name=actor_name(user) or "system", actor_role=actor_role(user, company), on_behalf_of=on_behalf_of,
        reason=reason or "", before_json=before, after_json=after, rule_set=rule_set, engine_version=ENGINE_VERSION,
    )


# ====================================================================== rules


@dataclass
class LeaveRules:
    """The leave figures of one labour rule set. Divisors and caps are per
    establishment class, never per company (§4)."""

    rule_set: object
    version: str
    confidence: str
    casual: Decimal
    sick: Decimal
    festival_days: int
    el_divisor: dict
    el_divisor_adolescent: dict
    el_cap: dict
    el_min_service_months: int
    encash_fraction: Decimal
    encash_per_cycle: int
    day_wage_divisor: int
    comp_due_days: int
    maternity_before: int
    maternity_after: int
    maternity_service_months: int
    maternity_max_children: int
    maternity_ban_weeks: int
    maternity_protection: dict
    citations: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)

    KEYS = {
        "casualLeaveDays": "Casual leave a calendar year",
        "sickLeaveDays": "Sick leave a calendar year",
        "festivalHolidayDays": "Festival holidays a year",
        "earnedLeaveRatioByEstablishment": "Earned leave: days worked per day earned",
        "earnedLeaveRatioAdolescentByEstablishment": "Earned leave, adolescent: days worked per day earned",
        "accumulationCapByEstablishment": "Earned leave accumulates to at most",
        "earnedLeaveEligibilityMonths": "Earned leave after this much service (months)",
        "encashmentFraction": "Encashable fraction of the spendable balance",
        "encashmentPerYear": "Encashments a cycle",
        "dayWageDivisor": "A day's wage for encashment: monthly wage ÷",
        "compensatoryHolidayDueDays": "A compensatory holiday lapses after (days)",
        "maternityDaysBefore": "Maternity leave before the delivery (days)",
        "maternityDaysAfter": "Maternity leave after the delivery (days)",
        "maternityMinimumServiceMonths": "Maternity benefit after this much service (months)",
        "maternityMaxSurvivingChildren": "Maternity benefit with at most this many surviving children",
        "maternityEmploymentBanWeeks": "No employment after the delivery for (weeks)",
        "maternityDismissalProtection": "Protection from dismissal",
    }

    @classmethod
    def of(cls, rule_set):
        L = RuleSetView(rule_set)
        got = {k: L.get(k) for k in cls.KEYS}
        order = ["DISPUTED", "DRAFTED", "CORROBORATED", "VERIFIED", "LIVE"]
        lowest = min((g.confidence for g in got.values()), key=lambda c: order.index(c) if c in order else 0)
        v = lambda k: got[k].value  # noqa: E731
        return cls(
            rule_set=rule_set, version=rule_set.version, confidence=lowest,
            casual=d4(v("casualLeaveDays")), sick=d4(v("sickLeaveDays")), festival_days=int(v("festivalHolidayDays")),
            el_divisor=dict(v("earnedLeaveRatioByEstablishment")),
            el_divisor_adolescent=dict(v("earnedLeaveRatioAdolescentByEstablishment")),
            el_cap=dict(v("accumulationCapByEstablishment")),
            el_min_service_months=int(v("earnedLeaveEligibilityMonths")),
            encash_fraction=Decimal(str(v("encashmentFraction"))), encash_per_cycle=int(v("encashmentPerYear")),
            day_wage_divisor=int(v("dayWageDivisor")), comp_due_days=int(v("compensatoryHolidayDueDays")),
            maternity_before=int(v("maternityDaysBefore")), maternity_after=int(v("maternityDaysAfter")),
            maternity_service_months=int(v("maternityMinimumServiceMonths")),
            maternity_max_children=int(v("maternityMaxSurvivingChildren")),
            maternity_ban_weeks=int(v("maternityEmploymentBanWeeks")),
            maternity_protection=dict(v("maternityDismissalProtection")),
            citations={k: g.citation for k, g in got.items()},
            rows=[{"key": k, "label": label, "value": got[k].value, "confidence": got[k].confidence,
                   "citation": got[k].citation, "note": got[k].note} for k, label in cls.KEYS.items()],
        )


class Book:
    """The labour rule set in force on a day, memoised for one operation."""

    def __init__(self):
        self._sets = {}
        self._rules = {}

    def rule_set(self, on):
        key = (on.year, on.month, on.day)
        if key not in self._sets:
            try:
                self._sets[key] = resolve(RuleFamilyChoices.LABOUR, on)
            except NoRuleSetInForce as exc:
                raise LeaveRefused({"ruleSet": [str(exc)]}, status=409) from None
        return self._sets[key]

    def rules(self, on):
        rs = self.rule_set(on)
        if rs.pk not in self._rules:
            self._rules[rs.pk] = LeaveRules.of(rs)
        return self._rules[rs.pk]


# ====================================================================== types

SEED = [
    dict(code="EARNED", name="Earned leave", name_bn="অর্জিত ছুটি", display_order=1, is_statutory=True,
         statutory_basis=f"{BLA}, s.117", cycle_kind=CK.SERVICE_YEAR, earn_in_arrears=True,
         accrual_kind=AK.PER_DAYS_WORKED, worker_restriction=WorkerRestrictionChoices.WORKER_ONLY,
         consumes_public_holidays=True, consumes_weekly_holidays=True, backdate_window_days=60, advance_allowed=True,
         carry_forward_allowed=True, encashment_allowed=True, payable_on_separation=True, on_grid=True),
    dict(code="CASUAL", name="Casual leave", name_bn="নৈমিত্তিক ছুটি", display_order=2, is_statutory=True,
         statutory_basis=f"{BLA}, s.115", cycle_kind=CK.CALENDAR_YEAR, accrual_kind=AK.FIXED_ANNUAL,
         worker_restriction=WorkerRestrictionChoices.WORKER_ONLY, half_day_allowed=True, backdate_window_days=60,
         on_grid=True),
    dict(code="SICK", name="Sick leave", name_bn="পীড়া ছুটি", display_order=3, is_statutory=True,
         statutory_basis=f"{BLA}, s.116", cycle_kind=CK.CALENDAR_YEAR, accrual_kind=AK.FIXED_ANNUAL,
         worker_restriction=WorkerRestrictionChoices.WORKER_ONLY, backdate_window_days=60,
         requires_medical_cert=True, on_grid=True),
    dict(code="MATERNITY", name="Maternity leave", name_bn="প্রসূতি ছুটি", display_order=4, is_statutory=True,
         statutory_basis=f"{BLA}, s.46", cycle_kind=CK.EVENT, accrual_kind=AK.EVENT,
         gender_restriction=GenderRestrictionChoices.WOMAN, counts_calendar_days=True),
    dict(code="COMPENSATORY", name="Compensatory holiday", name_bn="ক্ষতিপূরণমূলক ছুটি", display_order=5,
         is_statutory=True, statutory_basis=f"{BLA}, s.103, s.118", cycle_kind=CK.ROLLING, accrual_kind=AK.CREDIT,
         backdate_window_days=60),
    # No statutory basis in Bangladeshi labour law: a company policy.
    dict(code="BEREAVEMENT", name="Bereavement leave", name_bn="শোক ছুটি", display_order=6, is_statutory=False,
         cycle_kind=CK.CALENDAR_YEAR, accrual_kind=AK.FIXED_ANNUAL, accrual_days=Decimal(3), backdate_window_days=60),
]
GRID = ("EARNED", "CASUAL", "SICK")


def ensure_types(company):
    """The seeded types for a company, created on first use. {code: LeaveType}"""
    found = {t.code: t for t in LeaveType.objects.filter(company=company)}
    for seed in SEED:
        if seed["code"] not in found:
            try:
                with transaction.atomic():
                    found[seed["code"]] = LeaveType.objects.create(company=company, **seed)
            except IntegrityError:
                found[seed["code"]] = LeaveType.objects.get(company=company, code=seed["code"])
    return found


def type_of(company, code):
    types = ensure_types(company)
    code = str(code or "").upper()
    if code not in types or not types[code].is_active:
        raise LeaveRefused({"leaveType": [f"No leave type {code!r}."]}, status=400)
    return types[code]


def fixed_entitlement(ltype, rules):
    """Days a FIXED_ANNUAL type grants each cycle, and where that comes from."""
    if ltype.code == "CASUAL":
        return rules.casual, rules.citations["casualLeaveDays"]
    if ltype.code == "SICK":
        return rules.sick, rules.citations["sickLeaveDays"]
    return d4(ltype.accrual_days or 0), "company policy"


def basis_of(ltype):
    return ltype.statutory_basis or "company policy"


def restriction(employee, ltype, on, rules, *, service=True):
    """Why `employee` is not entitled to `ltype` on `on`, or None."""
    if ltype.gender_restriction == GenderRestrictionChoices.WOMAN and employee.gender != "FEMALE":
        return f"{ltype.name} is a woman's entitlement ({basis_of(ltype)})."
    if ltype.worker_restriction == WorkerRestrictionChoices.WORKER_ONLY:
        if not employee.classification:
            return f"Classification not recorded. {ltype.name} under {basis_of(ltype)} is a worker's entitlement."
        if employee.classification != "WORKER":
            return (f"{ltype.name} under {basis_of(ltype)} is a worker's entitlement, and {employee.name_en} is "
                    "classified non-worker. A company policy type would cover them.")
    if service:
        needed = {"EARNED": rules.el_min_service_months, "MATERNITY": rules.maternity_service_months}.get(ltype.code)
        if needed and ltype.code != "MATERNITY":
            if employee.doj is None:
                return "No date of joining recorded: service cannot be counted."
            served = months_between(employee.doj, on)
            if served < needed:
                return f"{served} months' service on {fmt(on)}; {ltype.name.lower()} starts after {needed} ({basis_of(ltype)})."
    return None


# ===================================================================== cycles


def anniversary(doj, year):
    try:
        return date(year, doj.month, doj.day)
    except ValueError:  # 29 February
        return date(year, 2, 28)


def cycle_bounds(ltype, employee, on):
    """The cycle of a CALENDAR_YEAR or SERVICE_YEAR type containing `on`."""
    if ltype.cycle_kind == CK.CALENDAR_YEAR:
        return date(on.year, 1, 1), date(on.year, 12, 31)
    if ltype.cycle_kind == CK.SERVICE_YEAR:
        if employee.doj is None or on < employee.doj:
            return None
        y = on.year
        start = anniversary(employee.doj, y)
        if on < start:
            y -= 1
            start = anniversary(employee.doj, y)
        return start, anniversary(employee.doj, y + 1) - timedelta(days=1)
    return None


def post(*, employee, ltype, cycle, days, reason, basis, effective, rule_set=None, user=None, source_ref="",
         on_behalf=False):
    """One ledger entry, pinned to `rule_set` -- by default the labour set in
    force on its effective date, so a past balance reproduces after the law
    changes."""
    if rule_set is None:
        try:
            rule_set = resolve(RuleFamilyChoices.LABOUR, effective)
        except NoRuleSetInForce:
            rule_set = cycle.rule_set
    return LedgerEntry.objects.create(
        company=employee.company, employee=employee, leave_type=ltype, cycle=cycle, effective_date=effective,
        days=d4(days), reason=reason, basis=basis, source_ref=source_ref, rule_set=rule_set,
        created_by=user if user is not None and getattr(user, "is_authenticated", False) else None,
        created_by_name=actor_name(user) or "system", on_behalf=on_behalf,
    )


def cycle_for(employee, ltype, on, book, *, create=True, user=None):
    """The cycle containing `on`, opened lazily (§3.3). Opening a fixed-annual
    type posts its grant. None when the type has no cycle for that day."""
    bounds = cycle_bounds(ltype, employee, on)
    if bounds is None:
        if ltype.cycle_kind in (CK.ROLLING, CK.EVENT):
            return (LeaveCycle.objects.filter(employee=employee, leave_type=ltype, starts_on__lte=on, ends_on__gte=on)
                    .order_by("ends_on").first())
        return None
    start, end = bounds
    found = LeaveCycle.objects.filter(employee=employee, leave_type=ltype, starts_on=start).first()
    if found is not None or not create:
        return found
    rules = book.rules(start)
    try:
        with transaction.atomic():
            cycle = LeaveCycle.objects.create(company=employee.company, employee=employee, leave_type=ltype,
                                              kind=ltype.cycle_kind, starts_on=start, ends_on=end,
                                              rule_set=rules.rule_set)
            if ltype.accrual_kind == AK.FIXED_ANNUAL and restriction(employee, ltype, start, rules) is None:
                days, cite = fixed_entitlement(ltype, rules)
                if days:
                    effective = max(start, employee.doj) if employee.doj else start
                    post(employee=employee, ltype=ltype, cycle=cycle, days=days, reason=R.ACCRUAL, effective=effective,
                         basis=f"{plural(days, 'day')} of {ltype.name.lower()} for {start.year} ({cite})")
    except IntegrityError:
        return LeaveCycle.objects.get(employee=employee, leave_type=ltype, starts_on=start)
    return cycle


# ===================================================================== ledger


def reverse_entry(entry, *, reason, replacement_days=None, user=None):
    """§2 rule 2: a correction is a reversal plus a replacement, written
    together. The original stays on the ledger, marked reversed."""
    from ..choices import REVERSIBLE

    with transaction.atomic():
        entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.reason == R.REVERSAL:
            raise LeaveRefused({"entry": ["A reversal is not itself reversed: reverse the original's replacement."]})
        if entry.reversed_by_id:
            raise LeaveRefused({"entry": [f"{entry.reference} is already reversed by LEDG-{entry.reversed_by_id:06d}."]},
                               status=409)
        if entry.reason not in REVERSIBLE:
            raise LeaveRefused({"entry": [
                f"A {entry.get_reason_display().lower()} entry is corrected through its own record: cancel the "
                "request or decline the encashment."]})
        reversal = LedgerEntry.objects.create(
            company=entry.company, employee=entry.employee, leave_type=entry.leave_type, cycle=entry.cycle,
            effective_date=entry.effective_date, days=-entry.days, reason=R.REVERSAL,
            basis=f"Reverses {entry.reference}: {reason}", source_ref=entry.reference, rule_set=entry.rule_set,
            created_by=user if user is not None and getattr(user, "is_authenticated", False) else None,
            created_by_name=actor_name(user) or "system",
        )
        if LedgerEntry.objects.filter(pk=entry.pk)._mark_reversed(reversal) != 1:
            raise LeaveRefused({"entry": [f"{entry.reference} was reversed meanwhile."]}, status=409)
        replacement = None
        if replacement_days is not None:
            replacement_days = d4(replacement_days)
            if replacement_days or entry.reason == R.ACCRUAL_CAPPED:
                replacement = LedgerEntry.objects.create(
                    company=entry.company, employee=entry.employee, leave_type=entry.leave_type, cycle=entry.cycle,
                    effective_date=entry.effective_date, days=replacement_days, reason=entry.reason,
                    basis=f"Replaces {entry.reference}: {reason}", source_ref=entry.reference,
                    rule_set=entry.rule_set,
                    created_by=user if user is not None and getattr(user, "is_authenticated", False) else None,
                    created_by_name=actor_name(user) or "system",
                )
        audit(entry.company, entry, A.REVERSED, user, on_behalf_of=entry.employee, reason=reason,
              before={"entry": entry.reference, "days": days_str(entry.days)},
              after={"reversal": reversal.reference,
                     "replacement": replacement.reference if replacement else None,
                     "days": days_str(replacement.days) if replacement else None},
              rule_set=entry.rule_set)
    return reversal, replacement


# ================================================================== positions


@dataclass
class Position:
    """A balance is three numbers, not one (§1.1 of the frontend spec)."""

    balance: Decimal = ZERO
    held: Decimal = ZERO
    committed: Decimal = ZERO
    eligible: bool = True
    reason: str | None = None
    cycle: object = None

    @property
    def spendable(self):
        return self.balance - self.held - self.committed

    def out(self):
        c = self.cycle
        return {
            "balance": days_str(self.balance), "held": days_str(self.held), "committed": days_str(self.committed),
            "spendable": days_str(self.spendable), "eligible": self.eligible, "reason": self.reason,
            "cycle": None if c is None else {"from": c.starts_on.isoformat(), "to": c.ends_on.isoformat(),
                                             "kind": c.kind},
        }


def _scope(ltype):
    """Whose entries make the balance: the one cycle containing the day, or,
    for a rolling credit, every window -- a credit leaves the balance only
    through its CREDIT_EXPIRED entry."""
    return "ALL" if ltype.cycle_kind == CK.ROLLING else "CYCLE"


def position(employee, ltype, as_of, *, cycle=None, exclude_request=None, book=None):
    """spendable() (§5.1). The single availability function: everything that
    shows or tests what can be spent calls this or `Positions`, which is the
    same arithmetic for many employees at once."""
    book = book or Book()
    if _scope(ltype) == "CYCLE":
        cycle = cycle or cycle_for(employee, ltype, as_of, book)
        if cycle is None:
            return Position(cycle=None)
        filt = {"cycle": cycle}
    else:
        filt = {"employee": employee, "leave_type": ltype}
    balance = (LedgerEntry.objects.filter(**filt, effective_date__lte=as_of, reversed_by__isnull=True)
               .exclude(reason=R.REVERSAL).aggregate(s=Sum("days"))["s"] or ZERO)
    holds = LeaveHold.objects.filter(**filt, released_at__isnull=True)
    if exclude_request is not None:
        holds = holds.exclude(request=exclude_request)
    held = holds.aggregate(s=Sum("days"))["s"] or ZERO
    committed = (LeaveRequest.objects.filter(**filt, status="APPROVED", from_date__gt=as_of)
                 .aggregate(s=Sum("days_consumed"))["s"] or ZERO)
    return Position(balance=d4(balance), held=d4(held), committed=d4(committed), cycle=cycle)


class Positions:
    """`position()` for many employees and types in a handful of queries:
    the balances tab is 300 employees × 3 types × 4 figures."""

    def __init__(self, company, employees, types, as_of, book=None, *, open_cycles=True):
        self.as_of = as_of
        self.book = book or Book()
        self.types = list(types)
        self.employees = list(employees)
        rules = self.book.rules(as_of)
        ids = [e.pk for e in self.employees]
        type_ids = [t.pk for t in self.types]

        self.cycles = {}
        for c in LeaveCycle.objects.filter(employee_id__in=ids, leave_type_id__in=type_ids, starts_on__lte=as_of,
                                           ends_on__gte=as_of).order_by("ends_on"):
            self.cycles.setdefault((c.employee_id, c.leave_type_id), c)
        self.reasons = {}
        for e in self.employees:
            for t in self.types:
                self.reasons[(e.pk, t.pk)] = restriction(e, t, as_of, rules, service=False)
                if (open_cycles and (e.pk, t.pk) not in self.cycles and _scope(t) == "CYCLE"
                        and t.cycle_kind != CK.EVENT and self.reasons[(e.pk, t.pk)] is None):
                    c = cycle_for(e, t, as_of, self.book)
                    if c is not None:
                        self.cycles[(e.pk, t.pk)] = c

        def grouped(qs, value):
            out = {}
            for row in qs.values("employee_id", "leave_type_id", "cycle_id").annotate(s=Sum(value)):
                out[(row["employee_id"], row["leave_type_id"], row["cycle_id"])] = row["s"] or ZERO
            return out

        base = dict(employee_id__in=ids, leave_type_id__in=type_ids)
        self.ledger = grouped(LedgerEntry.objects.filter(**base, effective_date__lte=as_of, reversed_by__isnull=True)
                              .exclude(reason=R.REVERSAL), "days")
        self.holds = grouped(LeaveHold.objects.filter(**base, released_at__isnull=True), "days")
        self.committed = grouped(LeaveRequest.objects.filter(**base, status="APPROVED", from_date__gt=as_of),
                                 "days_consumed")

    def _sum(self, table, e, t, cycle):
        if _scope(t) == "ALL":
            return sum((v for (ei, ti, _), v in table.items() if ei == e.pk and ti == t.pk), ZERO)
        if cycle is None:
            return ZERO
        return table.get((e.pk, t.pk, cycle.pk), ZERO)

    def of(self, e, t):
        cycle = self.cycles.get((e.pk, t.pk))
        reason = self.reasons.get((e.pk, t.pk))
        if reason is None and cycle is None and t.cycle_kind == CK.SERVICE_YEAR:
            reason = ("No date of joining recorded: the service year cannot be placed." if e.doj is None
                      else f"Joins on {fmt(e.doj)}.")
        return Position(balance=d4(self._sum(self.ledger, e, t, cycle)), held=d4(self._sum(self.holds, e, t, cycle)),
                        committed=d4(self._sum(self.committed, e, t, cycle)), eligible=reason is None,
                        reason=reason, cycle=cycle)


def position_sentence(p, ltype, verb="available"):
    """`2 days available — 7 on the ledger, 5 booked ahead` (§9.1)."""
    parts = [f"{days_str(p.balance)} on the ledger"]
    if p.held:
        parts.append(f"{days_str(p.held)} reserved by other requests")
    if p.committed:
        parts.append(f"{days_str(p.committed)} booked ahead")
    shown = max(p.spendable, ZERO)
    text = f"{plural(shown, 'day')} {verb} — {', '.join(parts)}"
    if p.spendable < 0:
        text += f"; {days_str(-p.spendable)} overdrawn"
    return text


# ============================================================== day counting


def day_breakdown(employee, ltype, from_date, to_date, start_half="FULL", end_half="FULL"):
    """§5.2. Per leave type, never global. Earned leave consumes the holidays
    inside it; casual and sick do not; maternity counts every calendar day.
    The sentence says which, and it is shown."""
    from employeeio.services.sites import site_of
    from timekeepingio.services.base import CalendarMissing, DayKinds, days_of

    if to_date < from_date:
        raise LeaveRefused({"toDate": ["The leave cannot end before it starts."]}, status=400)
    if (to_date - from_date).days > 366:
        raise LeaveRefused({"toDate": ["A request spans at most a year."]}, status=400)
    days = days_of(from_date, to_date)
    n = len(days)
    holidays, excluded, consumed = [], [], Decimal(0)
    if ltype.counts_calendar_days:
        consumed = Decimal(n)
        counting = "CALENDAR"
    else:
        try:
            kinds = DayKinds(site_of(employee), sorted({d.year for d in days}), strict=True)
        except CalendarMissing as exc:
            raise LeaveRefused(exc.errors, status=409, detail=exc.detail) from None
        counting = "CONSUMES" if ltype.consumes_public_holidays else "EXCLUDES"
        for d in days:
            kind, name = kinds.of(d)
            if kind == "WEEKLY":
                holidays.append({"date": d.isoformat(), "name": "Weekly holiday", "kind": "WEEKLY"})
                if not ltype.consumes_weekly_holidays:
                    excluded.append(holidays[-1])
                    continue
            elif kind == "HOLIDAY":
                holidays.append({"date": d.isoformat(), "name": name or "Holiday", "kind": "FESTIVAL"})
                if not ltype.consumes_public_holidays:
                    excluded.append(holidays[-1])
                    continue
            consumed += 1
    halves = []
    if ltype.half_day_allowed and consumed:
        if start_half == "SECOND_HALF":
            consumed -= Decimal("0.5")
            halves.append("starts at the second half")
        if end_half == "FIRST_HALF" and (to_date != from_date or start_half != "SECOND_HALF"):
            consumed -= Decimal("0.5")
            halves.append("ends at the first half")
    elif start_half != "FULL" or end_half != "FULL":
        raise LeaveRefused({"startHalf": [f"{ltype.name} is taken in whole days."]}, status=422)
    consumed = d4(max(consumed, Decimal(0)))

    def named(rows):
        def one(h):
            d = date.fromisoformat(h["date"])
            return (f"the weekly holiday on {d:%a} {d.day} {d:%b}" if h["kind"] == "WEEKLY"
                    else f"{h['name']} on {d.day} {d:%b}")
        items = [one(h) for h in rows]
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

    span = f"{n} calendar {'day' if n == 1 else 'days'}"
    label = ltype.name.lower()
    if counting == "CALENDAR":
        sentence = f"{span}, every one counted: {label} counts calendar days, holidays included."
    elif counting == "CONSUMES" and holidays:
        sentence = f"{span}. {ltype.name} counts the holidays inside it — {named(holidays)} — so {plural(consumed, 'day')}."
    elif excluded:
        verb = "is" if len(excluded) == 1 else "are"
        sentence = f"{span}. {ltype.name} does not count holidays, so {named(excluded)} {verb} excluded: {plural(consumed, 'day')} of {label}."
    else:
        sentence = f"{span}, no holidays inside: {plural(consumed, 'day')} of {label}."
    if halves:
        sentence += f" It {' and '.join(halves)}."
    return {"from": from_date.isoformat(), "to": to_date.isoformat(), "calendarDays": n, "holidays": holidays,
            "excluded": excluded, "consumed": days_str(consumed), "counting": counting, "startHalf": start_half,
            "endHalf": end_half, "sentence": sentence}


# ========================================================== compensatory credits


def post_credit(credit, *, book=None, types=None):
    """An attendance holiday-working credit (timekeepingio.CompensatoryCredit)
    onto the ledger as CREDIT_EARNED, in its own window. Idempotent: the
    credit's uid is the entry's source, and the second posting is refused by
    the unique index."""
    book = book or Book()
    employee = credit.employee
    ltype = (types or ensure_types(employee.company))["COMPENSATORY"]
    rules = book.rules(credit.business_date)
    start = credit.business_date
    end = start + timedelta(days=rules.comp_due_days - 1)
    try:
        with transaction.atomic():
            cycle, _ = LeaveCycle.objects.get_or_create(
                employee=employee, leave_type=ltype, starts_on=start,
                defaults={"company": employee.company, "kind": CK.ROLLING, "ends_on": end, "rule_set": rules.rule_set})
            worked = "festival holiday" if credit.decision.kind == "WORKED_FESTIVAL_HOLIDAY" else "weekly holiday"
            if credit.kind == "SUBSTITUTE":
                basis = f"Substitute holiday for the {worked} worked on {fmt(start)} ({credit.citation or 's.118'})"
            else:
                basis = (f"Worked the {worked} on {fmt(start)}: {plural(credit.days, 'compensatory day')} "
                         f"({credit.citation or 's.103'})")
            entry = post(employee=employee, ltype=ltype, cycle=cycle, days=credit.days, reason=R.CREDIT_EARNED,
                         effective=start, basis=f"{basis}; to be taken by {fmt(cycle.ends_on)}",
                         source_ref=f"credit:{credit.uid}")
            audit(employee.company, entry, A.CREDIT_EARNED, None, on_behalf_of=employee,
                  after={"days": days_str(credit.days), "kind": credit.kind, "date": start.isoformat()},
                  rule_set=rules.rule_set)
            return entry
    except IntegrityError:
        return None


def sync_credits(company, employees=None, book=None):
    """Post any attendance credit not yet on the ledger."""
    from timekeepingio.models import CompensatoryCredit

    qs = CompensatoryCredit.objects.filter(company=company).select_related("employee__company", "decision")
    if employees is not None:
        qs = qs.filter(employee__in=employees)
    posted = set(LedgerEntry.objects.filter(company=company, reason=R.CREDIT_EARNED, source_ref__startswith="credit:")
                 .values_list("source_ref", flat=True))
    book = book or Book()
    types = ensure_types(company)
    return [post_credit(c, book=book, types=types) for c in qs if f"credit:{c.uid}" not in posted]


def expire_credits(company, as_of, employees=None, user=None):
    """CREDIT_EXPIRED for whatever of a credit was not taken by its window's
    end. Consumption is allocated oldest credit first, so taking a day uses
    the credit that lapses soonest."""
    types = ensure_types(company)
    ltype = types["COMPENSATORY"]
    cycles = LeaveCycle.objects.filter(company=company, leave_type=ltype).order_by("ends_on", "starts_on")
    if employees is not None:
        cycles = cycles.filter(employee__in=employees)
    by_employee = {}
    for c in cycles.select_related("employee"):
        by_employee.setdefault(c.employee_id, []).append(c)
    posted = []
    for cs in by_employee.values():
        if not any(c.ends_on < as_of for c in cs):
            continue
        entries = (LedgerEntry.objects.filter(cycle__in=cs, reversed_by__isnull=True).exclude(reason=R.REVERSAL)
                   .values("cycle_id", "reason", "days"))
        credit = {c.pk: ZERO for c in cs}
        expired = {c.pk: ZERO for c in cs}
        used = ZERO
        for row in entries:
            if row["reason"] == R.CREDIT_EXPIRED:
                expired[row["cycle_id"]] += -row["days"]
            elif row["reason"] in (R.CREDIT_EARNED, R.OPENING) or (row["reason"] == R.ADJUSTMENT and row["days"] > 0):
                credit[row["cycle_id"]] += row["days"]
            else:
                used += -row["days"]
        for c in cs:
            available = credit[c.pk] - expired[c.pk]
            take = min(max(available, ZERO), max(used, ZERO))
            used -= take
            left = available - take
            if c.ends_on < as_of and left > 0:
                entry = post(employee=c.employee, ltype=ltype, cycle=c, days=-left, reason=R.CREDIT_EXPIRED,
                             effective=c.ends_on + timedelta(days=1), user=user,
                             basis=f"{plural(left, 'day')} not taken by {fmt(c.ends_on)}: the compensatory holiday "
                                   f"lapses ({ltype.statutory_basis})")
                audit(company, entry, A.CREDIT_EXPIRED, user, on_behalf_of=c.employee,
                      after={"days": days_str(left)}, rule_set=c.rule_set)
                posted.append(entry)
    return posted


def refresh_credits(company, as_of, employees=None):
    """Credits in, lapsed credits out: run before positions are read, so a
    compensatory balance is never one the ledger has not been told about."""
    sync_credits(company, employees)
    expire_credits(company, as_of, employees)


def today():
    return clock.today()

