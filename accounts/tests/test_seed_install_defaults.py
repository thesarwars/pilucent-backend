from io import StringIO

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase

from categoryio.models import Category


def run():
    call_command("seed_install_defaults", stdout=StringIO())


class SeedInstallDefaultsTests(TestCase):
    def setUp(self):
        self.admin, _ = Group.objects.get_or_create(name="admin")

    def test_completes_an_admin_group_a_first_migrate_left_partial(self):
        self.admin.permissions.set(Permission.objects.filter(codename="view_payroll_run"))
        run()
        self.assertEqual(self.admin.permissions.count(), Permission.objects.count())

    def test_leaves_a_curated_admin_group_alone(self):
        kept = Permission.objects.filter(codename__in=["view_sale", "view_payroll_run"])
        self.admin.permissions.set(kept)
        run()
        self.assertEqual(set(self.admin.permissions.all()), set(kept))

    def test_categories_are_seeded_and_a_rerun_adds_none(self):
        run()
        count = Category.objects.count()
        self.assertGreater(count, 0)
        run()
        self.assertEqual(Category.objects.count(), count)
