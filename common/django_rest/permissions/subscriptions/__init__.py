from .v1 import HaveSubscriptionV1
from .v2 import HaveSubscriptionV2

# Phase 1: entitlement engine is the default gate; V1 kept for rollback.
HaveSubscription = HaveSubscriptionV2

__all__ = ["HaveSubscription", "HaveSubscriptionV1", "HaveSubscriptionV2"]
