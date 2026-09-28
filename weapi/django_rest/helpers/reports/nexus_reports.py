"""Economic Nexus report builders (Exposure, Approaching-Risk, Threshold-History).

All three read the already-computed nexus data (``NexusStateStatus``,
``NexusStateRule``, ``NexusAgencyRegistration``, ``NexusAlertLog``) — they do not
re-measure sales. Run a recompute first so the rows are current.
"""

from datetime import date

from nexusio.choices import NexusStatusChoices
from nexusio.models import NexusAgencyRegistration, NexusAlertLog, NexusStateStatus
from nexusio.services.rules import rules_in_force

_STATUS_ORDER = {
    "REGISTERED": 0,
    "MET": 1,
    "APPROACHING": 2,
    "NOT_APPROACHING": 3,
    "NOT_APPLICABLE": 4,
}


def _num(value):
    return float(value) if value is not None else None


def _exposure_row(status, rule, reg):
    return {
        "state_code": status.state_code,
        "state_name": rule.state_name if rule else None,
        "window_start": status.window_start.isoformat() if status.window_start else None,
        "window_end": status.window_end.isoformat() if status.window_end else None,
        "sales_amount": _num(status.sales_amount),
        "sales_threshold": _num(rule.sales_threshold) if rule else None,
        "pct_of_sales_threshold": _num(status.pct_of_sales_threshold),
        "txn_count": status.txn_count,
        "txn_threshold": rule.txn_threshold if rule else None,
        "pct_of_txn_threshold": _num(status.pct_of_txn_threshold),
        "status": status.status,
        "threshold_met_date": (
            status.threshold_met_date.isoformat() if status.threshold_met_date else None
        ),
        "registration_status": (
            reg.registration_status if reg else "NOT_STARTED"
        ),
    }


def _rows_for(company):
    rules = rules_in_force(date.today())
    regs = {
        r.state_code: r
        for r in NexusAgencyRegistration.objects.filter(company=company)
    }
    rows = [
        _exposure_row(s, rules.get(s.state_code), regs.get(s.state_code))
        for s in NexusStateStatus.objects.filter(company=company)
    ]
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9), r["state_code"]))
    return rows


def _totals(rows):
    tally = {"met": 0, "approaching": 0, "registered": 0}
    for row in rows:
        if row["status"] == NexusStatusChoices.MET:
            tally["met"] += 1
        elif row["status"] == NexusStatusChoices.APPROACHING:
            tally["approaching"] += 1
        elif row["status"] == NexusStatusChoices.REGISTERED:
            tally["registered"] += 1
    return tally


def nexus_exposure(company, as_of=None):
    """Every tracked state with its window, activity, %s, verdict, registration."""
    as_of = as_of or date.today()
    rows = _rows_for(company)
    return {"as_of": as_of.isoformat(), "rows": rows, "total": _totals(rows)}


def nexus_approaching_risk(company, as_of=None):
    """Only states at/above the warning fraction but not yet met, closest first."""
    as_of = as_of or date.today()
    rows = [
        r for r in _rows_for(company) if r["status"] == NexusStatusChoices.APPROACHING
    ]
    # "Closest first" — a state can approach nexus via the sales OR the transaction
    # test (OR-logic states), so rank by whichever percentage is nearer to 100%.
    rows.sort(
        key=lambda r: max(
            r["pct_of_sales_threshold"] or 0, r["pct_of_txn_threshold"] or 0
        ),
        reverse=True,
    )
    return {"as_of": as_of.isoformat(), "rows": rows, "total": {"count": len(rows)}}


def nexus_threshold_history(company, as_of=None):
    """Audit trail: every approaching/crossing alert raised, most recent first."""
    as_of = as_of or date.today()
    rules = rules_in_force(date.today())
    alerts = NexusAlertLog.objects.filter(company=company).order_by("-triggered_at")
    rows = [
        {
            "state_code": a.state_code,
            "state_name": rules[a.state_code].state_name if a.state_code in rules else None,
            "alert_type": a.alert_type,
            "threshold_pct_at_alert": _num(a.threshold_pct_at_alert),
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            "acknowledged_at": (
                a.acknowledged_at.isoformat() if a.acknowledged_at else None
            ),
        }
        for a in alerts
    ]
    crossed = {a["state_code"] for a in rows if a["alert_type"] == "CROSSED"}
    return {"as_of": as_of.isoformat(), "rows": rows, "total": {"crossed": len(crossed)}}
