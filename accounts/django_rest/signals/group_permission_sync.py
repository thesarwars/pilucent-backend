"""Mirror system Django Group permission edits onto matching CompanyRoles.

When a developer edits the `admin`, `user`, or `employee` Group in Django
admin, the `is_system=True` CompanyRoles of the same name across every
company stay in sync automatically. Without this fan-out, the live
companies drift from the spec until the next `backfill_company_roles` run.
"""

from django.contrib.auth.models import Group
from django.db.models.signals import m2m_changed

from accounts.django_rest.helpers.group_seeds import SYSTEM_GROUP_NAMES


_RELEVANT_ACTIONS = frozenset({"post_add", "post_remove", "post_clear"})


def handle_group_permissions_changed(
    sender, instance, action, reverse, pk_set, **kwargs
):
    if action not in _RELEVANT_ACTIONS:
        return
    # Only the forward direction (group.permissions.* on a Group instance) is
    # used by the Django admin editor. Reverse calls (Permission.group_set.*)
    # aren't a path we need to support today.
    if reverse or not isinstance(instance, Group):
        return
    if instance.name not in SYSTEM_GROUP_NAMES:
        return

    # Lazy import: adminio depends on accounts at app-ready time.
    from adminio.models import CompanyRole

    new_perms = list(instance.permissions.all())
    roles = CompanyRole.objects.filter(is_system=True, name=instance.name)
    for role in roles.iterator():
        role.permission.set(new_perms)


def connect():
    m2m_changed.connect(
        handle_group_permissions_changed,
        sender=Group.permissions.through,
        dispatch_uid="accounts.group_permission_sync",
    )
