"""The document's life (§6): generate, resolve, release, supersede, deliver.

A refusal is `RunRefused`, the run module's: the same errors reach the client
the same way, and the two modules move one run through one close."""

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from common.money import ZERO, money_str
from common.words import format_month_year
from employeeio.services.salary_access import actor_role
from payrunio.choices import FIXED, RunStateChoices, RunTypeChoices
from payrunio.models import PayrollRun, PayrollRunLine
from payrunio.services import ops as R
from payrunio.services.ops import RunRefused

from ..choices import LIVE_ISSUED, LOCKED, OPEN, RETENTION_YEARS, AuditActionChoices as A
from ..choices import ChannelChoices, LanguageChoices, ResolutionChoices
from ..choices import SlipStateChoices as S
from ..models import PayslipAudit, PayslipDelivery, PayslipDocument, PayslipFinding, WagesRegister
from . import build as B

GENERATABLE = tuple(s for s in FIXED if s != RunStateChoices.CLOSED)
CORRECTING_RUNS = (RunTypeChoices.ADJUSTMENT, RunTypeChoices.ARREARS)


def audit(company, action, user, *, doc=None, run=None, employee=None, reason=""):
    actor = user if user is not None and getattr(user, "is_authenticated", False) else None
    PayslipAudit.objects.create(
        company=company, action=action, payslip_uid=doc.uid if doc else None,
        run_uid=(doc.run.uid if doc else run.uid if run else None),
        employee_uid=(doc.employee.uid if doc else employee.uid if employee else None),
        actor_uid=actor.uid if actor else None,
        actor_name=(getattr(actor, "name", "") or getattr(actor, "email", "")) if actor else "",
        actor_role=actor_role(actor, company) or "", reason=reason or "",
        document_hash=doc.document_hash if doc else None, engine_version=doc.engine_version if doc else "")


class Context:
    """What every slip of one run reads, loaded once."""

    def __init__(self, run):
        self.run = run
        self.book = B.PinnedBook(run)
        self.flags = B.Flags(run.company)
        self.employer = employer_of(run)
        self.leave = LeaveLeft(run)
        prefix = f"PS-{run.period}-"
        used = PayslipDocument.objects.filter(company=run.company, period=run.period,
                                              document_no__startswith=prefix).values_list("document_no", flat=True)
        self.prefix = prefix
        self.next_no = max((int(n.rsplit("-", 1)[1]) for n in used), default=0) + 1

    def document_no(self):
        n, self.next_no = self.next_no, self.next_no + 1
        return f"{self.prefix}{n:06d}"


class LeaveLeft:
    """Earned leave left at the period's end, for the facts strip."""

    def __init__(self, run):
        self.run, self.positions = run, None

    def of(self, employee):
        from leaveledgerio.services.core import Book, Positions, days_str, ensure_types

        ltype = ensure_types(self.run.company)["EARNED"]
        pos = Positions(self.run.company, [employee], [ltype], self.run.period_end, Book()).of(employee, ltype)
        return days_str(pos.spendable) if pos.eligible else None


def employer_of(run):
    """§3.1: as at this moment, so a later rename does not rewrite history."""
    c, s = run.company, run.site
    return {"name": c.legal_name or c.name, "address": c.get_legal_address() or c.customer_facing_address or "",
            "establishment": s.name, "establishmentBn": s.name_bn or "", "establishmentCode": s.code}


def _facts(line, employee, ctx, wages, non_cash, perquisites):
    d = line.tax_derivation_json or {}
    limit = ctx.book.tax.get("perquisiteCeilingPerEmployee")
    ytd = B.amount(d["ytdDeducted"]["value"]) if d.get("available") else ZERO
    return {
        "employee": {"code": employee.code, "nameEn": employee.name_en, "nameBn": employee.name_bn or "",
                     "designation": employee.designation.name if employee.designation_id else "",
                     "department": employee.department.name if employee.department_id else "",
                     "grade": employee.grade or ""},
        "calendarDays": line.calendar_days, "payableDays": format(line.payable_days, "f"),
        "lwpDays": format(line.lwp_days, "f"), "otHours": format(line.ot_hours, "f"),
        "prorationFactor": format(line.proration_factor, "f"), "employerPf": money_str(line.pf_employer),
        "paidBy": line.payment_method or "", "paidTo": line.destination_ref or "",
        "earnedLeaveLeft": ctx.leave.of(employee),
        "taxWithheldToDate": money_str(ytd + line.tax_withheld),
        "wagesForS125": money_str(wages), "nonCash": money_str(non_cash),
        "perquisites": money_str(perquisites),
        "perquisiteCeiling": money_str(B.amount(limit.value)) if limit.value is not None else None,
    }


