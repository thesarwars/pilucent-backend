from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from accounts.django_rest.helpers.group_seeds import seed_default_groups


class Command(BaseCommand):
    help = "Idempotently seed the admin/user/employee Django Groups with default permissions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-admin",
            action="store_true",
            help=(
                "Force-reset the `admin` Group to hold every Permission in the "
                "DB, wiping any manual curation. Default is to leave admin "
                "alone after first creation so Django-admin edits survive."
            ),
        )

    def handle(self, *args, **options):
        seed_default_groups(
            Group,
            Permission,
            ContentType,
            stdout=self.stdout,
            reset_admin=options["reset_admin"],
        )
        self.stdout.write(self.style.SUCCESS("Default groups seeded."))
