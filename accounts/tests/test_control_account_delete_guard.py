"""C2 — DELETE never checked `is_fixed`, so a control account could be removed.

`perform_destroy` does not run the serializer, so the `is_fixed` guard in
`PrivateWeChartOfAccountDetailsSerializer.validate` never fired on the DELETE path. The
serializer refused every other change to a fixed account; DELETE went straight past it.

Less severe than gap #7 claimed — the delete is soft and
`JournalEntryConnector.account` is PROTECT, so the ledger history survives. The damage is
the interaction:

    get_chart_of_account() excludes REMOVED   ->  posting stops resolving the account
    restoring it means PATCHing `status`      ->  is_fixed blocks all modification

So a control account could be removed and then **could not be put back through the API**.

Recorded here and NOT fixed here: the agency state-change path
(`serializers/agencies.py:258-266`) bulk-retires sales-tax accounts with
`.update(status=REMOVED)` and no `is_fixed` check. **60 `is_fixed` accounts carrying
`system_key=SALES_TAX_PAYABLE` match its filter shape in production.** A queryset
`.update()` bypasses `Model.save()`, so no model-level guard would catch it either — it
needs an explicit check in that code. That is the agency module's work.
"""

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company


class DeleteGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, *, is_fixed=False):
        return ChartOfAccount.objects.create(
            company=self.company,
            title=title,
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            is_fixed=is_fixed,
        )

    def test_the_view_refuses_a_fixed_account(self):
        from rest_framework.exceptions import ValidationError

        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
        )

        account = self.account("Accounts Receivable (A/R)", is_fixed=True)
        view = PrivateWeChartOfAccountDetails()

        with self.assertRaises(ValidationError):
            view.perform_destroy(account)

        account.refresh_from_db()
        self.assertEqual(account.status, ChartOfAccountStatusChoices.ACTIVE)

    def test_an_ordinary_account_still_soft_deletes(self):
        """The guard must not become a new way to fail."""
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
        )

        account = self.account("Office Supplies")
        view = PrivateWeChartOfAccountDetails()

        view.perform_destroy(account)

        account.refresh_from_db()
        self.assertEqual(account.status, ChartOfAccountStatusChoices.REMOVED)

    def test_the_parent_guard_still_fires(self):
        from rest_framework.exceptions import ValidationError

        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
        )

        parent = self.account("Bank Accounts")
        self.account("Business Checking").__class__.objects.filter(
            title="Business Checking"
        ).update(parent=parent)
        view = PrivateWeChartOfAccountDetails()

        with self.assertRaises(ValidationError):
            view.perform_destroy(parent)

    def test_a_fixed_account_is_refused_before_the_parent_check(self):
        """A fixed account with no children must still be refused."""
        from rest_framework.exceptions import ValidationError

        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
        )

        account = self.account("Opening Balance Equity", is_fixed=True)
        self.assertFalse(
            ChartOfAccount.objects.filter(parent=account).exists(),
            "no children, so only the is_fixed guard can refuse this",
        )

        with self.assertRaises(ValidationError):
            PrivateWeChartOfAccountDetails().perform_destroy(account)


class UnrestorableTests(TestCase):
    """Why removing a fixed account was worse than it looked."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def test_is_fixed_blocks_the_patch_that_would_restore_it(self):
        """The serializer refuses all modification, including status."""
        import inspect

        from weapi.django_rest.serializers import chart_of_accounts

        source = inspect.getsource(chart_of_accounts)
        self.assertIn("if self.instance.is_fixed == True:", source)
        self.assertIn("Fixed account cannot be modified.", source)

    def test_removed_accounts_are_invisible_to_posting(self):
        """`get_chart_of_account` excludes REMOVED, so posting stops finding it."""
        import inspect

        from common.django_rest.helpers import chart_of_account_helpers

        self.assertIn("REMOVED", inspect.getsource(chart_of_account_helpers))


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import chart_of_accounts

        return inspect.getsource(chart_of_accounts)

    def test_the_guard_exists_and_runs_first(self):
        source = self.source()

        self.assertIn("if instance.is_fixed:", source)
        guard = source.index("if instance.is_fixed:")
        parent = source.index("filter(parent=instance).exists()")
        self.assertLess(guard, parent, "the is_fixed guard must run first")

    def test_it_names_the_alternative(self):
        """A refusal that does not say what to do instead is a dead end."""
        self.assertIn("Make it inactive instead", self.source())
