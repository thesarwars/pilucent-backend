"""Recompute a company's nexus status rows from its sales + the rule engine.

Runs the same resolve-window → aggregate → evaluate → derive-status → upsert
sequence for every state. Idempotent: re-running over unchanged data yields the
same rows. ``threshold_met_date`` is stamped once (immutable) — the audit record
of when the obligation first arose.
"""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.utils import timezone

from nexusio.choices import (
    NexusAlertTypeChoices,
    NexusCombinationLogicChoices,
    NexusStatusChoices,
)
from nexusio.models import NexusStateStatus
from nexusio.services.aggregation import aggregate_by_state_month, sum_window
from nexusio.services.alerts import emit_alert, new_episode_key
from nexusio.services.engine import (
    DEFAULT_WARNING_FRACTION,
    derive_status,
    evaluate,
    resolve_windows,
)
from nexusio.services.registration import registered_state_codes
from nexusio.services.rules import rules_in_force

# NUMERIC(8,4) caps the stored percentage; the raw value still drives the verdict.
_MAX_PCT = Decimal("9999.9999")
# A state must fall this far below the warning fraction before its alert episode
# resets (so noise around the boundary doesn't re-fire alerts).
_EPISODE_RESET_BAND = Decimal("0.10")
# Namespace for the per-company Postgres advisory lock that serialises recompute
# (kept clear of other advisory-lock users by shifting the company PK past it).
_ADVISORY_LOCK_NS = 0x4E58  # "NX"


def _advisory_lock_key(company):
    """A stable bigint key for ``pg_advisory_lock`` unique to this company."""
    return (_ADVISORY_LOCK_NS << 32) | (company.id & 0xFFFFFFFF)


def _quantize(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.0001"))


def _quantize_pct(value):
    return min(_quantize(value), _MAX_PCT)


def _warning_fraction(company):
    """The company's approaching-warning fraction (settings override, else default)."""
    from nexusio.models import NexusSettings

    settings = NexusSettings.objects.filter(company=company).first()
    return settings.warning_fraction if settings else DEFAULT_WARNING_FRACTION


def _prefer(candidate, current):
    """A met window beats an unmet one; among equals, the higher sales % wins."""
    if candidate["met"] != current["met"]:
        return candidate["met"]
    return candidate["pct_sales"] > current["pct_sales"]


def _evaluate_state(rule, state_buckets, today):
    """Evaluate each measurement window; return the governing (ev, agg, window).

    For CURRENT_OR_PREVIOUS_YEAR this evaluates the prior year and the current
    year separately and picks the crossing year (or the closest), so nexus is met
    when EITHER year crosses — never on the two years summed together.
    """
    best = None
    for window_start, window_end in resolve_windows(rule.measurement_period_type, today):
        agg = sum_window(state_buckets, window_start, window_end)
        ev = evaluate(agg, rule)
        if best is None or _prefer(ev, best[0]):
            best = (ev, agg, (window_start, window_end))
    return best


def _upsert(company, state_code, defaults):
    status, created = NexusStateStatus.objects.get_or_create(
        company=company, state_code=state_code, defaults=defaults
    )
    if created:
        return status
    # The met-date is immutable: once a state first crossed, keep that date
    # regardless of later evaluations (even if it dips below and re-crosses).
    if status.threshold_met_date:
        defaults["threshold_met_date"] = status.threshold_met_date
    for field, value in defaults.items():
        setattr(status, field, value)
    status.save()
    return status


def recompute_company(company, today=None):
    """Recompute every state's status for ``company``; returns run metadata.

    Serialised per company with a Postgres advisory lock so two overlapping
    recomputes (nightly cron vs. an on-demand ``/recalculate``) can't each mint a
    different episode key for the same fresh crossing and fire duplicate alerts.
    On non-Postgres backends (sqlite tests) the lock is a no-op.
    """
    is_postgres = connection.vendor == "postgresql"
    if not is_postgres:
        return _recompute_company(company, today)

    key = _advisory_lock_key(company)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [key])
    try:
        return _recompute_company(company, today)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


