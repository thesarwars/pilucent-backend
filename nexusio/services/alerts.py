"""Nexus alert emission — log once per episode, deliver a notification once.

The ``NexusAlertLog`` unique constraint (company, state, type, episode) is the
de-dup guarantee: ``get_or_create`` only delivers a notification the first time a
given episode's alert is logged, so recompute can run any number of times (nightly,
on-demand, re-delivery) without spamming.
"""

import uuid

from nexusio.choices import NexusAlertTypeChoices
from nexusio.models import NexusAlertLog

from notificationio.choices import (
    NotificationKindChoices,
    NotificationModelKindChoices,
    NotificationStatusChoices,
)
from notificationio.services.notifications import NotificationService

_KIND_BY_ALERT = {
    NexusAlertTypeChoices.APPROACHING: NotificationKindChoices.NEXUS_THRESHOLD_APPROACHING,
    NexusAlertTypeChoices.CROSSED: NotificationKindChoices.NEXUS_THRESHOLD_CROSSED,
}


def new_episode_key():
    return uuid.uuid4().hex


def _company_users(company):
    from accounts.models import User

    return User.objects.filter(
        id__in=company.companyuser_set.values_list("user_id", flat=True)
    )


def emit_alert(company, state_code, state_name, alert_type, pct, episode_key):
    """Record the alert (once per episode) and, if newly recorded, notify users.

    Returns True when a new alert was logged + delivered, False if it already
    existed for this episode (idempotent).
    """
    _, created = NexusAlertLog.objects.get_or_create(
        company=company,
        state_code=state_code,
        alert_type=alert_type,
        episode_key=episode_key,
        defaults={"threshold_pct_at_alert": pct},
    )
    if not created:
        return False

    verb = "approaching" if alert_type == NexusAlertTypeChoices.APPROACHING else "crossed"
    message = f"{state_name or state_code}: sales-tax threshold {verb}."[:100]
    NotificationService.create_notification(
        status=NotificationStatusChoices.PUBLISHED,
        model_kind=NotificationModelKindChoices.NEXUS,
        kind=_KIND_BY_ALERT[alert_type],
        message=message,
        is_company=True,
        users=_company_users(company),
    )
    return True
