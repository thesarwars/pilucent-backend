"""Field validation for the BD employee profile (doc §4)."""

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

NID_LENGTHS = (10, 13, 17)
MOBILE_LENGTH = 11
MOBILE_PREFIX = "01"
MIN_REASON_LENGTH = 10


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def nid_valid(value):
    """§4.1: strip non-digits; 10, 13 or 17 digits. A risk, not a block."""
    return len(digits(value)) in NID_LENGTHS


def mobile_valid(value):
    """§4.2: strip non-digits; exactly 11 digits starting 01. Also wallets."""
    number = digits(value)
    return len(number) == MOBILE_LENGTH and number.startswith(MOBILE_PREFIX)


def validate_nid(value):
    if value and not nid_valid(value):
        raise ValidationError(
            f"NID must be 10, 13 or 17 digits; this has {len(digits(value))}."
        )


def validate_mobile(value, what="Mobile number"):
    if value and not mobile_valid(value):
        raise ValidationError(f"{what} must be 11 digits starting 01.")


def validate_pf_percent(value, book):
    """§4.3: within [pfMinPercent, pfMaxPercent] from the rule book. NaN and
    anything unparseable are rejected; the message states the range."""
    low = book.labour.decimal("pfMinPercent")
    high = book.labour.decimal("pfMaxPercent")
    message = f"Provident fund contribution must be between {low}% and {high}%."
    try:
        percent = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(message) from None
    if not percent.is_finite() or not (low <= percent <= high):
        raise ValidationError(message)
    return percent


def validate_reason(text):
    """§4.4: a gated change needs a reason of at least 10 characters, trimmed."""
    reason = str(text or "").strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ValidationError(
            f"A reason of at least {MIN_REASON_LENGTH} characters is required "
            f"({len(reason)} so far)."
        )
    return reason