def _recompute_company(company, today=None):
    """Recompute every state's status for ``company``; returns run metadata."""
    today = today or date.today()
    now = timezone.now()
    rules = rules_in_force(today)
    buckets, unattributed = aggregate_by_state_month(company)
    registered = registered_state_codes(company)
    warning_fraction = _warning_fraction(company)

    for state_code, rule in rules.items():
        if rule.combination_logic == NexusCombinationLogicChoices.NONE:
            _upsert(
                company,
                state_code,
                {
                    "window_start": None,
                    "window_end": None,
                    "sales_amount": 0,
                    "taxable_sales_amount": 0,
                    "txn_count": 0,
                    "pct_of_sales_threshold": None,
                    "pct_of_txn_threshold": None,
                    "threshold_met": False,
                    "status": NexusStatusChoices.NOT_APPLICABLE,
                    "threshold_met_date": None,
                    "last_evaluated_at": now,
                },
            )
            continue

        prev = NexusStateStatus.objects.filter(
            company=company, state_code=state_code
        ).first()
        prev_status = prev.status if prev else NexusStatusChoices.NOT_APPROACHING
        prev_episode = prev.episode_key if prev else None

        ev, agg, (window_start, window_end) = _evaluate_state(
            rule, buckets.get(state_code, {}), today
        )
        status = derive_status(
            ev,
            rule,
            registered=state_code in registered,
            warning_fraction=warning_fraction,
        )

        # Episode management + transition detection (spec §12.5 / tech guide §10.1).
        # Key CROSSED on the *status* entering MET, not on threshold_met alone: a
        # state can cross while REGISTERED (alert suppressed), then become an
        # actionable MET obligation when the registration is later removed — that
        # transition must still alert even though threshold_met was already True.
        newly_met = (
            status == NexusStatusChoices.MET and prev_status != NexusStatusChoices.MET
        )
        newly_approaching = (
            status == NexusStatusChoices.APPROACHING
            and prev_status == NexusStatusChoices.NOT_APPROACHING
        )
        episode_key = prev_episode
        if newly_met or newly_approaching:
            episode_key = prev_episode or new_episode_key()
        elif status == NexusStatusChoices.NOT_APPROACHING and ev["pct_sales"] < (
            warning_fraction - _EPISODE_RESET_BAND
        ):
            episode_key = None  # genuine fall-away resets the episode

        pct = _quantize_pct(ev["pct_sales"])
        _upsert(
            company,
            state_code,
            {
                "window_start": window_start,
                "window_end": window_end,
                "sales_amount": ev["sales_basis"],
                "taxable_sales_amount": _quantize(agg["taxable"]),
                "txn_count": ev["txn_count"],
                "pct_of_sales_threshold": pct,
                "pct_of_txn_threshold": (
                    _quantize_pct(ev["pct_txn"]) if ev["pct_txn"] is not None else None
                ),
                "threshold_met": ev["met"],
                "status": status,
                "episode_key": episode_key,
                # First run to observe met stamps the date; _upsert keeps it immutable.
                "threshold_met_date": today if ev["met"] else None,
                "last_evaluated_at": now,
            },
        )

        # Alerts only for actionable, un-registered states (once per episode).
        # newly_met already implies status == MET (i.e. un-registered + over threshold).
        if newly_met and episode_key:
            emit_alert(
                company, state_code, rule.state_name,
                NexusAlertTypeChoices.CROSSED, pct, episode_key,
            )
        elif newly_approaching and episode_key:
            emit_alert(
                company, state_code, rule.state_name,
                NexusAlertTypeChoices.APPROACHING, pct, episode_key,
            )

    return {"unattributed": unattributed, "evaluated_states": len(rules)}
