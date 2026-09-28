"""Rule-engine lookups: which NexusStateRule is in force for a state on a date."""

from django.db.models import Q

from nexusio.models import NexusStateRule


def _in_force_q(on_date):
    """Rows whose effective window contains ``on_date``."""
    return Q(effective_from__lte=on_date) & (
        Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
    )


def rule_in_force(state_code, on_date):
    """The single rule version in force for ``state_code`` on ``on_date`` (or None)."""
    return (
        NexusStateRule.objects.filter(_in_force_q(on_date), state_code=state_code)
        .order_by("-effective_from")
        .first()
    )


def rules_in_force(on_date):
    """One in-force rule per state as of ``on_date`` → {state_code: NexusStateRule}."""
    result = {}
    # Ordered newest-effective-first within each state, so the first row seen per
    # state is its in-force version.
    for rule in NexusStateRule.objects.filter(_in_force_q(on_date)).order_by(
        "state_code", "-effective_from"
    ):
        result.setdefault(rule.state_code, rule)
    return result
