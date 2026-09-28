from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from accounts.django_rest.helpers.group_seeds import seed_default_groups

from adminio.django_rest.helpers.role_backfill import backfill_company_roles
from adminio.models import CompanyRole

from companyio.models import Company


class Command(BaseCommand):
    help = (
        "Backfill: ensure every existing Company has the three system CompanyRoles "
        "(admin/user/employee) seeded, mirror Django Group permissions onto them, "
        "and tag legacy `<company.name>_admin` rows as is_system=True / kind=USER."
    )

    def handle(self, *args, **options):
        # Step 1: refresh the source-of-truth Django Groups before mirroring.
        seed_default_groups(Group, Permission, ContentType, stdout=self.stdout)

        # Step 2: backfill per-company CompanyRole rows.
        result = backfill_company_roles(
            Company, CompanyRole, Group, Permission, stdout=self.stdout
        )

        self.stdout.write(self.style.SUCCESS(f"Done: {result}"))