def build(line, ctx, *, uid=None, document_no=None):
    """One unsaved document and its findings. §5.1 is asserted here: a slip
    whose lines do not sum to its net is never written."""
    run, employee = ctx.run, line.employee
    earnings, deductions = line.earnings_json or [], line.deductions_json or []
    gross, total = B._sum(earnings), B._sum(deductions)
    if gross - total != line.net_pay:
        raise RunRefused({"payslip": [
            f"{employee.code}: earnings {money_str(gross)} less deductions {money_str(total)} is not the net "
            f"{money_str(line.net_pay)}. The slip is not issued until it reconciles."]})
    wages, pf_base, perquisites = B.bases(line, ctx.flags)
    notional = B.notional_perquisites(line.tax_derivation_json)
    non_cash = (notional / 12).quantize(B.FOUR)
    rv = ctx.book.labour.get("aggregateDeductionCapPercent")
    ceiling = (wages * B.amount(rv.value) / 100).quantize(B.FOUR) if rv.value is not None else None
    basis = f"{rv.value}% of wages, s.125" if rv.value is not None else None
    findings = B.compliance_for(line, employee, ctx.book, wages_base=wages, annual_perquisites=perquisites + notional,
                                total_deductions=total, ceiling=ceiling)
    en, bn = B.words(line.net_pay)
    doc = PayslipDocument(
        company=run.company, site=run.site, employee=employee, run=run, run_line=line, period=run.period,
        document_no=document_no or ctx.document_no(),
        state=S.BLOCKED if any(f["severity"] == B.BLOCK for f in findings) else S.ISSUABLE,
        gross=gross, total_deductions=total, net_pay=line.net_pay, net_in_words=en, net_in_words_bn=bn,
        wages_base=wages, non_cash_earnings=non_cash, pf_base=pf_base, deduction_ceiling=ceiling, ceiling_basis=basis,
        earnings_json=earnings, deductions_json=deductions, facts_json=_facts(line, employee, ctx, wages, non_cash, perquisites + notional),
        derivation_json=B.derivation(line.tax_derivation_json), employer_json=ctx.employer,
        rule_set=run.rule_set, tax_card=run.tax_card, engine_version=run.engine_version, input_hash=line.input_hash)
    if uid:
        doc.uid = uid
    return doc, findings


def _replace(line, ctx, prior, user, announce):
    """Regeneration replaces a draft wholesale, keeping its number and id. A
    warning someone accepted stays accepted while it still stands."""
    kept = {}
    if prior is not None:
        kept = {f.code: f for f in prior.findings.filter(resolved=True, resolution=ResolutionChoices.ACCEPTED)}
        prior.delete()
    doc, found = build(line, ctx, uid=prior.uid if prior else None, document_no=prior.document_no if prior else None)
    doc.save()
    rows = []
    for f in found:
        was = kept.get(f["code"])
        rows.append(PayslipFinding(company=doc.company, payslip=doc, resolved=was is not None,
                                   resolution=was.resolution if was else None,
                                   resolved_by=was.resolved_by if was else None,
                                   resolved_at=was.resolved_at if was else None, **f))
    PayslipFinding.objects.bulk_create(rows)
    if announce:
        audit(doc.company, A.GENERATED, user, doc=doc)
        if doc.state == S.BLOCKED:
            audit(doc.company, A.BLOCKED, user, doc=doc)
            R.event(ctx.run, "PayslipBlocked", actor=user, employee=doc.employee.code, documentNo=doc.document_no,
                    codes=[f["code"] for f in found if f["severity"] == B.BLOCK])
    return doc


def _rebuild(run, user, *, announce=True):
    """Every included line gets a draft; nothing issued is touched (P14)."""
    live = {d.run_line_id: d for d in PayslipDocument.objects.filter(run=run)
            .select_related("employee", "run").prefetch_related("findings")}
    done = {d.run_line_id for d in PayslipDocument.objects.filter(run=run, state__in=LOCKED)}
    lines = (PayrollRunLine.objects.filter(run=run, included=True)
             .select_related("employee", "employee__designation", "employee__department", "employee__tax_profile",
                             "structure").prefetch_related("structure__components").order_by("employee__code"))
    ctx = Context(run)
    return [_replace(line, ctx, live.get(line.pk), user, announce) for line in lines if line.pk not in done]


def _locked_run(run):
    return PayrollRun.objects.select_for_update().select_related(
        "company", "site", "rule_set", "tax_card").get(pk=run.pk)


