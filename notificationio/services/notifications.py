from ..models import Notification

from notificationio.choices import NotificationModelKindChoices

# Which Notification FK column an object links to, per model_kind. A model_kind
# with no entry here (e.g. NEXUS, which has no per-object FK) simply links no
# object — previously ``.get()`` returned None and ``payload[None] = object``
# raised ``TypeError: keywords must be strings``.
_FK_FIELD_BY_MODEL_KIND = {
    NotificationModelKindChoices.PURCHASE: "purchase",
    NotificationModelKindChoices.PURCHASE_PAYMENT: "purchase_payment",
    NotificationModelKindChoices.SALE: "sale",
    NotificationModelKindChoices.SALE_PAYMENT_RECEIVE: "sale_payment_receive",
    NotificationModelKindChoices.INBOX: "inbox",
    NotificationModelKindChoices.STOCK_ALERT: "stock_alert",
}


class NotificationService:

    def __init__(self):
        return ...

    def create_notification(
        status: str,
        model_kind: str,
        kind: str,
        message: str = "",
        is_company: bool = False,
        users: list = None,
        object=None,
    ):
        if not users:
            return False
        payload = {
            "status": status,
            "model_kind": model_kind,
            "kind": kind,
            "message": message,
            "is_company": is_company,
        }
        fk_field = _FK_FIELD_BY_MODEL_KIND.get(model_kind)
        if fk_field and object is not None:
            payload[fk_field] = object
        return bool(
            Notification.objects.bulk_create(
                [Notification(**payload, user=user) for user in users]
            )
        )
