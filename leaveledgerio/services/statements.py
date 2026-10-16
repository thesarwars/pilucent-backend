"""Quarterly leave statements (the Leave Operations design's statements tab;
the leave register, Form-9): one per worker per quarter, and a record of how
each reached the worker. The statement is easy; evidencing that the worker
received it is what an inspection tests.

Figures come from the ledger through `position()`, so a statement agrees
with the balances tab. A quarter whose attendance months are still open can
be stated only with that acknowledged on the record.
"""

import calendar as pycal
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum

from common import clock

from ..choices import IssueMethodChoices, LeaveAuditActionChoices as A, LedgerReasonChoices as R
from ..models import LeaveRequest, LedgerEntry, Statement, StatementBatch, StatementIssue
from .core import GRID, ZERO, Book, LeaveRefused, actor_name, audit, days_str, ensure_types, position, restriction

STATED = GRID  # earned, casual, sick: the register's leave


def quarter_bounds(quarter):
    """'2026-Q4' -> (2026-10-01, 2026-12-31)."""
    try:
        year, q = str(quarter).upper().split("-Q")
        year, q = int(year), int(q)
        if not 1 <= q <= 4:
            raise ValueError
    except (TypeError, ValueError):
        raise LeaveRefused({"quarter": ["quarter is YYYY-Qn, e.g. 2026-Q4."]}, status=400) from None
    start = date(year, 3 * q - 2, 1)
    end_month = 3 * q
    return start, date(year, end_month, pycal.monthrange(year, end_month)[1])


