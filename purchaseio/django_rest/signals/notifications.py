from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User

from notificationio.choices import (
    NotificationStatusChoices,
    NotificationKindChoices,
    NotificationModelKindChoices,
)
from notificationio.services.notifications import NotificationService

from ...models import Purchase


@receiver(post_save, sender=Purchase)
def create_purchase_notification(sender, instance, created, **kwargs):
    if created:
        kind = (
            NotificationKindChoices.PURCHASE_CREATED
            if instance.is_bill == False
            else NotificationKindChoices.BILL_CREATED
        )
        created_by = getattr(instance.created_by, "name", "someone")
        NotificationService.create_notification(
            status=NotificationStatusChoices.PUBLISHED,
            model_kind=NotificationModelKindChoices.PURCHASE,
            kind=kind,
            message=f"A new {kind.replace('_CREATED', '')} has been created by {created_by}.",
            users=User.objects.filter(
                id__in=instance.company.companyuser_set.values_list(
                    "user_id", flat=True
                )
            ),
            object=instance,
        )
