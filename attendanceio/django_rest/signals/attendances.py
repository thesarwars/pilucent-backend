from django.db.models.signals import post_save
from django.dispatch import receiver

from ...choices import DailyTimeTrackingKindChoices
from ...models import DailyTimeTracking, DailyTimeTrackingSession


@receiver(post_save, sender=DailyTimeTracking)
def create_attendance_session(sender, instance, created, **kwargs):
    if created:
        ...
        # DailyTimeTrackingSession.objects.create(
        #     daily_time_tracking=instance,
        #     check_in=instance.check_in,
        #     created_by=instance.created_by,
        #     kind=DailyTimeTrackingKindChoices.CREATED,
        #     employee = instance.employee
        # )
