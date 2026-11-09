"""Seed the data a server needs that `migrate` leaves out. Safe on every deploy.

A fresh install was missing two things, and both failed silently:

* The chart-of-account categories. Without them every new company is created
  with an empty chart and cannot post.
* Most of the `admin` Group. Migrate fills it the first time it runs, before
  most apps' permissions exist, and afterwards leaves it alone so that manual
  curation survives. So admins saw almost nothing in the sidebar.

The admin Group is only reset when it holds none of the core codenames below,
which is the state that first migrate leaves it in. A curated Group holds some
of them and is not touched.
"""

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME

CORE_ADMIN_CODENAMES = ("view_chartofaccount", "view_sale", "view_companyrole")


class Command(BaseCommand):
    help = "Seed chart-of-account categories, and complete the admin Group if a first migrate left it partial."

    def handle(self, *args, **options):
        call_command("create_chart_of_account_category", stdout=self.stdout)

        admin = Group.objects.filter(name=ADMIN_GROUP_NAME).first()
        partial = (
            admin is None
            or not admin.permissions.filter(codename__in=CORE_ADMIN_CODENAMES).exists()
        )
        if partial:
            call_command("seed_groups", reset_admin=True, stdout=self.stdout)
            call_command("backfill_company_roles", stdout=self.stdout)
        else:
            self.stdout.write("Admin group already complete; left as it is.")
