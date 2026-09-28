"""Standard card envelope + shared math helpers for v2 dashboard cards.

Every card returns the same payload shape (spec section 5) so the frontend can
render skeleton/empty/stale/error states uniformly:

    value, comparison_value, trend_direction, trend_percent, chart_series,
    list_items, action_route, last_updated_at, permission_state, data_state,
    error_state
"""

from datetime import datetime, date
from decimal import Decimal, InvalidOperation


# permission_state values
PERMISSION_ALLOWED = "allowed"
PERMISSION_RESTRICTED = "restricted"

# data_state values
STATE_OK = "ok"
STATE_EMPTY = "empty"
STATE_ERROR = "error"


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return value


def compute_trend(current, previous):
    """Return ``(trend_percent, trend_direction)``.

    trend_percent = (current - previous) / abs(previous) * 100.
    When there is no previous value (zero/None), there is no meaningful
    percentage, so direction is ``"new"`` and percent is ``None`` (spec: show
    "New" / "No previous data" instead of an infinite percentage).
    """
    cur = _to_number(current) or 0
    prev = _to_number(previous)

    if prev in (None, 0):
        return None, "new"

    percent = (cur - prev) / abs(prev) * 100
    if percent > 0:
        direction = "up"
    elif percent < 0:
        direction = "down"
    else:
        direction = "flat"
    return round(percent, 2), direction


def _isoformat(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_card(
    card_key,
    *,
    value=None,
    comparison_value=None,
    trend_percent=None,
    trend_direction=None,
    chart_series=None,
    list_items=None,
    action_route=None,
    last_updated_at=None,
    permission_state=PERMISSION_ALLOWED,
    data_state=None,
    extra=None,
    error_state=None,
):
    """Assemble the standard card payload."""
    if data_state is None:
        if error_state is not None:
            data_state = STATE_ERROR
        elif not value and not chart_series and not list_items and not extra:
            data_state = STATE_EMPTY
        else:
            data_state = STATE_OK

    payload = {
        "card": card_key,
        "value": _to_number(value) if not isinstance(value, (dict, list)) else value,
        "comparison_value": _to_number(comparison_value),
        "trend_percent": trend_percent,
        "trend_direction": trend_direction,
        "chart_series": chart_series or [],
        "list_items": list_items or [],
        "action_route": action_route,
        "last_updated_at": _isoformat(last_updated_at),
        "permission_state": permission_state,
        "data_state": data_state,
        "error_state": error_state,
    }
    if extra:
        payload.update(extra)
    return payload


def restricted_card(card_key, action_route=None, message=None):
    """Card payload for a user who lacks the plan/permission for this card."""
    return build_card(
        card_key,
        permission_state=PERMISSION_RESTRICTED,
        data_state=STATE_EMPTY,
        action_route=action_route,
        extra={"message": message or "You do not have access to this card."},
    )


def error_card(card_key, message):
    """Non-blocking error envelope so one failing card never 500s the page."""
    return build_card(
        card_key,
        data_state=STATE_ERROR,
        error_state={"message": message, "retryable": True},
    )
