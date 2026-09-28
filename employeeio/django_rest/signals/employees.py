from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.choices import UserStatusChoices

from employeeio.choices import EmployeeStatusChoices
from employeeio.models import Employee


@receiver(post_save, sender=Employee)
def create_private_employee_salary(sender, instance, created, **kwargs):
    if created:
        # Hook reserved for future auto-creation of EmployeeSalary / EmployeeBankingInformation.
        ...


@receiver(post_save, sender=Employee)
def sync_employee_status_to_user(sender, instance, created, **kwargs):
    """Mirror Employee status transitions onto the linked User.

    - Employee REMOVED -> User REMOVED (only if the user has no other active
      Employee record). Prevents removing one employment record from disabling
      a user who works in multiple companies.
    - Employee ACTIVE  -> User ACTIVE (re-activates a previously removed user
      when an admin reactivates their employment).
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
