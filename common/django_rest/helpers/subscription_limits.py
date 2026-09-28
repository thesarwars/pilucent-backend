from rest_framework.exceptions import ValidationError

from subscriptionio.services.limit_enforcement_service import LimitEnforcementService


def enforce_subscription_create_limit(company, metric_code: str):
    """Raise DRF ValidationError when HARD_BLOCK limits would be exceeded."""
    result = LimitEnforcementService.check_create_allowed(company, metric_code)
    if not result.allowed:
        raise ValidationError(
            {
                "message": result.message,
                "upgrade_metadata": result.upgrade_metadata,
                "denied_by": "subscription_limit",
            }
        )
    return result
