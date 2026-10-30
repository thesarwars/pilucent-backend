"""Run payroll operations (docs/backend/run-payroll-done.md §6).

    create ─► DRAFT ─► (team confirmed) TEAM_SELECTED ─► compute ─► COMPUTED
        ─► approve ─► APPROVED ─► instruct ─► DISBURSING ─► mark paid ─► PAID
        ─► release ─► CLOSED

Every move is a transition row with its actor (§2.1). The run row is locked
for compute, approve, instruct and release (§9.1). Approval and disbursement
are separate permissions; the approver is never the creator (§3.3).
Decisions taken where the spec leaves the question open (§12):

1. The payment day is the schedule's, checked at write against the s.123
   deadline by payroll settings; the due date shown is derived from the
   site's published calendar, never typed.
2. An approved run is never recomputed. A late correction is an adjustment run.
3. Drift between compute and approve refuses the approval, naming who moved.
5. The payroll officer may exclude an employee to clear a blocker, with a
   reason the approver sees before approving.
6. Cash is warned, not refused.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from common import clock
from common.money import ZERO, to_decimal
from common.words import format_date, format_money, format_month_year

from ..choices import (
    ENGINE_VERSION,
    FIXED,
    PRE_APPROVAL,
    TRANSITIONS,
    AuditActionChoices,
    PayStatusChoices,
    RunStateChoices,
)
from ..models import (
    CorporateAccount,
    PaymentInstruction,
    PaymentInstructionLine,
    PayrollAudit,
    PayrollException,
    PayrollRun,
    PayrollRunLine,
    PayrollRunTransition,
    RunEvent,
)
from . import bankfiles
from .engine import compute_line
from .inputs import NoStructure, attendance, destination_row, gather, payment_of, snapshot, team

A = AuditActionChoices
S = RunStateChoices
MIN_REASON = 10
APP = "payrunio"
MAX_OT_HOURS = Decimal("400")


class RunRefused(Exception):
    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _role(user, company):
    from employeeio.services.salary_access import actor_role

    return actor_role(_who(user), company)


def _reason(text, what="a reason"):
    text = str(text or "").strip()
    if len(text) < MIN_REASON:
        raise RunRefused({"reason": [f"Give {what}, at least {MIN_REASON} characters ({len(text)} so far)."]})
    return text


def money(v):
    return format_money(to_decimal(v), places=0)


def audit(run, action, user, *, employee=None, before=None, after=None, reason="", company=None):
    PayrollAudit.objects.create(company=company or run.company, run=run, action=action, employee=employee,
                                actor=_who(user), actor_name=_name(user), actor_role=_role(user, company or run.company),
                                before_json=before, after_json=after, reason=reason or "", engine_version=ENGINE_VERSION)


ROUTES = {
    "PayrollComputed": ("PAYROLL_RUN_COMPUTED", "approve_payroll_run"),
    "PayrollApproved": ("PAYROLL_RUN_APPROVED", "instruct_payroll_payment"),
    "PayslipsReleased": ("PAYSLIPS_RELEASED", "view_payroll_run"),
}


def event(run, name, *, message="", actor=None, **payload):
    """§8. The outbox row, and a notification to whoever acts next."""
    payload.update(runId=str(run.uid), period=run.period, site=run.site.name, ruleSetId=str(run.rule_set.uid),
                   taxCardId=str(run.tax_card.uid), engineVersion=run.engine_version)
    ev = RunEvent.objects.create(company=run.company, run=run, name=name, payload=payload)
    route = ROUTES.get(name)
    if route:
        from intakeio.services.ops import holders
        from notificationio.choices import NotificationModelKindChoices, NotificationStatusChoices
        from notificationio.services.notifications import NotificationService

        kind, perm = route
        users = {u.pk: u for u in holders(run.company, APP, perm)}
        users.pop(getattr(actor, "pk", None), None)
        if users:
            NotificationService.create_notification(
                status=NotificationStatusChoices.PUBLISHED, model_kind=NotificationModelKindChoices.PAYROLL_RUN,
                kind=kind, message=(message or name)[:100], is_company=True, users=list(users.values()))
    return ev


def move(run, to, user, reason=""):
    """§2. A transition the table does not permit is refused, never skipped."""
    if to not in TRANSITIONS[run.state]:
        raise RunRefused({"state": [f"A run that is {S(run.state).label.lower()} cannot become "
                                    f"{S(to).label.lower()}."]}, status=409)
    PayrollRunTransition.objects.create(run=run, from_state=run.state, to_state=to, actor=user,
                                        actor_name=_name(user), actor_role=_role(user, run.company), reason=reason or "")
    run.state = to
    run.save(update_fields=["state", "updated_at"])


def _locked(run):
    return PayrollRun.objects.select_for_update().select_related("company", "site", "schedule", "rule_set",
                                                                 "tax_card").get(pk=run.pk)


def _need(run, *states):
    if run.state not in states:
        raise RunRefused({"state": [f"The run is {S(run.state).label.lower()}; this needs it "
                                    f"{' or '.join(S(s).label.lower() for s in states)}."]}, status=409)


# ================================================================== context


class Context:
    """The rule book, the calendar and the attendance one run reads."""

    def __init__(self, run, employees):
        from paysetio.services.calendar import Calendar
        from rulebookio.book import rule_book

        self.book = rule_book(run.period_end)
        self.calendar = Calendar(run.site)
        self.att = attendance(run, employees)


def _period_bounds(period_start):
    from paysetio.services.calendar import month_bounds

    return month_bounds(period_start)


def _refresh(run, line, employee, ctx):
    """The team-stage view of a line: who, how they are paid, the days and
    the overtime attendance locked, and the structure in force."""
    from employeeio.services.salary import structure_in_force
    from employeeio.services.statutory import proration_factor

    from .inputs import days

    att = ctx.att[employee.pk]
    calendar_days, payable, lost, lwp, join, leave = days(run, employee, att)
    method, provider, _, dest, on_hold, _ = payment_of(employee)
    structure = structure_in_force(employee, run.period_end) or structure_in_force(employee, run.period_start)
    line.calendar_days, line.payable_days, line.days_lost, line.lwp_days = calendar_days, payable, lost, lwp
    line.join_date_in_period, line.leave_date_in_period = join, leave
    line.payment_method, line.mfs_provider, line.destination_ref = method, provider, dest
    line.payment_status = PayStatusChoices.HELD if on_hold else PayStatusChoices.PENDING
    line.ot_hours_attendance = att["ot"]
    if line.ot_hours_source != "MANUAL_OVERRIDE":
        line.ot_hours = att["ot"]
    line.structure = structure
    line.gross_before_proration = structure.gross if structure else None
    try:
        factor = proration_factor(run.period_start, run.elections_snapshot["elections"]["proration_method"]["value"],
                                  ctx.book, join_date=join, leave_date=leave, lwp_days=lwp, calendar=ctx.calendar)
    except Exception:  # noqa: BLE001 -- shown at compute, where it refuses properly
        factor = Decimal(1)
    line.proration_factor = factor if factor > 0 else Decimal(1)
    return line


# =================================================================== create


@transaction.atomic
def create_run(company, site, period_start, *, user, idempotency_key=""):
    """§6.1."""
    from employeeio.services.sites import default_site
    from paysetio.services.calendar import CalendarMissing, Calendar, payment_date, statutory_deadline
    from paysetio.services.ops import SettingsRefused, assert_runnable, schedule_in_force
    from paysetio.services.resolve import elections_for
    from rulebookio.book import RuleBookError, rule_book
    from timekeepingio.models import AttendancePeriod

    if idempotency_key:
        found = PayrollRun.objects.filter(company=company, idempotency_key=idempotency_key).first()
        if found is not None:
            return found, False
    site = site or default_site(company)
    period_start = period_start.replace(day=1)
    _, period_end = _period_bounds(period_start)
    label = format_month_year(period_start)

    existing = (PayrollRun.objects.filter(site=site, period_start=period_start, run_type="REGULAR")
                .exclude(state=S.CANCELLED).first())
    if existing is not None:
        raise RunRefused({"run": [f"{site.name} already has a regular run for {label} "
                                  f"({S(existing.state).label.lower()}). A correction is an adjustment run."]},
                         status=409, detail={"runId": str(existing.uid)})
    att = AttendancePeriod.objects.filter(site=site, period_month=period_start).first()
    if att is None or att.status != "LOCKED":
        raise RunRefused({"attendance": [f"The attendance period for {label} at {site.name} is still open. Lock it "
                                         "first, so the run agrees with what attendance locked."]}, status=422,
                         detail={"code": "ATTENDANCE_NOT_LOCKED"})
    try:
        assert_runnable(company, site, period_start, user=user)
    except SettingsRefused as exc:
        raise RunRefused(exc.errors, status=409, detail={"code": "SETTINGS", **(exc.detail or {})}) from None
    schedule = schedule_in_force(company, site, period_end)
    if schedule.frequency != "MONTHLY":
        raise RunRefused({"schedule": [f"{schedule.get_frequency_display()} schedules cannot be run yet: only a "
                                       "monthly wage period is supported."]}, status=422)
    try:
        book = rule_book(period_end)
        labour, tax = book.labour, book.tax
    except RuleBookError as exc:
        raise RunRefused({"ruleSet": [f"No published rule set as at {format_date(period_end)}: {exc}"]},
                         status=409, detail={"code": "NO_RULE_SET"}) from None
    try:
        due = statutory_deadline(Calendar(site), period_end)
    except CalendarMissing as exc:
        raise RunRefused(exc.errors, status=409, detail={"code": "NO_CALENDAR"}) from None

    snap = snapshot(elections_for(company, site, period_end), labour)
    try:
        with transaction.atomic():
            run = PayrollRun.objects.create(
                company=company, site=site, schedule=schedule, period=period_start.strftime("%Y-%m"),
                period_start=period_start, period_end=period_end, statutory_due_date=due,
                payment_date=payment_date(period_start, schedule.payment_day), rule_set=labour.rule_set,
                tax_card=tax.rule_set, engine_version=ENGINE_VERSION, elections_snapshot=snap, created_by=user,
                created_by_name=_name(user), idempotency_key=idempotency_key or "")
    except IntegrityError:
        raise RunRefused({"run": [f"{site.name} already has a regular run for {label}."]}, status=409) from None
    PayrollRunTransition.objects.create(run=run, from_state=None, to_state=S.DRAFT, actor=user, actor_name=_name(user),
                                        actor_role=_role(user, company))
    employees = list(team(run).select_related("payment", "tax_profile"))
    ctx = Context(run, employees)
    for e in employees:
        line = PayrollRunLine(company=company, run=run, employee=e, calendar_days=1, payable_days=0)
        _refresh(run, line, e, ctx).save()
    _counts(run)
    audit(run, A.RUN_CREATED, user, after={"period": run.period, "site": site.name, "members": len(employees),
                                           "dueDate": due.isoformat(), "ruleSet": labour.version,
                                           "taxCard": tax.version})
    event(run, "PayrollRunCreated", actor=user, members=len(employees))
    return run, True


def _counts(run):
    lines = run.lines.all()
    run.member_count = lines.count()
    run.included_count = lines.filter(included=True).count()
    run.excluded_count = run.member_count - run.included_count
    run.save(update_fields=["member_count", "included_count", "excluded_count", "updated_at"])


def _totals(run):
    """Σ over included lines; the run states what its lines add to (§5.1)."""
    from django.db.models import Sum

    agg = run.lines.filter(included=True).aggregate(g=Sum("gross"), t=Sum("tax_withheld"), pe=Sum("pf_employee"),
                                                    pr=Sum("pf_employer"), n=Sum("net_pay"))
    run.total_gross, run.total_tax = to_decimal(agg["g"] or 0), to_decimal(agg["t"] or 0)
    run.total_pf_employee, run.total_pf_employer = to_decimal(agg["pe"] or 0), to_decimal(agg["pr"] or 0)
    run.total_net = to_decimal(agg["n"] or 0)
    run.save(update_fields=["total_gross", "total_tax", "total_pf_employee", "total_pf_employer", "total_net",
                            "updated_at"])
    _counts(run)


# ================================================================ the team


def _reopen_team(run, user, why):
    """A team change after computing makes the figures stale: back to the
    team stage, recompute before approval."""
    if run.state == S.COMPUTED:
        move(run, S.TEAM_SELECTED, user, why)
        audit(run, A.TEAM_REOPENED, user, reason=why)


@transaction.atomic
def set_line(run, line, *, user, included=None, reason="", ot_hours=..., can_exclude=False, can_override=False):
    """Exclude or include an employee for this run only (§7.3), or type over
    the overtime attendance locked (§7.2). Neither touches their record."""
    run = _locked(run)
    _need(run, *PRE_APPROVAL)
    line = PayrollRunLine.objects.select_related("employee").get(pk=line.pk, run=run)
    changed = []
    if included is not None and bool(included) != line.included:
        if not can_exclude:
            raise RunRefused({"permission": ["Excluding or including needs the 'exclude payroll employee' "
                                             "permission."]}, status=403)
        if not included:
            why = _reason(reason, "the reason for leaving them out of this run")
            line.included, line.exclusion_reason = False, why
            line.excluded_by, line.excluded_by_name = _who(user), _name(user)
            _resolve_open(line, "EXCLUDED", why, user)
            audit(run, A.EMPLOYEE_EXCLUDED, user, employee=line.employee, reason=why)
        else:
            line.included, line.exclusion_reason, line.excluded_by, line.excluded_by_name = True, None, None, ""
            audit(run, A.EMPLOYEE_INCLUDED, user, employee=line.employee)
        changed.append("team")
    if ot_hours is not ...:
        if not can_override:
            raise RunRefused({"permission": ["Typing over attendance overtime needs the 'override payroll OT' "
                                             "permission."]}, status=403)
        before = {"otHours": format(line.ot_hours, "f"), "source": line.ot_hours_source}
        if ot_hours in (None, ""):
            line.ot_hours, line.ot_hours_source, line.ot_hours_overridden_by = line.ot_hours_attendance, "ATTENDANCE", None
            line.ot_override_reason = ""
        else:
            try:
                hours = Decimal(str(ot_hours)).quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001
                raise RunRefused({"otHours": ["Overtime hours must be a number."]}) from None
            if hours < 0 or hours > MAX_OT_HOURS:
                raise RunRefused({"otHours": [f"Overtime hours must be 0 to {MAX_OT_HOURS}."]})
            if hours == line.ot_hours_attendance:
                line.ot_hours, line.ot_hours_source, line.ot_hours_overridden_by = hours, "ATTENDANCE", None
                line.ot_override_reason = ""
            else:
                line.ot_hours, line.ot_hours_source, line.ot_hours_overridden_by = hours, "MANUAL_OVERRIDE", _who(user)
                line.ot_override_reason = str(reason or "").strip()
        audit(run, A.OT_OVERRIDDEN, user, employee=line.employee, before=before,
              after={"otHours": format(line.ot_hours, "f"), "source": line.ot_hours_source,
                     "attendance": format(line.ot_hours_attendance, "f")}, reason=line.ot_override_reason)
        changed.append("overtime")
    if changed:
        line.save()
        _counts(run)
        _reopen_team(run, user, f"{' and '.join(changed).capitalize()} changed after computing")
    return line


@transaction.atomic
def include_all(run, *, user):
    run = _locked(run)
    _need(run, *PRE_APPROVAL)
    lines = list(run.lines.filter(included=False).select_related("employee"))
    for line in lines:
        line.included, line.exclusion_reason, line.excluded_by, line.excluded_by_name = True, None, None, ""
        line.save()
        audit(run, A.EMPLOYEE_INCLUDED, user, employee=line.employee)
    if lines:
        _counts(run)
        _reopen_team(run, user, "Team changed after computing")
    return len(lines)


def _resolve_open(line, resolution, reason, user):
    for x in line.exceptions.filter(resolved=False):
        x.resolved, x.resolution, x.resolution_reason = True, resolution, reason
        x.resolved_by, x.resolved_by_name, x.resolved_at = _who(user), _name(user), timezone.now()
        x.save()


# ================================================================= compute


@transaction.atomic
def compute(run, *, user):
    """§6.2. Every included line gets a payslip or a block. Idempotent while
    the run is pre-approval: figures and open exceptions are replaced
    wholesale; exclusions, overtime overrides and accepted warnings stay."""
    run = _locked(run)
    _need(run, *PRE_APPROVAL)
    if run.state == S.DRAFT:
        move(run, S.TEAM_SELECTED, user)
        audit(run, A.TEAM_CONFIRMED, user, after={"included": run.lines.filter(included=True).count()})
    lines = list(run.lines.select_related("employee", "employee__payment", "employee__tax_profile")
                 .order_by("employee__code"))
    accepted = {(x.line_id, x.code): x for x in run.exceptions.filter(resolution="ACCEPTED")}
    run.exceptions.filter(line__included=True).delete()
    run.exceptions.filter(line__isnull=True).delete()
    ctx = Context(run, [ln.employee for ln in lines])
    now = timezone.now()
    for line in lines:
        e = line.employee
        _refresh(run, line, e, ctx)
        if not line.included:
            _zero(line)
            line.save()
            continue
        try:
            inp, structure, proj = gather(run, line, e, ctx.book, ctx.calendar, ctx.att[e.pk])
        except NoStructure as exc:
            _zero(line)
            line.blocked, line.computed_at, line.input_hash = True, now, ""
            line.save()
            _exception(run, line, "NO_STRUCTURE", "BLOCK", f"{exc} Assign one in the salary profile, or exclude "
                                                           "the line and pay it on a supplementary run.")
            continue
        if inp.factor <= 0:
            _zero(line)
            why = f"Nothing payable in {format_month_year(run.period_start)}: {inp.lwp_days.normalize():f} day(s) " \
                  "leave without pay cover the whole period of employment."
            line.included, line.exclusion_reason, line.excluded_by, line.excluded_by_name = False, why, None, "system"
            line.save()
            continue
        r = compute_line(inp)
        line.blocked, line.structure = False, structure
        line.gross_before_proration, line.proration_factor = inp.monthly_gross, inp.factor
        line.ot_base_amount, line.ot_amount = r.ot_base, r.ot_amount
        line.gross, line.tax_withheld, line.pf_employee, line.pf_employer = r.gross, r.tax, r.pf_employee, r.pf_employer
        line.other_deductions, line.net_pay = r.other, r.net
        line.earnings_json, line.deductions_json = r.earnings, r.deductions
        line.tax_derivation_json = proj.as_dict()
        line.computed_at, line.input_hash = now, r.input_hash
        line.save()
        for x in r.exceptions:
            ex = _exception(run, line, x["code"], x["severity"], x["message"], x["citation"])
            prior = accepted.get((line.pk, x["code"]))
            if prior is not None and ex.severity != "BLOCK":
                ex.resolved, ex.resolution, ex.resolution_reason = True, "ACCEPTED", prior.resolution_reason
                ex.resolved_by, ex.resolved_by_name, ex.resolved_at = prior.resolved_by, prior.resolved_by_name, \
                    prior.resolved_at
                ex.save()
    _totals(run)
    run.computed_at = now
    run.save(update_fields=["computed_at", "updated_at"])
    if run.state == S.TEAM_SELECTED:
        move(run, S.COMPUTED, user)
    blockers = blocking(run).count()
    audit(run, A.COMPUTED, user, after={"included": run.included_count, "net": format(run.total_net, "f"),
                                        "blockers": blockers})
    event(run, "PayrollComputed", actor=user, blockers=blockers, totalNet=format(run.total_net, "f"),
          message=f"{run.site.name} payroll for {format_month_year(run.period_start)} computed: "
                  f"{money(run.total_net)} awaiting approval")
    return run, blockers


def _zero(line):
    line.gross = line.tax_withheld = line.pf_employee = line.pf_employer = line.other_deductions = ZERO
    line.net_pay = line.ot_amount = line.ot_base_amount = ZERO
    line.earnings_json = line.deductions_json = line.tax_derivation_json = None
    line.blocked = False


def _exception(run, line, code, severity, message, citation=""):
    return PayrollException.objects.create(company=run.company, run=run, line=line,
                                           employee=line.employee if line else None, severity=severity, code=code,
                                           message=message, citation=citation or "")


def blocking(run):
    return run.exceptions.filter(severity="BLOCK", resolved=False, line__included=True)


# ============================================================== exceptions


@transaction.atomic
def resolve_exception(run, exc, *, resolution, reason="", user, can_exclude=False):
    """§6.3. EXCLUDED leaves the line out of this run with the reason;
    FIXED_UPSTREAM recomputes; ACCEPTED is for warnings only."""
    run = _locked(run)
    _need(run, S.COMPUTED)
    exc = PayrollException.objects.select_related("line", "line__employee").get(pk=exc.pk, run=run)
    if exc.resolved:
        raise RunRefused({"exception": ["Already resolved."]}, status=409)
    if resolution == "ACCEPTED":
        if exc.severity == "BLOCK":
            raise RunRefused({"resolution": ["A blocking exception cannot be accepted: exclude the employee or fix "
                                             "it upstream."]})
        exc.resolved, exc.resolution, exc.resolution_reason = True, "ACCEPTED", str(reason or "").strip()
        exc.resolved_by, exc.resolved_by_name, exc.resolved_at = _who(user), _name(user), timezone.now()
        exc.save()
        audit(run, A.EXCEPTION_RESOLVED, user, employee=exc.employee, after={"code": exc.code,
                                                                             "resolution": "ACCEPTED"}, reason=reason)
        return run
    if resolution == "EXCLUDED":
        if not can_exclude:
            raise RunRefused({"permission": ["Excluding needs the 'exclude payroll employee' permission."]}, status=403)
        if exc.line is None:
            raise RunRefused({"exception": ["This exception is not about one employee."]})
        why = _reason(reason, "the reason for leaving them out of this run")
        line = exc.line
        line.included, line.exclusion_reason = False, why
        line.excluded_by, line.excluded_by_name = _who(user), _name(user)
        line.save()
        _resolve_open(line, "EXCLUDED", why, user)
        _totals(run)
        audit(run, A.EMPLOYEE_EXCLUDED, user, employee=line.employee, after={"code": exc.code}, reason=why)
        return run
    if resolution == "FIXED_UPSTREAM":
        audit(run, A.EXCEPTION_RESOLVED, user, employee=exc.employee,
              after={"code": exc.code, "resolution": "FIXED_UPSTREAM"}, reason=reason)
        run, _ = compute(run, user=user)
        return run
    raise RunRefused({"resolution": ["resolution is EXCLUDED, FIXED_UPSTREAM or ACCEPTED."]}, status=400)


# ================================================================= approve


def drift(run):
    """§9.2: lines whose inputs moved since compute, by name."""
    lines = list(run.lines.filter(included=True, blocked=False).select_related("employee"))
    ctx = Context(run, [ln.employee for ln in lines])
    moved = []
    for line in lines:
        try:
            inp, _, _ = gather(run, line, line.employee, ctx.book, ctx.calendar, ctx.att[line.employee.pk])
        except NoStructure:
            moved.append(line.employee)
            continue
        from .engine import input_hash

        if input_hash(inp) != line.input_hash:
            moved.append(line.employee)
    return moved


@transaction.atomic
def approve(run, *, user):
    """§6.4."""
    run = _locked(run)
    _need(run, S.COMPUTED)
    if run.created_by_id == getattr(user, "pk", None):
        raise RunRefused({"approver": ["You prepared this run, so you cannot approve it. Preparing and approving are "
                                       "deliberately separate people."]}, status=403)
    blockers = list(blocking(run).select_related("employee"))
    if blockers:
        raise RunRefused({"blockers": [f"{len(blockers)} blocking exception{'' if len(blockers) == 1 else 's'} must be "
                                       "resolved before approval."]}, status=422,
                         detail={"blockers": [{"employee": x.employee.code if x.employee else None,
                                               "code": x.code, "message": x.message} for x in blockers]})
    from django.db.models import Sum

    lines_net = to_decimal(run.lines.filter(included=True).aggregate(n=Sum("net_pay"))["n"] or 0)
    if lines_net != to_decimal(run.total_net):
        raise RunRefused({"totals": [f"Lines total {money(lines_net)}, the run states {money(run.total_net)} — a "
                                     "register that does not reconcile cannot be paid. Recompute."]}, status=422)
    moved = drift(run)
    if moved:
        names = ", ".join(f"{e.name_en} ({e.code})" for e in moved[:8]) + (" and others" if len(moved) > 8 else "")
        raise RunRefused({"drift": [f"Figures moved since the run was computed for {names}: a structure, attendance, "
                                    "tax or payment detail changed. Recompute before approving."]}, status=409,
                         detail={"employees": [e.code for e in moved]})
    run.approved_by, run.approved_by_name, run.approved_at = user, _name(user), timezone.now()
    run.save(update_fields=["approved_by", "approved_by_name", "approved_at", "updated_at"])
    move(run, S.APPROVED, user)
    from timekeepingio.models import AttendancePeriod

    AttendancePeriod.objects.filter(site=run.site, period_month=run.period_start).update(
        payroll_run_ref=run.ref, payroll_processed_on=clock.today())
    audit(run, A.APPROVED, user, after={"net": format(run.total_net, "f"), "included": run.included_count,
                                        "excluded": run.excluded_count})
    event(run, "PayrollApproved", actor=user, totalNet=format(run.total_net, "f"),
          message=f"{run.site.name} payroll for {format_month_year(run.period_start)} approved by {_name(user)}")
    return run


@transaction.atomic
def cancel(run, *, reason, user):
    run = _locked(run)
    _need(run, *PRE_APPROVAL)
    why = _reason(reason, "the reason for cancelling the run")
    run.cancelled_reason = why
    run.save(update_fields=["cancelled_reason", "updated_at"])
    move(run, S.CANCELLED, user, why)
    audit(run, A.CANCELLED, user, reason=why)
    event(run, "PayrollRunCancelled", actor=user, reason=why)
    return run


# ================================================================ disburse


def corporate_account(company, code):
    row = CorporateAccount.objects.filter(company=company, profile_code=code).first()
    return row.account if row else None


@transaction.atomic
def set_corporate_account(company, code, account, *, user):
    p = bankfiles.profile(code)
    if not bankfiles.needs_account(p):
        raise RunRefused({"profile": [f"{p['name']} has no corporate account."]})
    account = str(account or "").strip()
    if len(account) < 4:
        raise RunRefused({"account": ["Give the company's account number for this profile."]})
    row, _ = CorporateAccount.objects.update_or_create(company=company, profile_code=code,
                                                       defaults={"account": account, "set_by": _who(user),
                                                                 "set_by_name": _name(user)})
    PayrollAudit.objects.create(company=company, action=A.ACCOUNT_SET, actor=_who(user), actor_name=_name(user),
                                actor_role=_role(user, company), after_json={"profile": code, "account": account},
                                engine_version=ENGINE_VERSION)
    return row


def payable_lines(run, p):
    return [ln for ln in run.lines.filter(included=True, payment_status__in=["PENDING", "FAILED"])
            .select_related("employee", "employee__payment") if bankfiles.matches(p, ln) and ln.net_pay > 0]


def file_rows(run, p):
    narration = f"Salary {format_month_year(run.period_start)}"
    return [destination_row(ln, ln.employee, narration) for ln in payable_lines(run, p)]


@transaction.atomic
def instruct(run, profile_code, *, idempotency_key, user):
    """§6.5. Replaying the key returns the original instruction, not a
    second file (non-negotiable 8)."""
    if not idempotency_key:
        raise RunRefused({"idempotencyKey": ["idempotencyKey is required."]}, status=400)
    found = PaymentInstruction.objects.filter(company=run.company, idempotency_key=idempotency_key).first()
    if found is not None:
        return found, False
    run = _locked(run)
    _need(run, S.APPROVED, S.DISBURSING, S.PARTIALLY_PAID)
    try:
        p = bankfiles.profile(profile_code)
    except bankfiles.FileRefused as exc:
        raise RunRefused({"profile": [exc.message]}) from None
    account = corporate_account(run.company, p["code"]) if bankfiles.needs_account(p) else ""
    if bankfiles.needs_account(p) and not account:
        raise RunRefused({"account": [f"Set the company's {p['bank']} account before generating a {p['name']} file."]},
                         status=422, detail={"code": "NO_CORPORATE_ACCOUNT", "profile": p["code"]})
    lines = payable_lines(run, p)
    narration = f"Salary {format_month_year(run.period_start)}"
    rows = [destination_row(ln, ln.employee, narration) for ln in lines]
    try:
        out = bankfiles.generate(p, rows, corporate_account=account, payment_date=run.payment_date, run_ref=run.ref)
    except bankfiles.FileRefused as exc:
        raise RunRefused({"file": [exc.message]}, status=422, detail={"issues": exc.issues}) from None
    ins = PaymentInstruction.objects.create(
        company=run.company, run=run, bank_profile_code=p["code"], corporate_account=account or "",
        file_name=out["fileName"], file_hash=out["hash"], content=out["text"], encoding=p["encoding"],
        row_count=out["recordCount"], total_amount=out["controlTotal"], generated_by=user,
        generated_by_name=_name(user), idempotency_key=idempotency_key)
    for ln in lines:
        PaymentInstructionLine.objects.create(instruction=ins, run_line=ln, amount=ln.net_pay)
        ln.payment_status = PayStatusChoices.INSTRUCTED
        ln.save(update_fields=["payment_status", "updated_at"])
    if run.state == S.APPROVED:
        move(run, S.DISBURSING, user)
    audit(run, A.FILE_GENERATED, user, after={"profile": p["code"], "file": out["fileName"], "hash": out["hash"],
                                              "rows": out["recordCount"], "total": format(out["controlTotal"], "f")})
    event(run, "PaymentFileGenerated", actor=user, profile=p["code"], fileHash=out["hash"], rows=out["recordCount"],
          total=format(out["controlTotal"], "f"))
    return ins, True


def _settle(run, user):
    """PAID when every included, payable line is paid (§6.6)."""
    open_lines = run.lines.filter(included=True).exclude(payment_status=PayStatusChoices.PAID).exists()
    any_paid = run.lines.filter(included=True, payment_status=PayStatusChoices.PAID).exists()
    if not open_lines:
        move(run, S.PAID, user)
    elif any_paid and run.state == S.DISBURSING:
        move(run, S.PARTIALLY_PAID, user)


@transaction.atomic
def mark_paid(run, lines, *, user):
    run = _locked(run)
    _need(run, S.DISBURSING, S.PARTIALLY_PAID)
    done = 0
    for ln in lines:
        ln = PayrollRunLine.objects.select_related("employee").get(pk=ln.pk, run=run)
        if ln.payment_status != PayStatusChoices.INSTRUCTED:
            raise RunRefused({"line": [f"{ln.employee.name_en} is {ln.get_payment_status_display().lower()}: only an "
                                       "instructed payment is marked paid."]}, status=409)
        now = timezone.now()
        ln.payment_status, ln.paid_at = PayStatusChoices.PAID, now
        ln.save(update_fields=["payment_status", "paid_at", "updated_at"])
        ln.transfers.filter(status="INSTRUCTED").update(status="PAID", paid_at=now)
        audit(run, A.MARKED_PAID, user, employee=ln.employee, after={"net": format(ln.net_pay, "f")})
        event(run, "PaymentMarkedPaid", actor=user, employee=ln.employee.code, amount=format(ln.net_pay, "f"))
        done += 1
    _settle(run, user)
    return run, done


@transaction.atomic
def mark_failed(run, line, *, reason, user):
    """A failed or returned transfer goes back to the pool: a new instruction
    pays it, never the same one twice (§9.3)."""
    run = _locked(run)
    _need(run, S.DISBURSING, S.PARTIALLY_PAID)
    why = _reason(reason, "what the bank or wallet reported")
    ln = PayrollRunLine.objects.select_related("employee").get(pk=line.pk, run=run)
    if ln.payment_status != PayStatusChoices.INSTRUCTED:
        raise RunRefused({"line": ["Only an instructed payment can fail."]}, status=409)
    ln.payment_status = PayStatusChoices.FAILED
    ln.save(update_fields=["payment_status", "updated_at"])
    ln.transfers.filter(status="INSTRUCTED").update(status="FAILED", failure_reason=why)
    audit(run, A.MARKED_FAILED, user, employee=ln.employee, reason=why)
    return run


@transaction.atomic
def release(run, *, user):
    """§6.7. Releasing closes the period; the withheld tax becomes a deposit
    liability with its own deadline."""
    from employeeio.models import ProcessedPayrollPeriod
    from employeeio.services.withholding import deposit_due
    from rulebookio.book import rule_book

    run = _locked(run)
    _need(run, S.PAID)
    now = timezone.now()
    run.released_at = run.closed_at = now
    run.save(update_fields=["released_at", "closed_at", "updated_at"])
    move(run, S.CLOSED, user)
    ProcessedPayrollPeriod.objects.get_or_create(company=run.company, period=run.period_start,
                                                 defaults={"processed_on": clock.today(), "processed_by": _who(user)})
    try:
        due = deposit_due(run.period_start, rule_book(run.period_end)).isoformat()
    except Exception:  # noqa: BLE001 -- the rule is the tax card's; absent, the ledger derives it
        due = None
    audit(run, A.RELEASED, user, after={"paid": run.included_count, "tax": format(run.total_tax, "f")})
    event(run, "PayslipsReleased", actor=user, totalTax=format(run.total_tax, "f"), depositDue=due,
          message=f"{run.included_count} payslips released for {format_month_year(run.period_start)}. "
                  f"{money(run.total_tax)} withheld tax due to the treasury")
    return run


def instruction_bytes(ins):
    return ins.content.encode("cp1252" if ins.encoding == "Windows-1252" else "utf-8", errors="replace")