def _counts(run):
    docs = PayslipDocument.objects.filter(run=run)
    return {"generated": docs.count(), "blocked": docs.filter(state=S.BLOCKED).count(),
            "issuable": docs.filter(state=S.ISSUABLE).count(), "issued": docs.filter(state__in=LOCKED).count()}


@transaction.atomic
def generate(run, *, user):
    """§6.1. The figures are the approved run's, so nothing before approval has
    a slip. Generation stays open up to the close, or a fixed gate could never
    be re-checked."""
    run = _locked_run(run)
    if run.state not in GENERATABLE:
        raise RunRefused({"run": [f"Run is {run.get_state_display().lower()}: payslips are generated from an "
                                  "approved run, up to its close."]}, status=409)
    if not PayrollRunLine.objects.filter(run=run, included=True).exists():
        raise RunRefused({"run": ["This run has nobody on it."]})
    _rebuild(run, user)
    counts = _counts(run)
    R.event(run, "PayslipsGenerated", actor=user, **counts)
    return counts


def blockers(run):
    docs = (PayslipDocument.objects.filter(run=run, state=S.BLOCKED).select_related("employee")
            .prefetch_related("findings").order_by("employee__code"))
    return [{"employee": d.employee.code, "name": d.employee.name_en, "payslip": str(d.uid),
             "findings": [{"code": f.code, "message": f.message, "citation": f.citation}
                          for f in d.findings.all() if f.severity == B.BLOCK and not f.resolved]}
            for d in docs]


def retention_from(moment):
    return timezone.localtime(moment).date() + relativedelta(years=RETENTION_YEARS)


def _issue(doc, user, now, language=LanguageChoices.EN):
    doc.language = language
    doc.document_hash = B.document_hash(doc)
    doc.issued_by, doc.issued_at, doc.retention_until = user, now, retention_from(now)
    doc.state = S.ISSUED
    doc.save()
    audit(doc.company, A.ISSUED, user, doc=doc)
    return doc


def _write_register(run, user, now):
    docs = list(PayslipDocument.objects.filter(run=run, state__in=LIVE_ISSUED))
    totals = PayslipDocument.objects.filter(run=run, state__in=LIVE_ISSUED).aggregate(
        g=Sum("gross"), d=Sum("total_deductions"), n=Sum("net_pay"))
    reg = WagesRegister.objects.create(
        company=run.company, site=run.site, run=run, period=run.period, row_count=len(docs), total_gross=totals["g"],
        total_deductions=totals["d"], total_net=totals["n"], register_hash=B.register_hash(docs), generated_by=user,
        retention_until=retention_from(now))
    R.event(run, "WagesRegisterGenerated", actor=user, rows=len(docs), hash=reg.register_hash)
    return reg


@transaction.atomic
def release(run, *, user, language=LanguageChoices.EN):
    """§6.3, all or nothing. The drafts are rebuilt first so the gate reads the
    rule book as it stands now, not as it stood when they were generated."""
    run = _locked_run(run)
    if run.state != RunStateChoices.PAID:
        raise RunRefused({"run": [f"Run is {run.get_state_display().lower()}: payslips are released once it is paid."]},
                         status=409)
    _rebuild(run, user, announce=False)
    blocked = blockers(run)
    if blocked:
        names = ", ".join(b["employee"] for b in blocked[:10])
        more = f" and {len(blocked) - 10} more" if len(blocked) > 10 else ""
        raise RunRefused({"payslips": [f"{len(blocked)} payslip(s) are blocked: {names}{more}. Nothing was released."]},
                         status=422, detail={"blocked": blocked})
    now = timezone.now()
    for doc in PayslipDocument.objects.filter(run=run, state=S.ISSUABLE).select_related("employee", "run", "rule_set",
                                                                                        "tax_card"):
        _issue(doc, user, now, language)
    _write_register(run, user, now)
    return R.release(run, user=user)  # closes the run and emits PayslipsReleased with its tax


