"""What the screens read. Every figure is the stored document's."""

from common.money import money_str
from common.words import format_month_year
from payrunio.choices import FIXED
from payrunio.models import PayrollRun

from ..choices import LIVE_ISSUED, LOCKED, OPEN
from ..models import PayslipDocument, WagesRegister
from . import build as B


def _when(v):
    return v.isoformat() if v else None


def finding_out(f):
    return {"uid": str(f.uid), "severity": f.severity, "code": f.code, "message": f.message, "messageBn": f.message_bn,
            "citation": f.citation, "consequence": f.consequence, "resolved": f.resolved, "resolution": f.resolution,
            "resolvedAt": _when(f.resolved_at)}


def row_out(d):
    live = [f for f in d.findings.all() if not f.resolved]
    return {"uid": str(d.uid), "documentNo": d.document_no, "state": d.state, "code": d.employee.code,
            "nameEn": d.employee.name_en, "nameBn": d.employee.name_bn or "", "netPay": money_str(d.net_pay),
            "blocks": sum(f.severity == B.BLOCK for f in live), "warnings": sum(f.severity == B.WARN for f in live)}


def run_brief(run):
    return {"uid": str(run.uid), "ref": run.ref, "period": run.period, "periodStart": run.period_start.isoformat(),
            "siteName": run.site.name, "siteNameBn": run.site.name_bn or "", "state": run.state,
            "runType": run.run_type, "label": format_month_year(run.period_start),
            "labelBn": format_month_year(run.period_start, "bn")}


def roster(company, *, run_uid=None, user=None, read_all=False):
    """§14 defect 6: the periods are the runs that exist, not a fixed list. A
    person without read-all sees only their own issued slips."""
    runs = PayrollRun.objects.filter(company=company, state__in=FIXED).select_related("site")
    docs = PayslipDocument.objects.filter(company=company).select_related("employee").prefetch_related("findings")
    if not read_all:
        docs = docs.filter(employee__user=user, state__in=LOCKED)
        runs = runs.filter(uid__in=docs.values_list("run__uid", flat=True))
    runs = list(runs.order_by("-period_start", "site__name", "-created_at"))
    picked = next((r for r in runs if str(r.uid) == str(run_uid)), runs[0] if runs else None)
    rows = [row_out(d) for d in docs.filter(run=picked).order_by("employee__code")] if picked else []
    return {"periods": [run_brief(r) for r in runs], "run": run_brief(picked) if picked else None, "rows": rows,
            "summary": {"generated": len(rows), "blocked": sum(r["state"] == "BLOCKED" for r in rows),
                        "issuable": sum(r["state"] == "ISSUABLE" for r in rows),
                        "issued": sum(r["state"] in LOCKED for r in rows),
                        "lines": picked.lines.filter(included=True).count() if picked else 0},
            "sites": len({r.site_id for r in runs})}


def document_out(d):
    return {
        **row_out(d),
        "period": d.period, "periodLabel": format_month_year(d.run.period_start),
        "periodLabelBn": format_month_year(d.run.period_start, "bn"), "language": d.language,
        "gross": money_str(d.gross), "totalDeductions": money_str(d.total_deductions), "netInWords": d.net_in_words,
        "netInWordsBn": d.net_in_words_bn, "wagesBase": money_str(d.wages_base),
        "nonCashEarnings": money_str(d.non_cash_earnings), "pfBase": money_str(d.pf_base),
        "deductionCeiling": money_str(d.deduction_ceiling) if d.deduction_ceiling is not None else None,
        "ceilingBasis": d.ceiling_basis, "earnings": d.earnings_json, "deductions": d.deductions_json,
        "facts": d.facts_json, "derivation": d.derivation_json, "employer": d.employer_json,
        "findings": [finding_out(f) for f in d.findings.order_by("created_at", "id")],
        "deliveries": [{"channel": x.channel, "destination": x.destination, "deliveredAt": _when(x.delivered_at)}
                       for x in d.deliveries.order_by("delivered_at")],
        "ruleSet": d.rule_set.version, "taxCard": d.tax_card.version, "engineVersion": d.engine_version,
        "documentHash": d.document_hash, "hashVerified": d.document_hash == B.document_hash(d) if d.document_hash else None,
        "issuedAt": _when(d.issued_at), "retentionUntil": _when(d.retention_until),
        "supersededBy": d.superseded_by.document_no if d.superseded_by_id else None,
        "runUid": str(d.run.uid),
    }


def _portion(d, *codes):
    return sum((B.amount(x["amount"]) for x in d.deductions_json if x["code"] in codes), B.ZERO)


def register_out(run):
    """§6.6. Written from issued slips; before release it is a preview of the
    drafts, and says so."""
    reg = WagesRegister.objects.filter(run=run).first()
    states = LOCKED if reg else OPEN
    docs = list(PayslipDocument.objects.filter(run=run, state__in=states).select_related("employee")
                .order_by("employee__code"))
    live = [d for d in docs if d.state in LIVE_ISSUED or not reg]
    gross, deducted, net = (reg.total_gross, reg.total_deductions, reg.total_net) if reg else (
        sum((d.gross for d in live), B.ZERO), sum((d.total_deductions for d in live), B.ZERO),
        sum((d.net_pay for d in live), B.ZERO))
    return {
        "run": run_brief(run), "issued": reg is not None, "employer": docs[0].employer_json if docs else None,
        "rows": [{"uid": str(d.uid), "documentNo": d.document_no, "state": d.state, "code": d.employee.code,
                  "nameEn": d.employee.name_en, "nameBn": d.employee.name_bn or "",
                  "payableDays": d.facts_json["payableDays"], "otHours": d.facts_json["otHours"],
                  "gross": money_str(d.gross), "tax": money_str(_portion(d, "TAX")), "pf": money_str(_portion(d, "PF")),
                  "other": money_str(_portion(d, "ADVANCE", "LOAN", "OTHER")),
                  "deductions": money_str(d.total_deductions), "net": money_str(d.net_pay)} for d in docs],
        "totals": {"rows": len(live), "gross": money_str(gross), "deductions": money_str(deducted),
                   "net": money_str(net)},
        "register": {"hash": reg.register_hash, "generatedAt": _when(reg.generated_at),
                     "retentionUntil": reg.retention_until.isoformat()} if reg else None,
        # Proof the documents and the run are one computation.
        "reconciled": {"ok": net == run.total_net and len(live) == run.included_count, "runNet": money_str(run.total_net),
                       "runRows": run.included_count},
    }
