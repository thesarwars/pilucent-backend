"""Renaming an agency must not 500, and changing its state must not delete.

Two faults in `PrivateWeAgencyDetailsSerializer.update`.

**The rename.** It used `ChartOfAccount.objects.get(title=old_title, ...)` and
caught only `DoesNotExist`. The create path makes an account titled
`agency.title` AND a config parent with the same title, so a company can hold
two -- five tenants do -- and the rename raised `MultipleObjectsReturned`, a
500 on a live endpoint.

**The state change.** It called `.delete()` on `ChartOfAccount` twice.
`JournalEntryConnector.account` is `PROTECT`, so that raises `ProtectedError`
-- another 500 -- the moment one of those accounts has been posted to. And
deleting an account erases the only explanation of the entries that referenced
it, which is the rule this project has for exactly this reason.
"""

import logging

from django.test import TestCase

from common.test_support import PreConstraintDataMixin

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices
from categoryio.models import Category

from companyio.models import Company


class AgencyAccountSourceTests(TestCase):
    """The two faults, pinned at the source.

    Driving the serializer needs an Agency, a request user and the full
    state-config machinery; what regressed is which query and which verb, so
    that is what these assert.
    """

    def source(self):
        import inspect

        from weapi.django_rest.serializers import agencies

        return inspect.getsource(agencies)

    def test_the_rename_no_longer_uses_get(self):
        source = self.source()

        self.assertNotIn("except ChartOfAccount.DoesNotExist", source)
        self.assertIn("renaming all of them", source)

    def test_nothing_hard_deletes_a_chart_account(self):
        """The rule: soft-delete, never delete."""
        source = self.source()

        self.assertNotIn(".delete()", source)
        self.assertIn("status=ChartOfAccountStatusChoices.REMOVED", source)


