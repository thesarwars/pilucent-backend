from django.db.models.signals import post_save
from django.dispatch import receiver

from payrollio.models import PayrollWorkLocation

from ..helpers.payroll_onboarding import route_work_location_onboarding


@receiver(post_save, sender=PayrollWorkLocation)
def payroll_work_location_post_save(sender, instance, created, **kwargs):
    route_work_location_onboarding(instance, created=created)
