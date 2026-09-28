from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from accounts.django_rest.helpers.group_seeds import seed_default_groups


def handle_post_migrate(sender, **kwargs):
    """Re-seed admin/user/employee groups after every migrate.

    Fires for every app's post_migrate so that permissions added by later-migrating
    apps end up attached. Idempotent — safe to run repeatedly.
    """
    seed_default_groups(Group, Permission, ContentType)