@transaction.atomic
def resolve(doc, finding_uid, *, resolution, reason, user):
    """§6.2, §5.2."""
    doc = PayslipDocument.objects.select_for_update().select_related("run", "employee").get(pk=doc.pk)
    if doc.state not in OPEN:
        raise RunRefused({"payslip": ["This document is issued: its findings are closed."]}, status=409)
    finding = doc.findings.filter(uid=finding_uid).first()
    if finding is None:
        raise RunRefused({"finding": ["No such finding on this document."]}, status=404)
    if finding.resolved:
        raise RunRefused({"finding": ["This finding is already resolved."]}, status=409)
    reason = R._reason(reason)
    if resolution == ResolutionChoices.ACCEPTED:
        if finding.severity == B.BLOCK:
            raise RunRefused({"resolution": [
                "A BLOCK cannot be accepted. Fix it upstream, or correct the run."]}, status=422)
        finding.resolved, finding.resolution = True, resolution
        finding.resolved_by, finding.resolved_at = user, timezone.now()
        finding.save()
    elif resolution == ResolutionChoices.FIXED_UPSTREAM:
        code = finding.code
        line = PayrollRunLine.objects.select_related("employee", "employee__designation", "employee__department",
                                                     "employee__tax_profile", "structure").get(pk=doc.run_line_id)
        run = _locked_run(doc.run)
        doc = _replace(line, Context(run), doc, user, True)
        if doc.findings.filter(code=code).exists():
            raise RunRefused({"finding": [
                f"{code} still stands after regenerating from the run's stored figures. An approved line does not "
                "change: a wrong rule is corrected in the rule book, a wrong rate through an adjustment run."]},
                status=422)
    else:
        raise RunRefused({"resolution": ["Resolution is FIXED_UPSTREAM or ACCEPTED."]}, status=400)
    audit(doc.company, A.FINDING_RESOLVED, user, doc=doc, reason=f"{finding.code}: {resolution}: {reason}")
    return doc


@transaction.atomic
def supersede(doc, *, new_run, reason, user):
    """§6.4. The new document comes from an adjustment run's line; both stay.
    An adjustment run already released holds the document itself."""
    doc = PayslipDocument.objects.select_for_update().select_related("run", "employee").get(pk=doc.pk)
    reason = R._reason(reason)
    if doc.state not in LIVE_ISSUED:
        raise RunRefused({"payslip": ["Only an issued document can be superseded."]}, status=409)
    run = _locked_run(new_run)
    if run.run_type not in CORRECTING_RUNS:
        raise RunRefused({"newRunId": ["A correction comes from an adjustment or arrears run."]})
    if run.state not in FIXED:
        raise RunRefused({"newRunId": ["The adjustment run is not approved yet."]}, status=409)
    line = (PayrollRunLine.objects.filter(run=run, employee=doc.employee, included=True)
            .select_related("employee", "employee__designation", "employee__department", "employee__tax_profile",
                            "structure").first())
    if line is None:
        raise RunRefused({"newRunId": [f"{doc.employee.code} is not on that run."]})
    new = PayslipDocument.objects.exclude(state=S.SUPERSEDED).filter(run_line=line).first()
    if new is None or new.state not in LIVE_ISSUED:
        new = _replace(line, Context(run), new, user, False)
        if new.state == S.BLOCKED:
            raise RunRefused({"payslips": ["The correction is itself blocked. Nothing was superseded."]}, status=422,
                             detail={"blocked": blockers(run)})
        new = PayslipDocument.objects.select_related("employee", "run", "rule_set", "tax_card").get(pk=new.pk)
        _issue(new, user, timezone.now(), doc.language)
    doc.state, doc.superseded_by = S.SUPERSEDED, new
    doc.save(update_fields=["state", "superseded_by", "updated_at"])
    audit(doc.company, A.SUPERSEDED, user, doc=doc, reason=reason)
    R.event(doc.run, "PayslipSuperseded", actor=user, documentNo=doc.document_no, supersededBy=new.document_no,
            reason=reason)
    return new


def _mask(text):
    text = str(text or "").strip()
    if not text:
        return None
    if "@" in text:
        name, _, host = text.partition("@")
        return f"{name[:1]}***@{host}"
    return f"***{text[-3:]}"


@transaction.atomic
def deliver(doc, *, channel, destination, user):
    """§3.5. PRINTED and HANDED are how most of a factory floor gets its slip."""
    if channel not in ChannelChoices.values:
        raise RunRefused({"channel": [f"Channel is one of {', '.join(ChannelChoices.values)}."]}, status=400)
    doc = PayslipDocument.objects.select_for_update().select_related("run", "employee").get(pk=doc.pk)
    if doc.state not in LIVE_ISSUED:
        raise RunRefused({"payslip": ["Only an issued document can be delivered."]}, status=409)
    PayslipDelivery.objects.create(company=doc.company, payslip=doc, channel=channel, destination=_mask(destination),
                                   delivered_by=user)
    if doc.state == S.ISSUED:
        doc.state = S.DELIVERED
        doc.save(update_fields=["state", "updated_at"])
    audit(doc.company, A.DELIVERED, user, doc=doc, reason=channel)
    R.event(doc.run, "PayslipDelivered", actor=user, documentNo=doc.document_no, channel=channel)
    return doc


def month_label(run, lang="en"):
    return format_month_year(run.period_start, lang)

