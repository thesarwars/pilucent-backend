"""Soft feature-gating for dashboard cards.

Sensitive cards (payroll, tax, audit/activity, support) are gated by the
company's subscription feature flags. Rather than returning a hard 403 (which
would break the whole dashboard render), cards use this to decide whether to
return a ``restricted`` envelope instead of real values.
"""

from types import SimpleNamespace

from common.django_rest.permissions.company_subscription import HaveSubscription


def company_has_feature(user, feature):
    """Return True if the active company's subscription enables ``feature``.

    ``feature`` is a Subscription boolean flag name such as ``is_payroll`` or
    ``is_audit_log``. A falsy ``feature`` means the card is always available.
    """
    if not feature:
        return True
    if user is None or getattr(user, "is_anonymous", True):
        return False

    checker = HaveSubscription()
    fake_view = SimpleNamespace(required_feature=feature)
    fake_request = SimpleNamespace(user=user)
    return bool(checker._has_subscription(fake_request, fake_view))
