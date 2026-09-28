from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.choices import UserStatusChoices

from .choices import EmployeeStatusChoices
from .models import (
    Employee,
    EmployeePaymentProfile,
    EmployeeStatutory,
    EmployeeTaxProfile,
)


@receiver(post_save, sender=Employee)
def create_blank_sub_records(sender, instance, created, **kwargs):
    """Every employee has its one-to-one sub-records from the start, blank.

    A blank record is a truthful state (doc §1.4): the profile reads it and
    reports the gaps, instead of inventing values or borrowing another
    employee's.
    """
    if not created:
        return
    EmployeeStatutory.objects.get_or_create(employee=instance)
    EmployeeTaxProfile.objects.get_or_create(employee=instance)
    EmployeePaymentProfile.objects.get_or_create(employee=instance)


@receiver(post_save, sender=Employee)
def sync_employee_status_to_user(sender, instance, created, **kwargs):
    """Mirror REMOVED / ACTIVE onto the linked login, as the US module did.

    Removing one employment record only disables the user when they have no
    other live employment, so a user employed by two companies keeps access.
    """
    user = instance.user
    if user is None:
        return

    if instance.status == EmployeeStatusChoices.REMOVED:
        still_active_elsewhere = (
            Employee.objects.filter(user=user)
            .exclude(pk=instance.pk)
            .exclude(status=EmployeeStatusChoices.REMOVED)
            .exists()
        )
        if not still_active_elsewhere and user.status != UserStatusChoices.REMOVED:
            user.status = UserStatusChoices.REMOVED
            user.is_active = False
            user.save(update_fields=["status", "is_active"])
    elif (
        instance.status == EmployeeStatusChoices.ACTIVE
        and user.status == UserStatusChoices.REMOVED
    ):
        user.status = UserStatusChoices.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active"])
