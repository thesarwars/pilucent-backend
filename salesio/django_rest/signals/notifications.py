from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User

from notificationio.choices import (
    NotificationStatusChoices,
    NotificationKindChoices,
    NotificationModelKindChoices,
)
from notificationio.services.notifications import NotificationService

from ...models import Sale


@receiver(post_save, sender=Sale)
def create_sale_notification(sender, instance, created, **kwargs):
    if created:
        kind = (
            NotificationKindChoices.SALE_CREATED
            if instance.is_invoice == False
            else NotificationKindChoices.INVOICE_CREATED
        )
        # created_by = instance.created_by.name if instance.created_by else "someone"
        created_by = getattr(instance.created_by, "name", "someone")
        NotificationService.create_notification(
            status=NotificationStatusChoices.PUBLISHED,
            model_kind=NotificationModelKindChoices.SALE,
            kind=kind,
            message=f"A new {kind.replace('_CREATED', '')} has been created by {created_by}.",
            users=User.objects.filter(
                id__in=instance.company.companyuser_set.values_list(
                    "user_id", flat=True
                )
            ),
            object=instance,
        )


# @receiver(post_save, sender=SaleReceipt)
# def create_sale_receipt_notification(sender, instance, created, **kwargs):
#     if created:
#         created_by = instance.created_by.name if instance.created_by else "someone"
#         NotificationService.create_notification(
#             status=NotificationStatusChoices.PUBLISHED,
#             model_kind=NotificationModelKindChoices.SALE_RECEIPT,
#             kind=NotificationKindChoices.SALE_RECEIPT_CREATED,
#             message=f"A new SALE receipt has been created by {created_by}.",
#             users=User.objects.filter(
#                 id__in=instance.company.companyuser_set.values_list(
#                     "user_id", flat=True
#                 )
#             ),
#             object=instance,
#         )