def quarter_of(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def quarter_label(quarter):
    start, end = quarter_bounds(quarter)
    return f"{start:%b} – {end:%b %Y}"


def _employed(company, start, end):
    from .reads import roster

    return [e for e in roster(company) if (e.doj is None or e.doj <= end)
            and (e.separated_on is None or e.separated_on >= start)]


def readiness(company, quarter):
    """The attendance months in the quarter that are not locked, per site."""
    from employeeio.services.sites import site_of
    from timekeepingio.models import AttendancePeriod

    start, end = quarter_bounds(quarter)
    months = [date(start.year, start.month + i, 1) for i in range(3)]
    sites = {}
    for e in _employed(company, start, end):
        site = site_of(e)
        sites[site.pk] = site
    locked = set(AttendancePeriod.objects.filter(site_id__in=list(sites), status="LOCKED", period_month__in=months)
                 .values_list("site_id", "period_month"))
    unlocked = [f"{site.name} {m:%b %Y}" for site in sites.values() for m in months if (site.pk, m) not in locked]
    return {"quarter": quarter, "label": quarter_label(quarter), "from": start.isoformat(), "to": end.isoformat(),
            "unlocked": unlocked, "ready": not unlocked}


def figures(employee, ltype, start, end, book):
    """One register row: opening, earned, taken, refused, encashed, other
    (forfeited, lapsed, debited or carried over a year change) and closing.
    Opening and closing are the cycle balances either side of the quarter;
    the movements are the live ledger entries inside it."""
    # Read-only: a statement never opens a cycle (and never posts its grant).
    opening = position(employee, ltype, start - timedelta(days=1), book=book, open_cycle=False).balance
    closing = position(employee, ltype, end, book=book, open_cycle=False).balance
    moves = {}
    for row in (LedgerEntry.objects.filter(employee=employee, leave_type=ltype, effective_date__gte=start,
                                           effective_date__lte=end, reversed_by__isnull=True)
                .exclude(reason=R.REVERSAL).values("reason").annotate(s=Sum("days"))):
        moves[row["reason"]] = row["s"] or ZERO
    earned = moves.get(R.ACCRUAL, ZERO) + moves.get(R.CREDIT_EARNED, ZERO) + max(moves.get(R.ADJUSTMENT, ZERO), ZERO)
    taken = -(moves.get(R.TAKEN, ZERO) + moves.get(R.CANCELLED, ZERO))
    encashed = -moves.get(R.ENCASHED, ZERO)
    refused = (LeaveRequest.objects.filter(employee=employee, leave_type=ltype, status="DECLINED",
                                           from_date__gte=start, from_date__lte=end)
               .aggregate(s=Sum("days_consumed"))["s"] or ZERO)
    other = closing - opening - earned + taken + encashed
    return {"type": ltype.code, "name": ltype.name, "nameBn": ltype.name_bn or None,
            "opening": days_str(opening), "earned": days_str(earned), "taken": days_str(taken),
            "refused": days_str(refused), "encashed": days_str(encashed), "other": days_str(other),
            "closing": days_str(closing)}


def generate(company, quarter, *, acknowledge_unlocked=False, user=None):
    """A new version of the quarter's statements. Refused while attendance
    months are open, unless that is acknowledged -- and the acknowledgement
    stays on the batch."""
    start, end = quarter_bounds(quarter)
    if start > clock.today():
        raise LeaveRefused({"quarter": [f"{quarter_label(quarter)} has not begun."]})
    ready = readiness(company, quarter)
    if not ready["ready"] and not acknowledge_unlocked:
        raise LeaveRefused({"quarter": [
            f"{len(ready['unlocked'])} attendance months in this quarter are not locked, so the leave they record "
            "may still change. Acknowledge that to state the quarter anyway."]}, status=409,
            detail={"unlocked": ready["unlocked"]})
    types = ensure_types(company)
    book = Book()
    with transaction.atomic():
        last = (StatementBatch.objects.filter(company=company, quarter=quarter).order_by("-version")
                .values_list("version", flat=True).first())
        batch = StatementBatch.objects.create(
            company=company, quarter=quarter, version=(last or 0) + 1, period_from=start, period_to=end,
            generated_by=user if user is not None and getattr(user, "is_authenticated", False) else None,
            generated_by_name=actor_name(user), unlocked_months=ready["unlocked"])
        made = []
        for e in _employed(company, start, end):
            rows = [figures(e, types[c], start, end, book) for c in STATED
                    if restriction(e, types[c], end, book.rules(end), service=False) is None]
            if rows:
                made.append(Statement(company=company, batch=batch, employee=e, rows=rows))
        Statement.objects.bulk_create(made)
        audit(company, batch, A.STATEMENTS_GENERATED, user, reason="; ".join(ready["unlocked"]),
              after={"quarter": quarter, "version": batch.version, "statements": len(made)})
    return batch


def latest(company, quarter):
    return StatementBatch.objects.filter(company=company, quarter=quarter).order_by("-version").first()


def record_issue(company, quarter, method, *, codes=None, on=None, detail="", user=None):
    """How the statements reached the workers. Every statement of the latest
    version, or the named employees'."""
    if method not in IssueMethodChoices.values:
        raise LeaveRefused({"method": [f"method is one of {', '.join(IssueMethodChoices.values)}."]}, status=400)
    batch = latest(company, quarter)
    if batch is None:
        raise LeaveRefused({"quarter": [f"No statements generated for {quarter_label(quarter)}."]}, status=404)
    on = date.fromisoformat(on) if on else clock.today()
    qs = batch.statements.select_related("employee")
    if codes:
        qs = qs.filter(employee__code__in=codes)
    statements = list(qs)
    with transaction.atomic():
        StatementIssue.objects.bulk_create([
            StatementIssue(company=company, statement=s, method=method, on=on, detail=(detail or "").strip()[:255],
                           recorded_by=user if user is not None and getattr(user, "is_authenticated", False) else None,
                           recorded_by_name=actor_name(user)) for s in statements])
        audit(company, batch, A.STATEMENT_ISSUED, user, after={"method": method, "count": len(statements)})
    return len(statements)


def acknowledge(company, uid, *, on=None, user=None):
    s = Statement.objects.filter(company=company, uid=uid).select_related("batch", "employee").first()
    if s is None:
        raise LeaveRefused({"statement": ["No such statement."]}, status=404)
    if not s.issues.exists():
        raise LeaveRefused({"statement": ["Record how it was issued before the worker's acknowledgement."]}, status=409)
    if s.acknowledged_at:
        raise LeaveRefused({"statement": ["Already acknowledged."]}, status=409)
    s.acknowledged_at = date.fromisoformat(on) if on else clock.today()
    s.acknowledged_by_name = actor_name(user)
    s.save(update_fields=["acknowledged_at", "acknowledged_by_name", "updated_at"])
    audit(s.company, s.batch, A.STATEMENT_ACKNOWLEDGED, user, on_behalf_of=s.employee)
    return s


def statement_out(s):
    issues = list(s.issues.all())
    return {"uid": str(s.uid), "employee": {"code": s.employee.code, "nameEn": s.employee.name_en,
                                            "nameBn": s.employee.name_bn or None},
            "rows": s.rows, "issued": [{"method": i.method, "label": i.get_method_display(), "on": i.on.isoformat(),
                                        "detail": i.detail or None, "by": i.recorded_by_name or None} for i in issues],
            "acknowledgedAt": s.acknowledged_at.isoformat() if s.acknowledged_at else None}


def summary(company, quarter):
    ready = readiness(company, quarter)
    batch = latest(company, quarter)
    if batch is None:
        return {**ready, "batch": None}
    statements = list(batch.statements.select_related("employee").prefetch_related("issues"))
    rows = [statement_out(s) for s in statements]
    issued = [r for r in rows if r["issued"]]
    by_method = {m: sum(1 for r in rows if any(i["method"] == m for i in r["issued"]))
                 for m in IssueMethodChoices.values}
    return {**ready, "batch": {
        "uid": str(batch.uid), "version": batch.version, "generatedAt": batch.created_at.isoformat(),
        "generatedBy": batch.generated_by_name or None, "unlockedAtGeneration": batch.unlocked_months,
        "generated": len(rows), "issued": len(issued), "acknowledged": sum(1 for r in rows if r["acknowledgedAt"]),
        "outstanding": len(rows) - len(issued), "byMethod": by_method,
        "chase": [{"code": r["employee"]["code"], "nameEn": r["employee"]["nameEn"], "why": "No issue method recorded"}
                  for r in rows if not r["issued"]],
        "rows": rows,
    }}


def quarters_around(today=None, back=4):
    today = today or clock.today()
    out, d = [], today
    for _ in range(back + 1):
        q = quarter_of(d)
        out.append({"id": q, "label": quarter_label(q)})
        d = quarter_bounds(q)[0] - timedelta(days=1)
    return out

