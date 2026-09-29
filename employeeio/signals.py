from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from accounts.choices import UserStatusChoices
from accounts.models import User

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


@receiver(pre_delete, sender=User)
def clear_access_when_the_login_goes(sender, instance, **kwargs):
    """`Employee.user` is SET_NULL: the employee outlives a deleted login. Its
    access flags belonged to that login, so they go with it -- otherwise a
    grant would survive as a stale True and pass to whoever is linked next."""
    Employee.objects.filter(user=instance).update(is_access_enabled=False, is_joined=False)