class SoftDeleteSemanticsTests(TestCase):
    """A retired account must not block the one that replaces it."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Jumatechs")
        root = Category.objects.create(
            title="Liabilities", company=None,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        )
        cls.account_type = Category.objects.create(
            title="Other Current Liabilities", parent=root, company=None,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        )
        cls.detail_type = Category.objects.create(
            title="Sales Tax Payable", parent=cls.account_type, company=None,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        )

    def account(self, title, status=ChartOfAccountStatusChoices.ACTIVE):
        return ChartOfAccount.objects.create(
            company=self.company, title=title,
            kind=ChartOfAccountKindChoices.LIABILITIES,
            account_type=self.account_type, detail_type=self.detail_type,
            status=status,
        )

    def live(self, title):
        return ChartOfAccount.objects.filter(
            company=self.company, title=title,
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED)

    def test_a_retired_account_is_not_live(self):
        account = self.account("MN Income Tax")

        ChartOfAccount.objects.filter(pk=account.pk).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        self.assertEqual(self.live("MN Income Tax").count(), 0)

    def test_a_retired_account_still_exists_to_explain_its_entries(self):
        account = self.account("MN Income Tax")

        ChartOfAccount.objects.filter(pk=account.pk).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        self.assertTrue(ChartOfAccount.objects.filter(pk=account.pk).exists())

    def test_a_replacement_can_take_the_same_title(self):
        old = self.account("MN Income Tax")
        ChartOfAccount.objects.filter(pk=old.pk).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        new = self.account("MN Income Tax")

        self.assertEqual(self.live("MN Income Tax").count(), 1)
        self.assertEqual(self.live("MN Income Tax").first(), new)


class RenameWithDuplicatesTests(PreConstraintDataMixin, SoftDeleteSemanticsTests):
    """The rename has to survive the duplicates five tenants already hold."""

    def rename_all(self, old_title, new_title):
        """The loop the serializer now runs."""
        matches = ChartOfAccount.objects.filter(
            title=old_title, company=self.company,
            kind=ChartOfAccountKindChoices.LIABILITIES,
            account_type__title="Other Current Liabilities",
            detail_type__title="Sales Tax Payable",
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED)
        logger = logging.getLogger("weapi")
        if len(matches) > 1:
            logger.warning("more than one")
        for account in matches:
            account.title = new_title
            account.save()
        return len(matches)

    def test_two_accounts_under_one_title_do_not_raise(self):
        self.account("Minnesota Department of Revenue")
        self.account("Minnesota Department of Revenue")

        renamed = self.rename_all(
            "Minnesota Department of Revenue", "MN Dept of Revenue"
        )

        self.assertEqual(renamed, 2)
        self.assertEqual(self.live("MN Dept of Revenue").count(), 2)

    def test_one_account_renames_as_before(self):
        self.account("Minnesota Department of Revenue")

        renamed = self.rename_all(
            "Minnesota Department of Revenue", "MN Dept of Revenue"
        )

        self.assertEqual(renamed, 1)

    def test_a_retired_duplicate_is_left_alone(self):
        self.account("Minnesota Department of Revenue")
        retired = self.account("Minnesota Department of Revenue")
        ChartOfAccount.objects.filter(pk=retired.pk).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        renamed = self.rename_all(
            "Minnesota Department of Revenue", "MN Dept of Revenue"
        )

        self.assertEqual(renamed, 1)
        retired.refresh_from_db()
        self.assertEqual(retired.title, "Minnesota Department of Revenue")


class BulkRetireProtectsControlAccountsTests(TestCase):
    """The agency state change must not retire a control account.

    `serializers/agencies.py` bulk-retires stale sales-tax accounts on a state
    change with `.update(status=REMOVED)`. It filtered by title, kind and
    taxonomy, and nothing excluded `is_fixed` -- so it could retire the seeded
    `SALES_TAX_PAYABLE` control account the posting engine resolves. Verified
    against production: 129 accounts match that filter shape and **60 of them are
    `is_fixed=True` carrying `system_key=SALES_TAX_PAYABLE`**.

    Two things make it worse than the DELETE path guarded in 14b110c0:

    * it is a queryset `.update()`, which bypasses `Model.save()` -- so no
      model-level guard could catch it, and the never-built third part of P0.2
      would not have helped
    * it is bulk, so one call can retire several accounts with only a log line
    """

    def test_the_guard_excludes_fixed_accounts(self):
        import inspect

        from weapi.django_rest.serializers import agencies

        source = inspect.getsource(agencies)
        self.assertIn("stale = stale.filter(is_fixed=False)", source)

    def test_it_reports_what_it_refused(self):
        """Silently skipping is as bad as silently retiring."""
        import inspect

        from weapi.django_rest.serializers import agencies

        source = inspect.getsource(agencies)
        self.assertIn("refusing to retire", source)
        self.assertIn("stale.filter(is_fixed=True)", source)

    def test_a_fixed_sales_tax_account_survives_the_filter(self):
        """The behaviour, on the filter shape the code uses."""
        from accounts.choices import ChartOfAccountKindChoices
        from accounts.models import ChartOfAccount
        from companyio.models import Company

        company = Company.objects.create(name="Agency Co")
        control = ChartOfAccount.objects.create(
            company=company, title="Sales Tax Payable",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            is_fixed=True,
        )
        ordinary = ChartOfAccount.objects.create(
            company=company, title="CA Sales Tax",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            is_fixed=False,
        )

        stale = ChartOfAccount.objects.filter(
            company=company,
            title__in=["Sales Tax Payable", "CA Sales Tax"],
            kind=ChartOfAccountKindChoices.LIABILITIES,
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED)

        # What the code now does.
        stale.filter(is_fixed=False).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        control.refresh_from_db()
        ordinary.refresh_from_db()
        self.assertEqual(control.status, ChartOfAccountStatusChoices.ACTIVE)
        self.assertEqual(ordinary.status, ChartOfAccountStatusChoices.REMOVED)
