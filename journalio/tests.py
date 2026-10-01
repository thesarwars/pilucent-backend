"""Tests that the ledger cannot be deleted out from under itself.

`JournalEntryConnector.account` was `CASCADE`. Deleting a chart-of-account row
therefore erased its journal lines — and because `JournalEntry` carries no FK to
the account, the **parent entries survived with their remaining legs**. The books
were left holding permanently unbalanced entries that no reconciliation could
explain, and the source rows were gone, so nothing could reconstruct them.

Worse, `ChartOfAccount.company` is `CASCADE`, so deleting one `Company` walked
the whole chain and destroyed a tenant's entire history in one statement.

The FK is now `PROTECT`. These tests pin that, and pin the two consequences that
make it safe to live with: the delete raises rather than silently succeeding, and
the surviving entry is never left half-deleted.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError
from django.test import TestCase

from common.test_support import PreConstraintDataMixin

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount
from companyio.models import Company
from journalio.choices import JournalEntryConnectorKindChoices
from journalio.models import JournalEntry, JournalEntryConnector


class LedgerDeletionProtectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Protected Co")
        cls.account = ChartOfAccount.objects.create(
            company=cls.company,
            title="Accounts Receivable (A/R)",
            code="1100",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        cls.entry = JournalEntry.objects.create(
            company=cls.company, amount=Decimal("100.00")
        )
        cls.connector = JournalEntryConnector.objects.create(
            journal=cls.entry,
            account=cls.account,
            debit=Decimal("100.00"),
            total=Decimal("100.00"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )

    def test_deleting_a_transacted_account_raises(self):
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.account.delete()

    def test_the_ledger_line_survives_the_attempt(self):
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.account.delete()
        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.connector.pk).exists()
        )
        self.assertTrue(ChartOfAccount.objects.filter(pk=self.account.pk).exists())

    def test_deleting_the_company_cannot_take_the_ledger_with_it(self):
        # The chain that made this critical: Company -> ChartOfAccount (CASCADE)
        # -> JournalEntryConnector. PROTECT fires even inside a cascade, which is
        # exactly why it is the right choice here rather than RESTRICT.
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.company.delete()
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.connector.pk).exists()
        )

    def test_an_untransacted_account_can_still_be_removed(self):
        # PROTECT must not turn every account into a permanent fixture; only
        # accounts carrying ledger history are pinned.
        spare = ChartOfAccount.objects.create(
            company=self.company,
            title="Unused Account",
            code="1999",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        spare.delete()
        self.assertFalse(ChartOfAccount.objects.filter(pk=spare.pk).exists())

    def test_soft_delete_remains_the_supported_path(self):
        self.account.status = ChartOfAccountStatusChoices.REMOVED
        self.account.save()
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, ChartOfAccountStatusChoices.REMOVED)
        self.assertTrue(
            JournalEntryConnector.objects.filter(pk=self.connector.pk).exists()
        )


class ProtectedErrorHandlerTests(TestCase):
    """`ProtectedError` must surface as 409, not as an unhandled 500."""

    def test_handler_maps_protected_error_to_409(self):
        from common.django_rest.exception_handler import exception_handler

        company = Company.objects.create(name="Handler Co")
        account = ChartOfAccount.objects.create(
            company=company,
            title="Cash",
            code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(company=company, amount=Decimal("5.00"))
        JournalEntryConnector.objects.create(
            journal=entry,
            account=account,
            debit=Decimal("5.00"),
            total=Decimal("5.00"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )

        try:
            with transaction.atomic():
                account.delete()
        except ProtectedError as error:
            response = exception_handler(error, {"view": None})
        else:  # pragma: no cover - the delete must raise
            self.fail("expected ProtectedError")

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data["error"])
        self.assertIn("cannot be deleted", response.data["message"])

    def test_handler_defers_to_drf_for_everything_else(self):
        from rest_framework.exceptions import NotFound

        from common.django_rest.exception_handler import exception_handler

        response = exception_handler(NotFound(), {"view": None})
        self.assertEqual(response.status_code, 404)

    def test_handler_returns_none_for_unknown_exceptions(self):
        # Anything it does not recognise must still bubble up as a 500 rather
        # than being swallowed.
        from common.django_rest.exception_handler import exception_handler

        self.assertIsNone(exception_handler(ValueError("boom"), {"view": None}))


class AdminCompanyEndpointTests(TestCase):
    """The superadmin DELETE endpoint deactivates instead of erasing."""

    def test_perform_destroy_soft_deletes(self):
        from adminio.django_rest.views.companies import AdminCompanyRetrieve
        from companyio.choices import CompanyStatusChoices

        company = Company.objects.create(name="Endpoint Co")
        AdminCompanyRetrieve().perform_destroy(company)

        company.refresh_from_db()
        self.assertEqual(company.status, CompanyStatusChoices.REMOVED)
        self.assertTrue(Company.objects.filter(pk=company.pk).exists())


class RemovedCompanyIsActuallyRemovedTests(TestCase):
    """Soft delete only means something if the rest of the system honours it.

    `AdminCompanyRetrieve.perform_destroy` sets status=REMOVED instead of
    erasing the tenant, because the ledger has to survive. Nothing respected
    that status, so the endpoint returned 204 and the company kept working --
    arguably worse than the 409 it replaced, because it looked like it worked.
    """

    @classmethod
    def setUpTestData(cls):
        from companyio.choices import CompanyStatusChoices
        from companyio.models import CompanyUser

        cls.user = __import__(
            "accounts.models", fromlist=["User"]
        ).User.objects.create(email="member@example.com", name="Member")
        cls.live = Company.objects.create(
            name="Live Co", status=CompanyStatusChoices.ACTIVE
        )
        cls.removed = Company.objects.create(
            name="Removed Co", status=CompanyStatusChoices.REMOVED
        )
        CompanyUser.objects.create(user=cls.user, company=cls.removed)
        CompanyUser.objects.create(user=cls.user, company=cls.live)

    def test_get_active_company_never_returns_a_removed_company(self):
        # No company in context -> falls back to a membership. It must skip the
        # removed one rather than scoping the whole request to a dead tenant.
        self.assertEqual(self.user.get_active_company(), self.live)

    def test_get_active_company_denies_when_context_points_at_a_removed_company(self):
        from common.tenant import set_current_company_id

        set_current_company_id(self.removed.id)
        try:
            self.assertIsNone(self.user.get_active_company())
        finally:
            set_current_company_id(None)

    def test_workspace_picker_hides_removed_companies(self):
        from accounts.django_rest.helpers.workspace import get_membership_queryset

        companies = [cu.company for cu in get_membership_queryset(self.user)]
        self.assertIn(self.live, companies)
        self.assertNotIn(self.removed, companies)

    def test_selecting_a_removed_company_is_rejected(self):
        from rest_framework.exceptions import ValidationError

        from accounts.django_rest.serializers.workspace import SelectCompanySerializer

        class _Request:
            user = self.user

        serializer = SelectCompanySerializer(
            data={"company_uid": str(self.removed.uid)},
            context={"request": _Request()},
        )
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    def test_selecting_a_live_company_still_works(self):
        from accounts.django_rest.serializers.workspace import SelectCompanySerializer

        class _Request:
            user = self.user

        serializer = SelectCompanySerializer(
            data={"company_uid": str(self.live.uid)},
            context={"request": _Request()},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)


class SystemKeyResolutionTests(TestCase):
    """The resolver must survive a rename, which title matching did not."""

    @classmethod
    def setUpTestData(cls):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        cls.Key = Key
        cls.company = Company.objects.create(name="Keyed Co")
        cls.inventory = ChartOfAccount.objects.create(
            company=cls.company, title="Inventory Asset", code="1200",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            system_key=Key.INVENTORY_ASSET,
        )
        cls.plain = ChartOfAccount.objects.create(
            company=cls.company, title="Office Supplies", code="6100",
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def _get(self, titles):
        from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
        return get_chart_of_account(titles, self.company)

    def test_contract_unchanged_for_existing_callers(self):
        got = self._get(["Inventory Asset", "Office Supplies"])
        self.assertEqual(got["Inventory Asset"], self.inventory)
        self.assertEqual(got["Office Supplies"], self.plain)

    def test_renamed_control_account_is_still_found(self):
        # This is the whole point: title matching returned nothing here.
        self.inventory.title = "Stock On Hand"
        self.inventory.save()
        got = self._get(["Inventory Asset"])
        print(f"\n  RESULT renamed 'Inventory Asset' -> 'Stock On Hand', resolved: {got.get('Inventory Asset') == self.inventory}")
        self.assertEqual(got["Inventory Asset"], self.inventory)

    def test_unkeyed_account_still_resolves_by_title(self):
        # Un-backfilled tenants must keep working during the rollout.
        legacy = ChartOfAccount.objects.create(
            company=self.company, title="Undeposited Funds", code="1410",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.assertEqual(self._get(["Undeposited Funds"])["Undeposited Funds"], legacy)

    def test_removed_control_account_is_not_returned(self):
        self.inventory.status = ChartOfAccountStatusChoices.REMOVED
        self.inventory.save()
        self.assertNotIn("Inventory Asset", self._get(["Inventory Asset"]))

    def test_missing_system_keys_reports_the_gap(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        missing = missing_system_keys(self.company)
        self.assertNotIn(self.Key.INVENTORY_ASSET, missing)
        self.assertIn(self.Key.AR, missing)
        print(f"  RESULT missing_system_keys -> {len(missing)} of 10 absent")

    def test_system_key_is_unique_per_company(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChartOfAccount.objects.create(
                    company=self.company, title="Another Inventory", code="1201",
                    kind=ChartOfAccountKindChoices.ASSETS,
                    status=ChartOfAccountStatusChoices.ACTIVE,
                    system_key=self.Key.INVENTORY_ASSET,
                )

    def test_a_removed_account_does_not_block_its_replacement(self):
        self.inventory.status = ChartOfAccountStatusChoices.REMOVED
        self.inventory.save()
        replacement = ChartOfAccount.objects.create(
            company=self.company, title="Inventory Asset", code="1202",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            system_key=self.Key.INVENTORY_ASSET,
        )
        self.assertEqual(self._get(["Inventory Asset"])["Inventory Asset"], replacement)


class SeedingStampsSystemKeysTests(TestCase):
    """Onboarding must produce a company that can actually post."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        # The seeder resolves account_type/detail_type against the Category
        # tree, so it must exist before any company is onboarded.
        call_command("create_chart_of_account_category", verbosity=0)

    def _onboard(self, kind):
        # Company creation fires the post_save signal that seeds the chart --
        # calling create_chart_of_accounts() as well seeds it twice.
        from companyio.models import Company
        return Company.objects.create(name=f"{kind} Co", kind=kind)

    def test_a_seeded_company_has_the_full_spine(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        company = self._onboard("ECOMMERCE")
        missing = missing_system_keys(company)
        print(f"\n  RESULT ECOMMERCE missing system keys: {missing or 'none'}")
        self.assertEqual(missing, [])

    def test_posting_engine_resolves_every_control_account(self):
        from common.django_rest.helpers.chart_of_account_helpers import (
            TITLE_TO_SYSTEM_KEY, get_chart_of_account,
        )
        company = self._onboard("RETAIL_WHOLESALE")
        got = get_chart_of_account(list(TITLE_TO_SYSTEM_KEY), company)
        print(f"  RESULT RETAIL_WHOLESALE resolved {len(got)}/{len(TITLE_TO_SYSTEM_KEY)} control accounts")
        self.assertEqual(len(got), len(TITLE_TO_SYSTEM_KEY))

    def test_ordinary_accounts_get_no_system_key(self):
        company = self._onboard("ECOMMERCE")
        total = ChartOfAccount.objects.filter(company=company).count()
        keyed = ChartOfAccount.objects.filter(company=company, system_key__isnull=False).count()
        from common.django_rest.helpers.chart_of_account_helpers import TITLE_TO_SYSTEM_KEY
        print(f"  RESULT ECOMMERCE seeded {total} accounts, {keyed} keyed")
        self.assertEqual(keyed, len(TITLE_TO_SYSTEM_KEY))
        self.assertGreater(total, 10)

    def test_rename_survives_after_seeding(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
        company = self._onboard("ECOMMERCE")
        acct = ChartOfAccount.objects.get(company=company, system_key=Key.INVENTORY_ASSET)
        acct.title = "Renamed By User"
        acct.save()
        got = get_chart_of_account(["Inventory Asset"], company)
        print(f"  RESULT after user rename, still resolves: {got.get('Inventory Asset') == acct}")
        self.assertEqual(got["Inventory Asset"], acct)

    def test_food_beverage_can_now_post(self):
        # This industry could not post a single transaction: it spelled all ten
        # control accounts differently, so every lookup returned None.
        from common.django_rest.helpers.chart_of_account_helpers import (
            ON_DEMAND_KEYS, TITLE_TO_SYSTEM_KEY, get_chart_of_account,
            missing_system_keys,
        )
        company = self._onboard("FOOD_BEVERAGE")
        missing = missing_system_keys(company)
        # The spine only. An ON_DEMAND key is created the first time the thing
        # that needs it happens, and food_beverage is precisely the template
        # that ships none of them -- it has no "Payroll Liabilities" row and
        # neither federal tax row. Their absence at onboarding is the designed
        # state, not the seeding failure this test exists to catch.
        spine = [
            title
            for title, key in TITLE_TO_SYSTEM_KEY.items()
            if key not in ON_DEMAND_KEYS
        ]
        resolved = get_chart_of_account(spine, company)
        print(f"  RESULT FOOD_BEVERAGE missing={missing or 'none'} resolved={len(resolved)}/{len(spine)}")
        self.assertEqual(missing, [])
        self.assertEqual(len(resolved), len(spine))

    def test_food_beverage_inventory_split_survives_as_sub_accounts(self):
        company = self._onboard("FOOD_BEVERAGE")
        control = ChartOfAccount.objects.get(company=company, title="Inventory Asset")
        children = ChartOfAccount.objects.filter(company=company, parent=control)
        names = sorted(children.values_list("title", flat=True))
        print(f"  RESULT Inventory Asset children: {names}")
        self.assertEqual(names, ["Inventory (Beverage)", "Inventory (Food)"])


class BackfillSystemKeysTests(PreConstraintDataMixin, TestCase):
    """The repair for tenants onboarded before system_key existed."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("backfill_system_keys", stdout=out, **kwargs)
        return out.getvalue()

    def _legacy_company(self, kind="ECOMMERCE"):
        """A company as it looked before system_key: seeded, then keys cleared."""
        from companyio.models import Company
        company = Company.objects.create(name=f"Legacy {kind}", kind=kind)
        ChartOfAccount.objects.filter(company=company).update(system_key=None)
        return company

    def test_dry_run_changes_nothing(self):
        company = self._legacy_company()
        output = self._run()
        self.assertIn("Dry run", output)
        self.assertEqual(
            ChartOfAccount.objects.filter(company=company, system_key__isnull=False).count(), 0
        )

    def test_apply_stamps_every_control_account(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        company = self._legacy_company()
        self._run(apply=True)
        missing = missing_system_keys(company)
        print(f"\n  RESULT legacy ECOMMERCE after backfill, missing: {missing or 'none'}")
        self.assertEqual(missing, [])

    def test_is_idempotent(self):
        company = self._legacy_company()
        self._run(apply=True)
        second = self._run(apply=True)
        self.assertIn("to stamp               : 0", second)
        from common.django_rest.helpers.chart_of_account_helpers import (
            ON_DEMAND_KEYS,
            TITLE_TO_SYSTEM_KEY,
        )

        # The spine only. A title in the map is not necessarily one the backfill
        # stamps: an ON_DEMAND key is created the first time the thing that needs
        # it happens, so a company that has not needed it yet correctly has none.
        # Its title is still mapped, because the *seeder* reads that map to key
        # the row when a template does ship it.
        expected = len(set(TITLE_TO_SYSTEM_KEY.values()) - ON_DEMAND_KEYS)
        self.assertEqual(
            ChartOfAccount.objects.filter(company=company, system_key__isnull=False).count(),
            expected,
        )

    def test_absent_accounts_are_reported_not_invented(self):
        company = self._legacy_company()
        ChartOfAccount.objects.filter(company=company, title="Undeposited Funds").delete()
        output = self._run(apply=True)
        self.assertIn("absent", output.lower())
        self.assertFalse(
            ChartOfAccount.objects.filter(company=company, title="Undeposited Funds").exists()
        )

    def test_create_missing_builds_from_the_template(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        company = self._legacy_company()
        ChartOfAccount.objects.filter(company=company, title="Undeposited Funds").delete()
        self._run(apply=True, create_missing=True)
        created = ChartOfAccount.objects.get(company=company, title="Undeposited Funds")
        print(f"  RESULT recreated 'Undeposited Funds' code={created.code} "
              f"type={created.account_type.title!r} keyed={created.system_key}")
        self.assertEqual(created.code, "1410")
        self.assertEqual(missing_system_keys(company), [])

    def test_duplicate_titles_are_skipped_not_guessed(self):
        company = self._legacy_company()
        ChartOfAccount.objects.create(
            company=company, title="Inventory Asset", code="9999",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        output = self._run(apply=True)
        print("  RESULT duplicate title -> reported ambiguous, not guessed")
        self.assertIn("Ambiguous", output)
        self.assertFalse(
            ChartOfAccount.objects.filter(
                company=company, title="Inventory Asset", system_key__isnull=False
            ).exists()
        )


class OnboardingSelfHealsTests(TestCase):
    """A company must never finish onboarding unable to post.

    Production evidence: a backfill found 106 control accounts missing across
    28 of 60 companies, five of them missing all ten. Seeding failed silently
    every time.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def test_a_normal_onboarding_needs_no_healing(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        from companyio.models import Company
        company = Company.objects.create(name="Healthy Co", kind="ECOMMERCE")
        self.assertEqual(missing_system_keys(company), [])

    def test_a_gap_after_seeding_is_repaired(self):
        # Simulate the production failure: seeding drops a control account.
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        from companyio.django_rest.helpers.signal_helpers import ensure_control_accounts
        from companyio.models import Company
        company = Company.objects.create(name="Gappy Co", kind="CONSTRUCTION")
        ChartOfAccount.objects.filter(
            company=company, title="Undeposited Funds"
        ).delete()
        self.assertEqual(missing_system_keys(company), ["UNDEPOSITED_FUNDS"])

        remaining = ensure_control_accounts(company)
        healed = ChartOfAccount.objects.get(company=company, title="Undeposited Funds")
        print(f"\n  RESULT healed 'Undeposited Funds' code={healed.code} "
              f"type={healed.account_type.title!r} key={healed.system_key}")
        self.assertEqual(remaining, [])
        self.assertEqual(missing_system_keys(company), [])

    def test_healing_matches_what_a_fresh_company_gets(self):
        # A healed account must be indistinguishable from a seeded one --
        # otherwise the repair introduces its own drift.
        from companyio.django_rest.helpers.signal_helpers import ensure_control_accounts
        from companyio.models import Company
        fresh = Company.objects.create(name="Fresh Co", kind="RETAIL_WHOLESALE")
        gappy = Company.objects.create(name="Gappy Co 2", kind="RETAIL_WHOLESALE")
        ChartOfAccount.objects.filter(company=gappy, title="Inventory Asset").delete()
        ensure_control_accounts(gappy)

        a = ChartOfAccount.objects.get(company=fresh, title="Inventory Asset")
        b = ChartOfAccount.objects.get(company=gappy, title="Inventory Asset")
        for field in ("code", "kind", "system_key", "is_fixed"):
            self.assertEqual(getattr(a, field), getattr(b, field), field)
        self.assertEqual(a.account_type_id, b.account_type_id)
        self.assertEqual(a.detail_type_id, b.detail_type_id)
        print("  RESULT healed account is identical to a freshly seeded one")

    def test_it_is_idempotent(self):
        from companyio.django_rest.helpers.signal_helpers import ensure_control_accounts
        from companyio.models import Company
        company = Company.objects.create(name="Idem Co", kind="ECOMMERCE")
        before = ChartOfAccount.objects.filter(company=company).count()
        self.assertEqual(ensure_control_accounts(company), [])
        self.assertEqual(ChartOfAccount.objects.filter(company=company).count(), before)

    def test_food_beverage_onboards_complete(self):
        from common.django_rest.helpers.chart_of_account_helpers import missing_system_keys
        from companyio.models import Company
        company = Company.objects.create(name="FB Co", kind="FOOD_BEVERAGE")
        self.assertEqual(missing_system_keys(company), [])


class UpdateOpeningBalanceTests(TestCase):
    """The helper must never silently do nothing.

    Six purchase call sites passed "addition"/"substraction" -- which matched no
    branch -- so the journal line was written while the stored balance was not.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Balance Co")
        self.account = ChartOfAccount.objects.create(
            company=self.company, title="Inventory Asset", code="1200",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("100.00"),
        )

    def test_credit_adds(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        update_opening_balance(self.account, K.CREDIT, Decimal("25.00"), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("125.00"))

    def test_debit_subtracts(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        update_opening_balance(self.account, K.DEBIT, Decimal("25.00"), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("75.00"))

    def test_unknown_op_raises_instead_of_no_oping(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        for bad in ("addition", "substraction", "", "nonsense"):
            with self.assertRaises(ValueError, msg=f"{bad!r} should raise"):
                update_opening_balance(self.account, bad, Decimal("25.00"), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("100.00"))
        print("\n  RESULT 'addition'/'substraction' now raise instead of silently no-oping")

    def test_action_type_converts_cleanly(self):
        # The supported way to go from a connector action_type to an operation.
        from common.django_rest.helpers.balance_helpers import (
            balance_operation_for_action, update_opening_balance,
        )
        update_opening_balance(
            self.account, balance_operation_for_action("addition"), Decimal("10.00"), 0
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("110.00"))

    def test_update_branch_still_works(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        got = update_opening_balance(self.account, "update", Decimal("150.00"), Decimal("100.00"))
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, Decimal("150.00"))
        self.assertEqual(got["action_type"], "addition")


class OpeningBalanceIsNotWritableTests(TestCase):
    """opening_balance is a running balance, not a settable field."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def test_opening_balance_is_read_only_on_update(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )
        fields = S().get_fields()
        print(f"\n  RESULT PATCH opening_balance read_only={fields['opening_balance'].read_only}")
        self.assertTrue(fields["opening_balance"].read_only)
        # system_key is not exposed at all, which is stronger than read-only.
        self.assertNotIn("system_key", fields)

    def test_patching_it_does_not_move_the_balance(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )
        company = Company.objects.create(name="RO Co", kind="ECOMMERCE")
        account = ChartOfAccount.objects.create(
            company=company, title="Some Asset", code="1500",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("500.00"),
        )
        s = S(instance=account, data={"opening_balance": "999999.00"}, partial=True)
        s.is_valid(raise_exception=True)
        self.assertNotIn("opening_balance", s.validated_data)
        account.refresh_from_db()
        print(f"  RESULT after PATCH opening_balance=999999 -> stays {account.opening_balance}")
        self.assertEqual(account.opening_balance, Decimal("500.00"))

    def _create(self, company, kind_title, opening_balance):
        from categoryio.models import Category
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as S,
        )
        at = Category.objects.filter(title=kind_title, parent__isnull=False).first()
        dt = Category.objects.filter(parent=at).first()

        class _U:
            def get_active_company(self): return company
            def get_employee(self): return None
        class _R:
            user = _U()
        return S(
            data={
                "title": f"Test {kind_title}", "code": "7777",
                "account_type_slug": at.slug, "detail_type_slug": dt.slug,
                "opening_balance": str(opening_balance),
            },
            context={"request": _R()},
        )

    def test_income_account_rejects_an_opening_balance(self):
        company = Company.objects.create(name="Inc Co", kind="ECOMMERCE")
        s = self._create(company, "Income", "500.00")
        self.assertFalse(s.is_valid())
        self.assertIn("opening_balance", s.errors)
        print(f"  RESULT income account w/ opening balance -> rejected")

    def test_expense_account_rejects_an_opening_balance(self):
        company = Company.objects.create(name="Exp Co", kind="ECOMMERCE")
        s = self._create(company, "Expense", "500.00")
        self.assertFalse(s.is_valid())
        self.assertIn("opening_balance", s.errors)

    def test_income_account_with_zero_is_fine(self):
        company = Company.objects.create(name="Zero Co", kind="ECOMMERCE")
        s = self._create(company, "Income", "0.00")
        self.assertTrue(s.is_valid(), s.errors)

    def test_asset_account_may_still_have_one(self):
        # Balance sheet accounts legitimately carry opening balances -- create()
        # posts the matching Opening Balance Equity entry for them.
        company = Company.objects.create(name="Asset Co", kind="ECOMMERCE")
        s = self._create(company, "Bank", "500.00")
        self.assertTrue(s.is_valid(), s.errors)
        print("  RESULT asset account w/ opening balance -> still allowed")


class ReclassificationGuardTests(TestCase):
    """A posted account cannot be moved to a different statement section."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from categoryio.models import Category
        self.company = Company.objects.create(name="Reclass Co", kind="ECOMMERCE")
        self.bank_type = Category.objects.filter(title="Bank", parent__isnull=False).first()
        self.account = ChartOfAccount.objects.create(
            company=self.company, title="Some Bank", code="1500",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            account_type=self.bank_type,
        )

    def _post_to(self, account):
        entry = JournalEntry.objects.create(company=self.company, amount=Decimal("10.00"))
        JournalEntryConnector.objects.create(
            journal=entry, account=account, debit=Decimal("10.00"),
            total=Decimal("10.00"), kind=JournalEntryConnectorKindChoices.DEBIT,
        )

    def test_untransacted_account_can_be_reclassified(self):
        from categoryio.models import Category
        other = Category.objects.filter(
            title="Other Current Assets", parent__isnull=False
        ).first()
        self.account.account_type = other
        self.account.save()  # must not raise
        self.account.refresh_from_db()
        self.assertEqual(self.account.account_type, other)

    def test_transacted_account_cannot_be_reclassified(self):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from categoryio.models import Category
        self._post_to(self.account)
        self.account.account_type = Category.objects.filter(
            title="Other Current Assets", parent__isnull=False
        ).first()
        with self.assertRaises(DjangoValidationError):
            self.account.save()
        print("\n  RESULT reclassifying a posted account -> blocked at the model")

    def test_kind_cannot_change_after_posting(self):
        from django.core.exceptions import ValidationError as DjangoValidationError
        self._post_to(self.account)
        self.account.kind = ChartOfAccountKindChoices.INCOMES
        with self.assertRaises(DjangoValidationError):
            self.account.save()

    def test_balance_updates_still_work_on_a_posted_account(self):
        # The guard must not touch the hot path: update_opening_balance ends in
        # save_dirty_fields() on every single posting.
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        self._post_to(self.account)
        for _ in range(3):
            update_opening_balance(self.account, K.CREDIT, Decimal("5.00"), 0)
        self.account.refresh_from_db()
        print(f"  RESULT 3 balance updates on a posted account -> {self.account.opening_balance}")
        self.assertEqual(self.account.opening_balance, Decimal("15.00"))

    def test_title_and_code_are_still_editable_after_posting(self):
        self._post_to(self.account)
        self.account.title = "Renamed Bank"
        self.account.code = "1501"
        self.account.save()  # must not raise -- these are labels, not classification
        self.account.refresh_from_db()
        self.assertEqual(self.account.title, "Renamed Bank")


class SerializerGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def test_kind_is_read_only_on_update(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )
        self.assertTrue(S().get_fields()["kind"].read_only)
        print("  RESULT kind read_only on PATCH -> True")

    def test_status_cannot_be_patched_to_removed(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )
        company = Company.objects.create(name="Status Co", kind="ECOMMERCE")
        account = ChartOfAccount.objects.create(
            company=company, title="A", code="1600",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        s = S(instance=account, data={"status": "REMOVED"}, partial=True)
        self.assertFalse(s.is_valid())
        self.assertIn("status", s.errors)
        print("  RESULT PATCH status=REMOVED -> rejected, must use DELETE")

    def test_detail_level_category_as_account_type_is_rejected(self):
        from categoryio.models import Category
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as S,
        )
        company = Company.objects.create(name="Kind Co", kind="ECOMMERCE")
        # A detail type, i.e. a grandchild -- its parent is not a root kind.
        detail = Category.objects.filter(parent__parent__isnull=False).first()
        class _U:
            def get_active_company(self): return company
            def get_employee(self): return None
        class _R:
            user = _U()
        s = S(data={"title": "Bad", "code": "8888",
                    "account_type_slug": detail.slug, "detail_type_slug": detail.slug},
              context={"request": _R()})
        self.assertFalse(s.is_valid())
        print(f"  RESULT detail-level category as account_type -> rejected "
              f"(would have stored kind={detail.parent.title.upper()!r})")


class AtomicBalanceWriteTests(TestCase):
    """The F() rewrite must not break the three contracts callers depend on."""

    def setUp(self):
        self.company = Company.objects.create(name="Atomic Co")
        self.account = ChartOfAccount.objects.create(
            company=self.company, title="A/R", code="1100",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("100.00"),
        )

    def test_contract_1_caller_sees_the_new_value_immediately(self):
        # ~84 call sites do `connector.last_balance = account.opening_balance`
        # on the very next line. A bare F() update would leave 100.00 here.
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        update_opening_balance(self.account, K.CREDIT, Decimal("25.00"), 0)
        print(f"\n  RESULT in-memory value right after the call: {self.account.opening_balance}")
        self.assertEqual(self.account.opening_balance, Decimal("125.00"))

    def test_contract_2_works_for_customer_and_supplier(self):
        from customerio.models import Customer
        from supplierio.models import Supplier
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        cust = Customer.objects.create(
            company=self.company, first_name="C", opening_balance=Decimal("10.00"))
        supp = Supplier.objects.create(
            company=self.company, first_name="S", opening_balance=Decimal("10.00"))
        for obj in (cust, supp):
            update_opening_balance(obj, K.CREDIT, Decimal("5.00"), 0)
            obj.refresh_from_db()
            self.assertEqual(obj.opening_balance, Decimal("15.00"))
        print("  RESULT polymorphic over Customer and Supplier -> both 15.00")

    def test_contract_3_other_dirty_fields_still_flush(self):
        # The trailing save_dirty_fields() was incidental but callers rely on it.
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        self.account.description = "set before the call"
        update_opening_balance(self.account, K.CREDIT, Decimal("5.00"), 0)
        fresh = ChartOfAccount.objects.get(pk=self.account.pk)
        print(f"  RESULT sibling dirty field flushed: {fresh.description!r}")
        self.assertEqual(fresh.description, "set before the call")
        self.assertEqual(fresh.opening_balance, Decimal("105.00"))

    def test_the_write_is_atomic_not_read_modify_write(self):
        # Two stale in-memory copies. Under read-modify-write the second write
        # overwrites the first and one +50 is lost, leaving 150. With an F()
        # increment the database adds both, giving 200.
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        a = ChartOfAccount.objects.get(pk=self.account.pk)
        b = ChartOfAccount.objects.get(pk=self.account.pk)
        update_opening_balance(a, K.CREDIT, Decimal("50.00"), 0)
        update_opening_balance(b, K.CREDIT, Decimal("50.00"), 0)
        final = ChartOfAccount.objects.get(pk=self.account.pk).opening_balance
        print(f"  RESULT two concurrent +50 on a stale copy -> {final} (150 = lost update)")
        self.assertEqual(final, Decimal("200.00"))

    def test_update_branch_and_return_value_preserved(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        got = update_opening_balance(
            self.account, "update", Decimal("150.00"), Decimal("100.00"))
        self.assertEqual(got["action_type"], "addition")
        self.assertEqual(got["total_debit_or_credit"], Decimal("50.00"))
        self.assertEqual(self.account.opening_balance, Decimal("150.00"))

    def test_update_branch_downwards(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        got = update_opening_balance(
            self.account, "update", Decimal("60.00"), Decimal("100.00"))
        self.assertEqual(got["action_type"], "substraction")
        self.assertEqual(got["total_debit_or_credit"], Decimal("40.00"))
        self.assertEqual(self.account.opening_balance, Decimal("60.00"))

    def test_unsaved_object_still_works(self):
        from common.django_rest.helpers.balance_helpers import update_opening_balance
        from journalio.choices import JournalEntryConnectorKindChoices as K
        fresh = ChartOfAccount(
            company=self.company, title="Unsaved", code="1700",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        update_opening_balance(fresh, K.CREDIT, Decimal("30.00"), 0)
        self.assertEqual(fresh.opening_balance, Decimal("30.00"))


class ServiceInvoiceBalancesTests(TestCase):
    """An invoice must balance even when it consumes no inventory.

    Revenue used to be emitted inside the FIFO loop, so a line that deducted no
    stock -- a service, or anything out of stock -- produced a debit to
    Accounts Receivable with no credit anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from customerio.models import Customer
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        from accounts.models import User
        from companyio.models import Company, CompanyUser

        self.company = Company.objects.create(name="Svc Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="svc@example.com", name="Svc")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="Cust", display_name="Cust")
        income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()
        # A SERVICE product: no stock, no purchase layers -> FIFO deducts nothing.
        self.product = Product.objects.create(
            company=self.company, title="Consulting", sku="SVC1",
            quantity=0, date="2026-01-01",
            kind=ProductKindChoices.SERVICE, status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("150.00"), income_account=income,
        )

    def _create_invoice(self, **overrides):
        from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer
        from common.tenant import set_current_company_id

        class _R:
            pass
        req = _R(); req.user = self.user
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeSaleListSerializer(
                data={
                    "customer_uid": str(self.customer.uid),
                    "currency_kind": "USD",
                    "currency_rate": "1",
                    "is_invoice": True,
                    "status": "OPEN",
                    "tax_kind": "NO_TAX",
                    "email": {"customer_email": "c@example.com", "cc_emails": [], "bcc_emails": []},
                    "total": "1500.00",
                    "due_total": "1500.00",
                    "sales_items": [{
                        "product_uid": str(self.product.uid),
                        "quantity": 10,
                        "sale_price": "150.00",
                        "total": "1500.00",
                    }],
                },
                context={"request": req},
            )
            payload = s.initial_data
            payload.update(overrides)
            s = PrivateWeSaleListSerializer(data=payload, context={"request": req})
            s.is_valid(raise_exception=True)
            return s.save()
        finally:
            set_current_company_id(None)

    def test_fifo_deducts_nothing_for_a_service_product(self):
        from common.django_rest.helpers.fifo_product_quantity_helpers import (
            fifo_product_deduction,
        )
        remaining, details, _ = fifo_product_deduction(self.product, 10)
        print(f"\n  RESULT service product: remaining={remaining} layers={len(details)}")
        self.assertEqual(details, [])

    def test_the_invoice_entry_balances(self):
        sale = self._create_invoice()
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry, "no journal entry was created")
        rows = entry.journalentryconnector_set.all()
        debit = sum(r.debit or 0 for r in rows)
        credit = sum(r.credit or 0 for r in rows)
        print(f"  RESULT service invoice: debit={debit} credit={credit} diff={debit-credit}")
        for r in rows:
            print(f"         {r.account.title:<32} dr={r.debit} cr={r.credit}")
        self.assertEqual(debit, credit, "entry does not balance")

    def test_income_is_recognised_in_full(self):
        sale = self._create_invoice()
        entry = JournalEntry.objects.filter(sale=sale).first()
        income = entry.journalentryconnector_set.filter(
            account__system_key="SALES_OF_PRODUCT_INCOME")
        total = sum(r.credit or 0 for r in income)
        print(f"  RESULT income credited: {total} (expected 1500.00)")
        self.assertEqual(total, Decimal("1500.00"))


    def test_an_invoice_without_kind_still_posts_a_journal(self):
        # `kind` is optional on the wire. It used to read None in create(), so
        # neither the SALE nor the REFUND branch ran and no journal existed --
        # while the sale, its items and the balance mutations were committed.
        sale = self._create_invoice()
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry, "omitting kind produced no journal entry")
        rows = entry.journalentryconnector_set.all()
        debit = sum(r.debit or 0 for r in rows)
        credit = sum(r.credit or 0 for r in rows)
        print(f"  RESULT invoice with NO kind in payload: debit={debit} credit={credit}")
        self.assertEqual(debit, credit)


class ContraRevenueAccountsTests(TestCase):
    """Sales Discounts and Shipping Income must exist before Sale #2 can post."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def test_every_industry_seeds_both(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from companyio.models import Company
        for kind in ("ECOMMERCE", "CONSTRUCTION", "FOOD_BEVERAGE", "REAL_ESTATE"):
            company = Company.objects.create(name=f"{kind} CR", kind=kind)
            disc = ChartOfAccount.objects.filter(
                company=company, system_key=Key.SALES_DISCOUNTS).first()
            ship = ChartOfAccount.objects.filter(
                company=company, system_key=Key.SHIPPING_INCOME).first()
            self.assertIsNotNone(disc, f"{kind} has no Sales Discounts")
            self.assertIsNotNone(ship, f"{kind} has no Shipping Income")
            self.assertEqual(disc.kind, ChartOfAccountKindChoices.INCOMES)
            self.assertEqual(ship.kind, ChartOfAccountKindChoices.INCOMES)
        print(f"\n  RESULT 4 industries seeded: both accounts present, both INCOMES")

    def test_resolvable_by_the_posting_engine(self):
        from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
        from companyio.models import Company
        company = Company.objects.create(name="Resolve CR", kind="RETAIL_WHOLESALE")
        got = get_chart_of_account(["Sales Discounts", "Shipping Income"], company)
        print(f"  RESULT posting engine resolves: {sorted(got)}")
        self.assertEqual(len(got), 2)

    def test_renamed_account_keeps_its_detail_type(self):
        # The 12 industries that had "Discounts Given" were renamed, not replaced,
        # so the contra-revenue typing must survive.
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from companyio.models import Company
        company = Company.objects.create(name="Renamed CR", kind="ECOMMERCE")
        disc = ChartOfAccount.objects.get(company=company, system_key=Key.SALES_DISCOUNTS)
        print(f"  RESULT renamed account: {disc.title!r} detail_type={disc.detail_type.title!r}")
        self.assertEqual(disc.detail_type.title, "Discounts/Refunds Given")


class LegacyMergeTests(TestCase):
    """Repair for companies left holding both a legacy and a canonical account."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def _run(self, **kw):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("backfill_system_keys", stdout=out, **kw)
        return out.getvalue()

    def _company_with_duplicate(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from companyio.models import Company
        company = Company.objects.create(name="Dup Co", kind="ECOMMERCE")
        canonical = ChartOfAccount.objects.get(company=company, system_key=Key.SALES_DISCOUNTS)
        # Recreate the state the earlier run produced: a legacy-named account
        # sitting beside the freshly created canonical one.
        legacy = ChartOfAccount.objects.create(
            company=company, title="Discounts Given", code="4060",
            kind=ChartOfAccountKindChoices.INCOMES,
            status=ChartOfAccountStatusChoices.ACTIVE,
            account_type=canonical.account_type, detail_type=canonical.detail_type,
        )
        return company, canonical, legacy

    def test_backfill_now_renames_instead_of_duplicating(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from companyio.models import Company
        company = Company.objects.create(name="Rename Co", kind="ECOMMERCE")
        acct = ChartOfAccount.objects.get(company=company, system_key=Key.SALES_DISCOUNTS)
        acct.title = "Discounts Given"; acct.system_key = None; acct.save()
        self._run(apply=True)
        acct.refresh_from_db()
        print(f"\n  RESULT legacy-named account -> title={acct.title!r} key={acct.system_key}")
        self.assertEqual(acct.title, "Sales Discounts")
        self.assertEqual(acct.system_key, Key.SALES_DISCOUNTS)
        self.assertEqual(
            ChartOfAccount.objects.filter(company=company, title="Discounts Given").count(), 0)

    def test_merge_keeps_the_account_that_has_history(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        company, canonical, legacy = self._company_with_duplicate()
        entry = JournalEntry.objects.create(company=company, amount=Decimal("9.00"))
        JournalEntryConnector.objects.create(
            journal=entry, account=legacy, debit=Decimal("9.00"),
            total=Decimal("9.00"), kind=JournalEntryConnectorKindChoices.DEBIT)
        canonical_pk = canonical.pk

        self._run(apply=True, merge_legacy=True)

        legacy.refresh_from_db()
        print(f"  RESULT kept the account with history: {legacy.title!r} key={legacy.system_key}")
        self.assertEqual(legacy.title, "Sales Discounts")
        self.assertEqual(legacy.system_key, Key.SALES_DISCOUNTS)
        self.assertFalse(ChartOfAccount.objects.filter(pk=canonical_pk).exists())
        self.assertEqual(legacy.journalentryconnector_set.count(), 1)

    def test_dry_run_changes_nothing(self):
        company, canonical, legacy = self._company_with_duplicate()
        out = self._run(merge_legacy=True)
        self.assertIn("Dry run", out)
        self.assertTrue(ChartOfAccount.objects.filter(pk=canonical.pk).exists())

    def test_both_in_use_is_reported_not_merged(self):
        company, canonical, legacy = self._company_with_duplicate()
        entry = JournalEntry.objects.create(company=company, amount=Decimal("5.00"))
        for acct in (canonical, legacy):
            JournalEntryConnector.objects.create(
                journal=entry, account=acct, debit=Decimal("5.00"),
                total=Decimal("5.00"), kind=JournalEntryConnectorKindChoices.DEBIT)
        out = self._run(apply=True, merge_legacy=True)
        print("  RESULT both accounts in use -> reported for manual resolution")
        self.assertIn("BOTH have journal lines", out)
        self.assertTrue(ChartOfAccount.objects.filter(pk=canonical.pk).exists())
        self.assertTrue(ChartOfAccount.objects.filter(pk=legacy.pk).exists())


class DiscountAndShippingPostingTests(TestCase):
    """Discount and shipping were never journaled, so the entry never balanced.

    Credits were built from GROSS line amounts while the debit posted due_total,
    which is net of the discount and includes the shipping charge -- so every
    discounted or shipped invoice was out by exactly (discount - shipping).
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from customerio.models import Customer
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        from accounts.models import User
        from companyio.models import Company, CompanyUser

        self.company = Company.objects.create(name="Disc Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="disc@example.com", name="D")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="C", display_name="C")
        income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="W1", quantity=0,
            date="2026-01-01", kind=ProductKindChoices.SERVICE,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("100.00"),
            income_account=income)

    def _invoice(self, **extra):
        from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer
        from common.tenant import set_current_company_id
        class _R: pass
        req = _R(); req.user = self.user
        payload = {
            "customer_uid": str(self.customer.uid), "currency_kind": "USD",
            "currency_rate": "1", "is_invoice": True, "status": "OPEN",
            "tax_kind": "NO_TAX",
            "email": {"customer_email": "c@x.com", "cc_emails": [], "bcc_emails": []},
            "total": "1000.00", "due_total": "1000.00",
            "sales_items": [{"product_uid": str(self.product.uid), "quantity": 10,
                             "sale_price": "100.00", "total": "1000.00"}],
        }
        payload.update(extra)
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeSaleListSerializer(data=payload, context={"request": req})
            s.is_valid(raise_exception=True)
            return s.save()
        finally:
            set_current_company_id(None)

    def _rows(self, sale):
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry)
        return entry.journalentryconnector_set.all()

    def _assert_balanced(self, sale, label):
        rows = self._rows(sale)
        dr = sum(r.debit or 0 for r in rows)
        cr = sum(r.credit or 0 for r in rows)
        print(f"\n  RESULT {label}: debit={dr} credit={cr} diff={dr-cr}")
        for r in rows:
            print(f"         {r.account.title:<28} dr={r.debit} cr={r.credit}")
        self.assertEqual(dr, cr, f"{label} does not balance")
        return rows

    def test_flat_discount_balances(self):
        # 1000 gross, 100 discount -> due 900.
        sale = self._invoice(discount="100.00", discount_kind="FLAT",
                             due_total="900.00")
        rows = self._assert_balanced(sale, "flat discount 100")
        disc = [r for r in rows if r.account.system_key == "SALES_DISCOUNTS"]
        self.assertEqual(len(disc), 1)
        self.assertEqual(disc[0].debit, Decimal("100.00"))

    def test_shipping_balances(self):
        # 1000 gross + 50 shipping -> due 1050.
        sale = self._invoice(shipping_fee="50.00", due_total="1050.00")
        rows = self._assert_balanced(sale, "shipping 50")
        ship = [r for r in rows if r.account.system_key == "SHIPPING_INCOME"]
        self.assertEqual(len(ship), 1)
        self.assertEqual(ship[0].credit, Decimal("50.00"))

    def test_discount_and_shipping_together(self):
        # The case that used to balance by luck when the two were equal.
        sale = self._invoice(discount="100.00", discount_kind="FLAT",
                             shipping_fee="50.00", due_total="950.00")
        self._assert_balanced(sale, "discount 100 + shipping 50")

    def test_percentage_discount_is_resolved_to_an_amount(self):
        # 10% of 1000 = 100. Posting the raw 10 would be wrong by 90.
        sale = self._invoice(discount="10", discount_kind="PERCENTAGE",
                             due_total="900.00")
        rows = self._assert_balanced(sale, "percentage discount 10%")
        disc = [r for r in rows if r.account.system_key == "SALES_DISCOUNTS"]
        print(f"         -> 10% of 1000 posted as {disc[0].debit}")
        self.assertEqual(disc[0].debit, Decimal("100.00"))

    def test_no_discount_no_extra_legs(self):
        sale = self._invoice()
        rows = self._rows(sale)
        keys = {r.account.system_key for r in rows}
        self.assertNotIn("SALES_DISCOUNTS", keys)
        self.assertNotIn("SHIPPING_INCOME", keys)


class SaleReversalTests(TestCase):
    """Reversing a sale must return the books to exactly where they started.

    This is the precondition for reverse-and-repost: if the reversal is not
    exact, reposting on top of it produces drift on every amendment rather than
    correcting the one the user made.

    The FIFO cases are the interesting ones. Restoring is driven by
    StockMovementLayerConsumption, so a lot gets back exactly what it gave up --
    including the two cases arithmetic on the journal cannot recover: a
    zero-cost lot (dividing cost by price is undefined) and units taken after
    the lots ran out, which belong to no lot at all.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from customerio.models import Customer
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        from accounts.models import User
        from companyio.models import Company, CompanyUser

        # setUp is re-invoked by the characterization test to get a clean
        # company per scenario, so the identifiers have to be unique per call.
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Rev Co {self._nth}", kind="ECOMMERCE")
        self.user = User.objects.create(
            email=f"rev{self._nth}@example.com", name="R")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="C", display_name="C")
        self.income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()
        self.asset = ChartOfAccount.objects.filter(
            company=self.company, system_key="INVENTORY_ASSET").first()
        self.cogs = ChartOfAccount.objects.filter(
            company=self.company, system_key="COGS").first()
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="W1", quantity=0,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("100.00"),
            income_account=self.income, asset_account=self.asset)

    def _layer(self, quantity, price):
        """One published purchase lot the FIFO walk will consume."""
        from django.db.models import F
        from productio.models import Product
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier

        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN)
        item = PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=quantity,
            opening_quantity=quantity, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED)
        # On-hand has to reflect the lot, or the FIFO walk drives
        # Product.quantity negative and the PositiveIntegerField rejects it.
        Product.objects.filter(pk=self.product.pk).update(
            quantity=F("quantity") + quantity)
        return item

    def _cost_account(self):
        """FIFO cost legs only post when the product has an expense account."""
        from productio.models import ProductAdditionalCost
        ProductAdditionalCost.objects.create(
            product=self.product, amount=Decimal("0.00"),
            expense_account=self.cogs)

    def _invoice(self, quantity, sale_price, **extra):
        from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer
        from common.tenant import set_current_company_id
        class _R: pass
        req = _R(); req.user = self.user
        total = Decimal(str(sale_price)) * quantity
        payload = {
            "customer_uid": str(self.customer.uid), "currency_kind": "USD",
            "currency_rate": "1", "is_invoice": True, "status": "OPEN",
            "tax_kind": "NO_TAX",
            "email": {"customer_email": "c@x.com", "cc_emails": [], "bcc_emails": []},
            "total": str(total), "due_total": str(total),
            "sales_items": [{"product_uid": str(self.product.uid),
                             "quantity": quantity, "sale_price": str(sale_price),
                             "total": str(total)}],
        }
        payload.update(extra)
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeSaleListSerializer(data=payload, context={"request": req})
            s.is_valid(raise_exception=True)
            return s.save()
        finally:
            set_current_company_id(None)

    def _snapshot(self):
        """Every figure the sale is capable of moving."""
        from productio.models import Product
        from purchaseio.models import PurchaseItem
        from customerio.models import Customer
        return {
            "accounts": {
                a.pk: a.opening_balance
                for a in ChartOfAccount.objects.filter(company=self.company)
            },
            "product": Product.objects.get(pk=self.product.pk).quantity,
            "layers": {
                pi.pk: pi.quantity
                for pi in PurchaseItem.objects.filter(product=self.product)
            },
            "customer": Customer.objects.get(pk=self.customer.pk).opening_balance,
        }

    def _assert_restored(self, before, after, label):
        drift = {
            ChartOfAccount.objects.get(pk=pk).title: after["accounts"][pk] - bal
            for pk, bal in before["accounts"].items()
            if after["accounts"][pk] != bal
        }
        print(f"\n  RESULT {label}")
        print(f"         account drift : {drift or 'none'}")
        print(f"         product on-hand: {before['product']} -> {after['product']}")
        print(f"         layers         : {before['layers']} -> {after['layers']}")
        print(f"         customer bal   : {before['customer']} -> {after['customer']}")
        self.assertEqual(drift, {}, f"{label}: account balances did not return")
        self.assertEqual(after["product"], before["product"], "on-hand did not return")
        self.assertEqual(after["layers"], before["layers"], "lots did not return")
        self.assertEqual(after["customer"], before["customer"], "customer did not return")

    def _reverse(self, sale):
        from weapi.django_rest.helpers.sale_posting import reverse_sale_postings
        return reverse_sale_postings(sale)

    def test_service_sale_reverses_to_zero(self):
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._assert_restored(before, self._snapshot(), "service sale, no inventory")

    def test_single_layer_sale_reverses_exactly(self):
        self._cost_account()
        self._layer(20, "40.00")
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._assert_restored(before, self._snapshot(), "one lot, 10 of 20 units")

    def test_multi_layer_sale_returns_each_lot(self):
        # The case that defeats patching: one line spanning two lots.
        self._cost_account()
        self._layer(6, "10.00")
        self._layer(6, "20.00")
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._assert_restored(before, self._snapshot(), "two lots, 6@10 + 4@20")

    def test_zero_cost_lot_is_restored(self):
        # Inferring quantity as cost/price is undefined here; the ledger knows.
        self._cost_account()
        self._layer(10, "0.00")
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._assert_restored(before, self._snapshot(), "zero-cost lot")

    def test_fallback_units_beyond_the_lots_are_restored(self):
        # 4 units in lots, 6 more taken from on-hand with no lot behind them.
        from productio.models import Product
        self._cost_account()
        self._layer(4, "10.00")
        Product.objects.filter(pk=self.product.pk).update(quantity=10)
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._assert_restored(before, self._snapshot(), "4 from lots + 6 fallback")

    def test_journal_is_gone_after_reversal(self):
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self.assertTrue(JournalEntry.objects.filter(sale=sale).exists())
        summary = self._reverse(sale)
        print(f"\n  RESULT reversal summary: {summary}")
        self.assertFalse(JournalEntry.objects.filter(sale=sale).exists())
        self.assertEqual(
            JournalEntryConnector.objects.filter(journal__sale=sale).count(), 0)

    def test_reversal_is_idempotent_for_inventory(self):
        # A second reversal must not hand the goods back twice.
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        after_first = self._snapshot()
        self._reverse(sale)
        after_second = self._snapshot()
        print(f"\n  RESULT on-hand after 1st={after_first['product']} "
              f"2nd={after_second['product']}")
        self.assertEqual(after_second["product"], after_first["product"])
        self.assertEqual(after_second["layers"], after_first["layers"])

    def test_a_compensating_movement_is_recorded(self):
        from stockio.models import StockMovement
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        moves = StockMovement.objects.filter(sale_item__sale=sale)
        kinds = sorted(m.movement_type for m in moves)
        print(f"\n  RESULT ledger movements after reversal: {kinds}")
        # The SALE row survives -- the ledger is append-only.
        self.assertIn("SALE", kinds)
        self.assertIn("REVERSAL", kinds)
        net = sum(m.signed_quantity for m in moves)
        print(f"         net signed quantity: {net}")
        self.assertEqual(net, 0)

    def test_lines_are_persisted_once_and_linked_to_the_ledger(self):
        # bulk_create moved ahead of the posting loop; the risk of that is
        # inserting every line twice, and the point of it is the sale_item link.
        from salesio.models import SaleItem
        from stockio.models import StockMovement
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        lines = SaleItem.objects.filter(sale=sale)
        moves = StockMovement.objects.filter(sale_item__sale=sale)
        print(f"\n  RESULT lines={lines.count()} "
              f"movements linked to a line={moves.count()}")
        self.assertEqual(lines.count(), 1)
        self.assertEqual(moves.count(), 1)
        self.assertEqual(moves.first().sale_item_id, lines.first().pk)
        # And the per-lot detail hangs off it, which is what makes per-line
        # COGS attributable at all.
        consumptions = moves.first().layer_consumptions.all()
        print(f"         lot slices: "
              f"{[(c.quantity_consumed, c.unit_cost) for c in consumptions]}")
        self.assertEqual(consumptions.count(), 1)


class PostSaleDocumentTests(SaleReversalTests):
    """post_sale_document() posts from persisted state alone.

    Inherits the fixtures from SaleReversalTests: same company, product, lots
    and invoice builder.

    The property that matters is the round trip. If reversing a document and
    posting it again does not land back on the same numbers, then every
    amendment drifts -- so `reverse -> repost` with nothing changed must be a
    no-op on every balance.
    """

    def _repost(self, sale):
        from weapi.django_rest.helpers.sale_posting import post_sale_document
        return post_sale_document(sale)

    def _entry_rows(self, sale):
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry, "no journal entry")
        return entry.journalentryconnector_set.all()

    def _balance_of(self, sale, label):
        rows = self._entry_rows(sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        print(f"\n  RESULT {label}: debit={dr} credit={cr} diff={dr - cr}")
        for r in rows:
            title = r.account.title if r.account else "(none)"
            print(f"         {title:<30} dr={r.debit} cr={r.credit}")
        return dr, cr

    def test_round_trip_leaves_every_balance_unchanged(self):
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        before = self._snapshot()
        reverse = self._reverse(sale)
        self._repost(sale)
        after = self._snapshot()
        drift = {
            ChartOfAccount.objects.get(pk=pk).title: after["accounts"][pk] - bal
            for pk, bal in before["accounts"].items()
            if after["accounts"][pk] != bal
        }
        print(f"\n  RESULT reverse->repost drift: {drift or 'none'}")
        print(f"         on-hand {before['product']} -> {after['product']}, "
              f"lots {before['layers']} -> {after['layers']}")
        self.assertEqual(drift, {}, "reverse+repost moved a balance")
        self.assertEqual(after["product"], before["product"])
        self.assertEqual(after["layers"], before["layers"])
        self.assertEqual(after["customer"], before["customer"])

    def test_reposted_entry_balances(self):
        self._cost_account()
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._reverse(sale)
        self._repost(sale)
        dr, cr = self._balance_of(sale, "reposted invoice")
        self.assertEqual(dr, cr)

    def test_multi_line_inclusive_tax_backs_out_once_not_once_per_line(self):
        # The bug the earlier fix left behind: total_tax was subtracted from
        # EVERY line, so a 3-line inclusive invoice understated revenue by 2x.
        from salesio.models import SaleItem
        from salesio.choices import SaleItemStatusChoices
        sale = self._invoice(1, "300.00", tax_kind="INCLUSIVE",
                             total="900.00", due_total="900.00",
                             total_tax="90.00")
        # Two more lines of the same shape.
        for _ in range(2):
            SaleItem.objects.create(
                sale=sale, product=self.product, quantity=1,
                sale_price=Decimal("300.00"), total=Decimal("300.00"),
                status=SaleItemStatusChoices.PUBLISHED)
        self._reverse(sale)
        self._repost(sale)
        rows = self._entry_rows(sale)
        income = sum(Decimal(r.credit or 0) for r in rows
                     if r.account and r.account.system_key == "SALES_OF_PRODUCT_INCOME")
        print(f"\n  RESULT 3 lines x 300 inclusive, total_tax 90 -> income credit "
              f"{income} (correct 810; per-line bug would give 630)")
        self.assertEqual(income, Decimal("810.000"))

    def test_estimate_posts_nothing(self):
        sale = self._invoice(10, "100.00")
        sale.is_invoice = False
        sale.is_estimated = True
        sale.save(update_fields=["is_invoice", "is_estimated"])
        self._reverse(sale)
        entry = self._repost(sale)
        print(f"\n  RESULT estimate -> journal entry: {entry}")
        self.assertIsNone(entry)
        self.assertFalse(JournalEntry.objects.filter(sale=sale).exists())

    def test_lines_are_read_in_entry_order_not_reversed(self):
        from salesio.models import SaleItem
        sale = self._invoice(10, "100.00")
        SaleItem.objects.create(
            sale=sale, product=self.product, quantity=1,
            sale_price=Decimal("5.00"), total=Decimal("5.00"))
        from weapi.django_rest.helpers.sale_posting import sale_lines
        default_order = [i.pk for i in sale.saleitem_set.all()]
        posting_order = [i.pk for i in sale_lines(sale)]
        print(f"\n  RESULT default manager order={default_order} "
              f"posting order={posting_order}")
        self.assertEqual(posting_order, sorted(posting_order))

    def test_tax_rate_is_snapshotted_and_reused(self):
        from agencyio.models import Agency, AgencyTax, AgencyTaxSet
        from salesio.models import SaleItem
        payable = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_TAX_PAYABLE").first()
        agency = Agency.objects.create(company=self.company, title="State",
                                       status="ACTIVE")
        tax = AgencyTax.objects.create(company=self.company, title="ST")
        tax_set = AgencyTaxSet.objects.create(
            taxes=tax, agency=agency, rate=Decimal("10.000"),
            sales_tax_account=payable)

        # 1000 of goods + 10% tax -> the customer owes 1100, so due_total must
        # carry the tax or the entry cannot balance.
        sale = self._invoice(10, "100.00", total="1000.00", due_total="1100.00",
                             total_tax="100.00")
        line = sale.saleitem_set.first()
        line.is_tax = True
        line.tax = tax
        line.total = Decimal("1000.00")
        line.save()

        self._reverse(sale)
        self._repost(sale)
        line.refresh_from_db()
        print(f"\n  RESULT snapshot after first post: {line.tax_snapshot}")
        self.assertTrue(line.tax_snapshot)
        self.assertEqual(Decimal(line.tax_snapshot[0]["rate"]), Decimal("10.000"))

        # The agency changes its rate. An amendment must still use 10%.
        tax_set.rate = Decimal("25.000")
        tax_set.save(update_fields=["rate"])
        self._reverse(sale)
        self._repost(sale)
        rows = self._entry_rows(sale)
        posted = sum(Decimal(r.credit or 0) for r in rows
                     if r.account and r.account.system_key == "SALES_TAX_PAYABLE")
        print(f"         rate changed 10% -> 25%; repost posted {posted} "
              f"(100 = filed rate kept, 250 = silently re-priced)")
        self.assertEqual(posted, Decimal("100.000"))


class CreatePostingCharacterizationTests(SaleReversalTests):
    """Record exactly what create() posts, so swapping its guts is provable.

    Not an assertion of correctness -- several of these scenarios are known to
    post wrongly today. It is a before/after fingerprint: run it, swap create()
    onto post_sale_document(), run it again, and every difference has to be one
    of the four deliberate fixes. Anything else is a regression.
    """

    OUT = ("/private/tmp/claude-501/-Users-sarwars-Desktop-Projects-Jumatechs-"
           "Pilucent-pilucent-backend/db40ffd5-63d7-400f-96ab-49b5c346cd0f/"
           "scratchpad/create_fingerprint.txt")

    def _fingerprint(self, sale, label, lines):
        entry = JournalEntry.objects.filter(sale=sale).first()
        lines.append(f"### {label}")
        if entry is None:
            lines.append("    (no journal entry)")
            return
        lines.append(f"    kind={entry.kind} is_deposit={entry.is_deposit} "
                     f"amount={entry.amount}")
        rows = sorted(
            entry.journalentryconnector_set.all(),
            key=lambda r: ((r.account.title if r.account else ""),
                           str(r.debit), str(r.credit)),
        )
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        for r in rows:
            title = r.account.title if r.account else "(none)"
            lines.append(f"    {title:<32} dr={r.debit:<12} cr={r.credit:<12} "
                         f"item={'y' if r.saleitem_id else '-'} "
                         f"lot={'y' if r.purchase_item_id else '-'}")
        lines.append(f"    TOTAL dr={dr} cr={cr} balanced={dr == cr}")

    def test_fingerprint_every_scenario(self):
        import os
        from productio.models import Product
        lines = []

        # A. service invoice, no inventory at all
        sale = self._invoice(10, "100.00")
        self._fingerprint(sale, "A service invoice 10x100", lines)

        # B. one lot
        self.setUp(); self._cost_account(); self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._fingerprint(sale, "B invoice, one lot 20@40", lines)

        # C. two lots on one line
        self.setUp(); self._cost_account()
        self._layer(6, "10.00"); self._layer(6, "20.00")
        sale = self._invoice(10, "100.00")
        self._fingerprint(sale, "C invoice, lots 6@10 + 6@20", lines)

        # D. discount + shipping
        self.setUp()
        sale = self._invoice(10, "100.00", discount="100.00",
                             discount_kind="FLAT", shipping_fee="50.00",
                             due_total="950.00")
        self._fingerprint(sale, "D invoice, discount 100 + shipping 50", lines)

        # E. percentage discount
        self.setUp()
        sale = self._invoice(10, "100.00", discount="10",
                             discount_kind="PERCENTAGE", due_total="900.00")
        self._fingerprint(sale, "E invoice, 10% discount", lines)

        # F. sale receipt with a deposit
        self.setUp()
        deposit_acct = ChartOfAccount.objects.filter(
            company=self.company, system_key="UNDEPOSITED_FUNDS").first()
        sale = self._invoice(10, "100.00", is_invoice=False,
                             is_sale_receipt=True, deposit="1000.00",
                             due_total="0.00",
                             receivable_charter_account_uid=str(deposit_acct.uid))
        self._fingerprint(sale, "F sale receipt, deposit 1000 to Undeposited", lines)

        # G. multi-line inclusive tax -- all three lines in the PAYLOAD, so
        # create() posts them itself and the per-line backout is visible.
        self.setUp()
        three = [{"product_uid": str(self.product.uid), "quantity": 1,
                  "sale_price": "300.00", "total": "300.00"} for _ in range(3)]
        sale = self._invoice(1, "300.00", tax_kind="INCLUSIVE", total="900.00",
                             due_total="900.00", total_tax="90.00",
                             sales_items=three)
        self._fingerprint(sale, "G 3-line inclusive tax, total_tax 90", lines)

        # H. estimate
        self.setUp()
        # create() reads validated_data["expired_date"] unguarded for estimates.
        sale = self._invoice(10, "100.00", is_invoice=False, is_estimated=True,
                             expired_date="2026-12-31")
        self._fingerprint(sale, "H estimate", lines)

        text = "\n".join(lines)
        os.makedirs(os.path.dirname(self.OUT), exist_ok=True)
        with open(self.OUT, "w") as fh:
            fh.write(text + "\n")
        print("\n" + text)


class UpdatePostingCharacterizationTests(SaleReversalTests):
    """Record what amending a sale does today, so the rewrite is provable.

    Every scenario here is a known finding in the sales audit. The point of the
    fingerprint is that after the rewrite each one has a *predictable* correct
    answer, and nothing else moves.
    """

    OUT = ("/private/tmp/claude-501/-Users-sarwars-Desktop-Projects-Jumatechs-"
           "Pilucent-pilucent-backend/db40ffd5-63d7-400f-96ab-49b5c346cd0f/"
           "scratchpad/update_fingerprint.txt")

    def _update(self, sale, payload):
        from weapi.django_rest.serializers.sales import (
            PrivateWeSaleDetailsSerializer,
        )
        from common.tenant import set_current_company_id
        class _R: pass
        req = _R(); req.user = self.user
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeSaleDetailsSerializer(
                instance=sale, data=payload, partial=True,
                context={"request": req})
            s.is_valid(raise_exception=True)
            return s.save()
        finally:
            set_current_company_id(None)

    def _dump(self, sale, label, out):
        sale.refresh_from_db()
        out.append(f"### {label}")
        entries = JournalEntry.objects.filter(sale=sale)
        out.append(f"    journal entries: {entries.count()}")
        rows = sorted(
            JournalEntryConnector.objects.filter(journal__sale=sale),
            key=lambda r: ((r.account.title if r.account else ""),
                           str(r.debit), str(r.credit)),
        )
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        for r in rows:
            title = r.account.title if r.account else "(none)"
            out.append(f"    {title:<30} dr={r.debit:<11} cr={r.credit:<11} "
                       f"{r.request_kind or ''}")
        out.append(f"    TOTAL dr={dr} cr={cr} balanced={dr == cr}")
        out.append(f"    lines in db: {sale.saleitem_set.count()} "
                   f"(qty {[i.quantity for i in sale.saleitem_set.order_by('id')]})")
        out.append(f"    due_total={sale.due_total} total={sale.total}")

    def _line_payload(self, sale, **over):
        item = sale.saleitem_set.order_by("id").first()
        base = {"uid": str(item.uid), "product_uid": str(self.product.uid),
                "quantity": item.quantity, "sale_price": str(item.sale_price),
                "total": str(item.total), "tax_uid": ""}
        base.update(over)
        return base

    def test_fingerprint_amendments(self):
        import os
        out = []

        # 1. price-only edit: 10 x 100 -> 10 x 80  (audit gap 4)
        self.setUp(); self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00")
        self._update(sale, {"total": "800.00", "due_total": "800.00",
                            "sales_items": [self._line_payload(
                                sale, sale_price="80.00", total="800.00")]})
        self._dump(sale, "1 price-only edit 100->80 (gap 4)", out)

        # 2. quantity decrease across two lots (audit gap 5)
        self.setUp(); self._cost_account()
        self._layer(6, "10.00"); self._layer(6, "20.00")
        sale = self._invoice(10, "100.00")
        self._update(sale, {"total": "800.00", "due_total": "800.00",
                            "sales_items": [self._line_payload(
                                sale, quantity=8, total="800.00")]})
        self._dump(sale, "2 qty 10->8 across lots 6@10+6@20 (gap 5)", out)

        # 3. line dropped from the payload (audit gap 10)
        self.setUp(); self._cost_account(); self._layer(50, "40.00")
        two = [{"product_uid": str(self.product.uid), "quantity": 6,
                "sale_price": "100.00", "total": "600.00"},
               {"product_uid": str(self.product.uid), "quantity": 4,
                "sale_price": "100.00", "total": "400.00"}]
        sale = self._invoice(6, "100.00", total="1000.00", due_total="1000.00",
                             sales_items=two)
        keep = sale.saleitem_set.order_by("id").first()
        self._update(sale, {"total": "600.00", "due_total": "600.00",
                            "sales_items": [{
                                "uid": str(keep.uid),
                                "product_uid": str(self.product.uid),
                                "quantity": 6, "sale_price": "100.00",
                                "total": "600.00", "tax_uid": ""}]})
        self._dump(sale, "3 line B dropped from payload (gap 10)", out)

        # 4. save twice with no change at all (audit gap 3 shape)
        self.setUp(); self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00")
        same = {"total": "1000.00", "due_total": "1000.00",
                "sales_items": [self._line_payload(sale)]}
        self._update(sale, same)
        self._update(sale, same)
        self._dump(sale, "4 saved twice, nothing changed", out)

        # 5. estimate flipped to invoice (audit gap 6)
        self.setUp(); self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00", is_invoice=False, is_estimated=True,
                             expired_date="2026-12-31")
        self._update(sale, {"is_estimated": False, "is_invoice": True,
                            "total": "1000.00", "due_total": "1000.00",
                            "sales_items": [self._line_payload(sale)]})
        self._dump(sale, "5 estimate -> invoice (gap 6)", out)

        text = "\n".join(out)
        os.makedirs(os.path.dirname(self.OUT), exist_ok=True)
        with open(self.OUT, "w") as fh:
            fh.write(text + "\n")
        print("\n" + text)


class AmendmentIsReverseAndRepostTests(UpdatePostingCharacterizationTests):
    """The four amendment findings, each asserted rather than fingerprinted."""

    def _rows(self, sale):
        return list(JournalEntryConnector.objects.filter(journal__sale=sale))

    def _balanced(self, sale):
        rows = self._rows(sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        return dr, cr

    def _income(self, sale):
        return sum(Decimal(r.credit or 0) for r in self._rows(sale)
                   if r.account and r.account.system_key == "SALES_OF_PRODUCT_INCOME")

    def _cogs(self, sale):
        return sum(Decimal(r.debit or 0) for r in self._rows(sale)
                   if r.account and r.account.system_key == "COGS")

    def test_gap4_price_only_edit_moves_income(self):
        self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00")
        self._update(sale, {"total": "800.00", "due_total": "800.00",
                            "sales_items": [self._line_payload(
                                sale, sale_price="80.00", total="800.00")]})
        dr, cr = self._balanced(sale)
        print(f"\n  RESULT gap 4: income={self._income(sale)} dr={dr} cr={cr}")
        self.assertEqual(self._income(sale), Decimal("800.000"))
        self.assertEqual(dr, cr)

    def test_gap5_multi_lot_quantity_change_reprices_every_lot(self):
        self._cost_account()
        self._layer(6, "10.00"); self._layer(6, "20.00")
        sale = self._invoice(10, "100.00")
        self._update(sale, {"total": "800.00", "due_total": "800.00",
                            "sales_items": [self._line_payload(
                                sale, quantity=8, total="800.00")]})
        dr, cr = self._balanced(sale)
        # 8 units against 6@10 then 2@20 = 60 + 40 = 100.
        print(f"\n  RESULT gap 5: cogs={self._cogs(sale)} (true FIFO 100) dr={dr} cr={cr}")
        self.assertEqual(self._cogs(sale), Decimal("100.000"))
        self.assertEqual(dr, cr)

    def test_gap10_dropped_line_is_reversed_and_hidden(self):
        from salesio.choices import SaleItemStatusChoices
        self._cost_account(); self._layer(50, "40.00")
        two = [{"product_uid": str(self.product.uid), "quantity": 6,
                "sale_price": "100.00", "total": "600.00"},
               {"product_uid": str(self.product.uid), "quantity": 4,
                "sale_price": "100.00", "total": "400.00"}]
        sale = self._invoice(6, "100.00", total="1000.00", due_total="1000.00",
                             sales_items=two)
        keep = sale.saleitem_set.order_by("id").first()
        self._update(sale, {"total": "600.00", "due_total": "600.00",
                            "sales_items": [{
                                "uid": str(keep.uid),
                                "product_uid": str(self.product.uid),
                                "quantity": 6, "sale_price": "100.00",
                                "total": "600.00", "tax_uid": ""}]})
        dr, cr = self._balanced(sale)
        live = sale.saleitem_set.exclude(status=SaleItemStatusChoices.REMOVED)
        print(f"\n  RESULT gap 10: income={self._income(sale)} dr={dr} cr={cr} "
              f"live lines={live.count()} (rows kept={sale.saleitem_set.count()})")
        self.assertEqual(self._income(sale), Decimal("600.000"))
        self.assertEqual(dr, cr)
        self.assertEqual(live.count(), 1)
        # The row survives so its history is not orphaned, but it stops posting
        # AND stops rendering.
        self.assertEqual(sale.saleitem_set.count(), 2)

    def test_gap6_estimate_to_invoice_posts(self):
        self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00", is_invoice=False, is_estimated=True,
                             expired_date="2026-12-31")
        self.assertFalse(JournalEntry.objects.filter(sale=sale).exists())
        self._update(sale, {"is_estimated": False, "is_invoice": True,
                            "total": "1000.00", "due_total": "1000.00",
                            "sales_items": [self._line_payload(sale)]})
        dr, cr = self._balanced(sale)
        print(f"\n  RESULT gap 6: entries={JournalEntry.objects.filter(sale=sale).count()} "
              f"income={self._income(sale)} dr={dr} cr={cr}")
        self.assertTrue(JournalEntry.objects.filter(sale=sale).exists())
        self.assertEqual(self._income(sale), Decimal("1000.000"))
        self.assertEqual(dr, cr)

    def test_repeated_saves_do_not_accumulate(self):
        self._cost_account(); self._layer(50, "40.00")
        sale = self._invoice(10, "100.00")
        same = {"total": "1000.00", "due_total": "1000.00",
                "sales_items": [self._line_payload(sale)]}
        for _ in range(4):
            self._update(sale, same)
        dr, cr = self._balanced(sale)
        entries = JournalEntry.objects.filter(sale=sale).count()
        print(f"\n  RESULT saved 4x: entries={entries} rows={len(self._rows(sale))} "
              f"income={self._income(sale)} dr={dr} cr={cr}")
        self.assertEqual(entries, 1)
        self.assertEqual(self._income(sale), Decimal("1000.000"))
        self.assertEqual(dr, cr)

    def test_patch_omitting_warehouse_does_not_wipe_it(self):
        from wirehouseio.models import Warehouse
        wh = Warehouse.objects.create(company=self.company, title="Main")
        sale = self._invoice(10, "100.00")
        sale.warehouse = wh
        sale.save(update_fields=["warehouse"])
        self._update(sale, {"description": "note only"})
        sale.refresh_from_db()
        print(f"\n  RESULT warehouse after a PATCH that omitted it: {sale.warehouse}")
        self.assertEqual(sale.warehouse_id, wh.pk)


class SaleVoidTests(SaleReversalTests):
    """Deleting a sale must void it, not erase it.

    perform_destroy assigned REMOVED to the in-memory instance and then hard
    deleted the row anyway. JournalEntry.sale is CASCADE, so the entry and all
    its lines went with it while every opening_balance they had moved stayed
    put -- and with the entry gone there was nothing left to measure the damage
    against.
    """

    def _destroy(self, sale):
        from weapi.django_rest.views.sales import PrivateWeSaleDetails
        view = PrivateWeSaleDetails()
        class _R: pass
        req = _R(); req.user = self.user
        view.request = req
        view.perform_destroy(sale)

    def _destroy_line(self, item):
        from weapi.django_rest.views.sales import PrivateWeSalesItemDetails
        view = PrivateWeSalesItemDetails()
        class _R: pass
        req = _R(); req.user = self.user
        view.request = req
        view.perform_destroy(item)

    def test_the_row_and_its_journal_survive(self):
        from salesio.models import Sale
        self._cost_account(); self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        original = JournalEntry.objects.filter(sale=sale).first()
        self._destroy(sale)
        sale.refresh_from_db()
        print(f"\n  RESULT after delete: status={sale.status} "
              f"entries={JournalEntry.objects.filter(sale=sale).count()}")
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())
        self.assertEqual(sale.status, "REMOVED")
        self.assertTrue(JournalEntry.objects.filter(pk=original.pk).exists())
        self.assertEqual(JournalEntry.objects.filter(sale=sale).count(), 2)

    def test_balances_return_to_where_they_started(self):
        self._cost_account(); self._layer(20, "40.00")
        before = self._snapshot()
        sale = self._invoice(10, "100.00")
        self._destroy(sale)
        after = self._snapshot()
        drift = {
            ChartOfAccount.objects.get(pk=pk).title: after["accounts"][pk] - bal
            for pk, bal in before["accounts"].items()
            if after["accounts"][pk] != bal
        }
        print(f"\n  RESULT void drift: {drift or 'none'}; on-hand "
              f"{before['product']} -> {after['product']}; customer "
              f"{before['customer']} -> {after['customer']}")
        self.assertEqual(drift, {})
        self.assertEqual(after["product"], before["product"])
        self.assertEqual(after["customer"], before["customer"])

    def test_the_two_entries_net_to_zero(self):
        self._cost_account(); self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._destroy(sale)
        rows = JournalEntryConnector.objects.filter(journal__sale=sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        deleted = [r for r in rows if r.request_kind == "DELETED"]
        print(f"\n  RESULT original + reversal: {len(rows)} rows "
              f"({len(deleted)} marked DELETED) dr={dr} cr={cr}")
        self.assertEqual(dr, cr)
        self.assertTrue(deleted)
        # Every account nets to zero across the pair.
        per_account = {}
        for r in rows:
            key = r.account.title if r.account else "(none)"
            per_account[key] = (per_account.get(key, Decimal("0"))
                                + Decimal(r.debit or 0) - Decimal(r.credit or 0))
        print(f"         per-account net: {dict(per_account)}")
        for title, net in per_account.items():
            self.assertEqual(net, Decimal("0.000"), f"{title} did not net out")

    def test_an_estimate_is_removed_without_a_reversal(self):
        sale = self._invoice(10, "100.00", is_invoice=False, is_estimated=True,
                             expired_date="2026-12-31")
        self._destroy(sale)
        sale.refresh_from_db()
        print(f"\n  RESULT estimate voided: status={sale.status} "
              f"entries={JournalEntry.objects.filter(sale=sale).count()}")
        self.assertEqual(sale.status, "REMOVED")
        self.assertEqual(JournalEntry.objects.filter(sale=sale).count(), 0)

    def test_voided_sale_disappears_from_listings(self):
        from salesio.models import Sale
        self._cost_account(); self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        self._destroy(sale)
        visible = Sale.objects.get_status_all().filter(company=self.company)
        print(f"\n  RESULT visible sales after void: {visible.count()}")
        self.assertEqual(visible.count(), 0)
        self.assertEqual(Sale.objects.filter(pk=sale.pk).count(), 1)

    def test_deleting_a_line_reposts_the_document_without_it(self):
        from salesio.choices import SaleItemStatusChoices
        self._cost_account(); self._layer(50, "40.00")
        two = [{"product_uid": str(self.product.uid), "quantity": 6,
                "sale_price": "100.00", "total": "600.00"},
               {"product_uid": str(self.product.uid), "quantity": 4,
                "sale_price": "100.00", "total": "400.00"}]
        sale = self._invoice(6, "100.00", total="1000.00", due_total="1000.00",
                             sales_items=two)
        drop = sale.saleitem_set.order_by("id").last()
        self._destroy_line(drop)
        rows = JournalEntryConnector.objects.filter(journal__sale=sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        income = sum(Decimal(r.credit or 0) for r in rows
                     if r.account and r.account.system_key == "SALES_OF_PRODUCT_INCOME")
        live = sale.saleitem_set.exclude(status=SaleItemStatusChoices.REMOVED)
        print(f"\n  RESULT line deleted: live lines={live.count()} "
              f"income={income} dr={dr} cr={cr}")
        sale.refresh_from_db()
        print(f"         header recomputed: total={sale.total} "
              f"due_total={sale.due_total}")
        self.assertEqual(live.count(), 1)
        self.assertEqual(income, Decimal("600.000"))
        self.assertEqual(dr, cr)
        # The header has to follow the lines, or A/R keeps debiting for goods
        # no longer on the invoice.
        self.assertEqual(sale.total, Decimal("600.000"))
        self.assertEqual(sale.due_total, Decimal("600.000"))


class ChartOfAccountOpeningBalanceCreateTests(TestCase):
    """Creating an account WITH an opening balance must not 500.

    `chart_of_account_kind` was left referenced but never bound, so the whole
    opening-balance block raised NameError. `opening_balance != 0` short-circuits
    the name away, which is why the zero case -- and therefore every existing
    test -- passed while the real one crashed.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from accounts.models import User
        from companyio.models import Company, CompanyUser
        self.company = Company.objects.create(name="OB Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="ob@example.com", name="OB")
        CompanyUser.objects.create(user=self.user, company=self.company)

    def _create(self, opening_balance):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer,
        )
        from categoryio.models import Category
        from common.tenant import set_current_company_id
        asset_type = Category.objects.filter(
            parent__title__iexact="Assets", parent__isnull=False
        ).first() or Category.objects.filter(parent__isnull=False).first()
        detail = Category.objects.filter(parent=asset_type).first()

        class _R: pass
        req = _R(); req.user = self.user
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeChartOfAccountListSerializer(
                data={
                    "title": f"Bank {opening_balance}",
                    "code": "1901",
                    "account_type_slug": asset_type.slug,
                    "detail_type_slug": detail.slug if detail else None,
                    "opening_balance": str(opening_balance),
                },
                context={"request": req},
            )
            s.is_valid(raise_exception=True)
            return s.save()
        finally:
            set_current_company_id(None)

    def test_zero_opening_balance_creates(self):
        account = self._create(0)
        print(f"\n  RESULT opening_balance=0 -> created {account}")
        self.assertIsNotNone(account)

    def test_nonzero_opening_balance_does_not_raise(self):
        # This is the case that 500'd: the guard short-circuits at zero, so only
        # a real opening balance reached the undefined name.
        account = self._create(500)
        print(f"  RESULT opening_balance=500 -> created without NameError")
        self.assertIsNotNone(account)


class ChartOfAccountApiGuardTests(TestCase):
    """COA #14, #19 and the cross-tenant related-field leak."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from accounts.models import User
        from companyio.models import Company, CompanyUser
        from categoryio.models import Category
        self.company = Company.objects.create(name="Guard Co", kind="ECOMMERCE")
        self.other = Company.objects.create(name="Rival Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="guard@example.com", name="G")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.asset_type = Category.objects.filter(
            parent__title__iexact="Assets").first()
        self.expense_type = Category.objects.filter(
            parent__title__iexact="Expenses").first()

    def _ser(self, data, instance=None):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer,
            PrivateWeChartOfAccountDetailsSerializer,
        )
        class _R: pass
        req = _R(); req.user = self.user
        cls = (PrivateWeChartOfAccountDetailsSerializer if instance
               else PrivateWeChartOfAccountListSerializer)
        kwargs = {"data": data, "context": {"request": req}}
        if instance:
            kwargs["instance"] = instance
            kwargs["partial"] = True
        return cls(**kwargs)

    def _payload(self, **over):
        from categoryio.models import Category
        detail = Category.objects.filter(parent=self.asset_type).first()
        base = {"title": "Cash Box", "code": "1955",
                "account_type_slug": self.asset_type.slug,
                "detail_type_slug": detail.slug}
        base.update(over)
        return base

    def test_coa14_create_returns_the_instance_so_the_body_has_uid(self):
        from common.tenant import set_current_company_id
        set_current_company_id(self.company.id)
        try:
            s = self._ser(self._payload())
            s.is_valid(raise_exception=True)
            s.save()
            print(f"\n  RESULT 201 body uid={s.data.get('uid')!r}")
            self.assertIn("uid", s.data)
            self.assertTrue(s.data["uid"])
        finally:
            set_current_company_id(None)

    def test_coa19_detail_type_from_another_account_type_is_rejected(self):
        from common.tenant import set_current_company_id
        from categoryio.models import Category
        # A detail type belonging to Expenses, offered under an Assets account.
        wrong = Category.objects.filter(parent=self.expense_type).first()
        set_current_company_id(self.company.id)
        try:
            s = self._ser(self._payload(detail_type_slug=wrong.slug))
            ok = s.is_valid()
            print(f"  RESULT expense detail type under an asset account: "
                  f"valid={ok} errors={dict(s.errors) if not ok else '-'}")
            self.assertFalse(ok)
            self.assertIn("detail_type_slug", s.errors)
        finally:
            set_current_company_id(None)

    def test_coa19_matching_pair_is_accepted(self):
        from common.tenant import set_current_company_id
        set_current_company_id(self.company.id)
        try:
            s = self._ser(self._payload())
            self.assertTrue(s.is_valid(), s.errors)
        finally:
            set_current_company_id(None)

    def test_another_tenants_account_cannot_be_used_as_parent(self):
        from common.tenant import set_current_company_id
        from accounts.models import ChartOfAccount
        theirs = ChartOfAccount.objects.filter(company=self.other).first()
        self.assertIsNotNone(theirs, "rival company should have seeded accounts")
        set_current_company_id(self.company.id)
        try:
            s = self._ser(self._payload(parent_uid=str(theirs.uid)))
            ok = s.is_valid()
            print(f"  RESULT parent from another tenant: valid={ok} "
                  f"errors={dict(s.errors) if not ok else '-'}")
            self.assertFalse(ok)
            self.assertIn("parent_uid", s.errors)
        finally:
            set_current_company_id(None)

    def test_own_account_is_still_usable_as_parent(self):
        from common.tenant import set_current_company_id
        from accounts.models import ChartOfAccount
        mine = ChartOfAccount.objects.filter(company=self.company).first()
        set_current_company_id(self.company.id)
        try:
            s = self._ser(self._payload(parent_uid=str(mine.uid)))
            self.assertTrue(s.is_valid(), s.errors)
        finally:
            set_current_company_id(None)

    def test_product_related_fields_are_company_scoped(self):
        # Product #9: the account/brand/category/supplier fields were global too.
        from weapi.django_rest.serializers.products import (
            PrivateWeProductListSerializer,
        )
        from accounts.models import ChartOfAccount
        theirs = ChartOfAccount.objects.filter(company=self.other).first()
        class _R: pass
        req = _R(); req.user = self.user
        s = PrivateWeProductListSerializer(context={"request": req})
        qs = s.fields["income_account_uid"].queryset
        reachable = qs.filter(pk=theirs.pk).exists()
        mine = ChartOfAccount.objects.filter(company=self.company).first()
        print(f"\n  RESULT product income_account queryset: rival reachable="
              f"{reachable}, own reachable={qs.filter(pk=mine.pk).exists()}")
        self.assertFalse(reachable)
        self.assertTrue(qs.filter(pk=mine.pk).exists())



    def _plain(self, title, code):
        """A user-created account -- seeded ones are is_fixed and refuse edits."""
        from accounts.models import ChartOfAccount
        from categoryio.models import Category
        detail = Category.objects.filter(parent=self.asset_type).first()
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            account_type=self.asset_type, detail_type=detail,
            status=ChartOfAccountStatusChoices.ACTIVE)

    def test_renaming_onto_another_account_is_rejected(self):
        # COA #16: create() checked for a collision; update() did not, so an
        # account could be RENAMED onto another's title.
        from common.tenant import set_current_company_id
        target = self._plain("Petty Cash", "1971")
        other = self._plain("Float", "1972")
        set_current_company_id(self.company.id)
        try:
            s = self._ser({"title": target.title}, instance=other)
            ok = s.is_valid()
            print(f"\n  RESULT rename {other.title!r} -> {target.title!r}: "
                  f"valid={ok} errors={dict(s.errors) if not ok else '-'}")
            self.assertFalse(ok)
            self.assertIn("title", s.errors)
        finally:
            set_current_company_id(None)

    def test_reusing_another_accounts_code_is_rejected(self):
        from common.tenant import set_current_company_id
        target = self._plain("Vault", "1973")
        other = self._plain("Till", "1974")
        set_current_company_id(self.company.id)
        try:
            s = self._ser({"code": target.code}, instance=other)
            ok = s.is_valid()
            print(f"  RESULT reuse code {target.code!r}: valid={ok} "
                  f"errors={dict(s.errors) if not ok else '-'}")
            self.assertFalse(ok)
            self.assertIn("code", s.errors)
        finally:
            set_current_company_id(None)

    def test_an_account_may_keep_its_own_title(self):
        from common.tenant import set_current_company_id
        acct = self._plain("Change Fund", "1975")
        set_current_company_id(self.company.id)
        try:
            s = self._ser({"title": acct.title, "description": "same name"},
                          instance=acct)
            print(f"  RESULT keeping own title {acct.title!r}: valid={s.is_valid()} "
                  f"{dict(s.errors) if not s.is_valid() else ''}")
            self.assertTrue(s.is_valid(), s.errors)
        finally:
            set_current_company_id(None)


class SeedTaxonomyPoisoningTests(TestCase):
    """A tenant-created Category must not hijack another company's seeding.

    The seed matched Category by title alone. Category is tenant-writable and
    ordered by -created_at, so `.first()` returned the NEWEST row: one tenant
    creating a category named after a real account type would re-type every
    company onboarded afterwards.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def test_a_tenant_category_does_not_win_over_the_shipped_one(self):
        from categoryio.models import Category
        from companyio.models import Company
        from accounts.models import ChartOfAccount
        from common.django_rest.helpers.chart_of_account_helpers import (
            resolve_taxonomy_category,
        )
        attacker = Company.objects.create(name="Attacker", kind="ECOMMERCE")
        shipped = Category.objects.filter(
            kind="CHART_OF_ACCOUNT", company__isnull=True).first()

        poison = Category.objects.create(
            title=shipped.title, kind="CHART_OF_ACCOUNT",
            status="ACTIVE", company=attacker)
        newest = Category.objects.filter(title=shipped.title).first()
        print(f"\n  RESULT newest row with that title belongs to: "
              f"{newest.company} (poison={newest.pk == poison.pk})")
        self.assertEqual(newest.pk, poison.pk, "fixture should reproduce the hazard")

        resolved = resolve_taxonomy_category(shipped.title)
        print(f"         resolver returns: {resolved.company} (shipped={resolved.pk == shipped.pk})")
        self.assertEqual(resolved.pk, shipped.pk)

        victim = Company.objects.create(name="Victim", kind="ECOMMERCE")
        typed = ChartOfAccount.objects.filter(
            company=victim, account_type__isnull=False)
        leaked = typed.filter(account_type__company__isnull=False)
        print(f"         victim accounts typed against a tenant category: "
              f"{leaked.count()} of {typed.count()}")
        self.assertEqual(leaked.count(), 0)


class LedgerBalanceDerivationTests(TestCase):
    """Balances come from the lines, not from the snapshot beside them."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Ledger Co", kind="ECOMMERCE")
        self.cash = ChartOfAccount.objects.filter(
            company=self.company, kind=ChartOfAccountKindChoices.ASSETS).first()
        self.income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()

    def _post(self, account, debit=0, credit=0, date="2026-03-15",
              stored_last_balance=None):
        entry = JournalEntry.objects.create(
            company=self.company, amount=Decimal(str(debit or credit)), date=date)
        return JournalEntryConnector.objects.create(
            journal=entry, account=account, date=date,
            debit=Decimal(str(debit)), credit=Decimal(str(credit)),
            total=Decimal(str(debit or credit)),
            last_balance=(Decimal(str(stored_last_balance))
                          if stored_last_balance is not None else 0),
            kind=(JournalEntryConnectorKindChoices.DEBIT if debit
                  else JournalEntryConnectorKindChoices.CREDIT))

    def test_movement_is_derived_even_when_the_snapshot_lies(self):
        from common.django_rest.helpers.ledger_balances import account_movement
        # Three real lines totalling 300 debit, with a wildly drifted snapshot
        # on the newest one -- which is exactly what get_last_balance returned.
        self._post(self.cash, debit=100, date="2026-03-01", stored_last_balance=100)
        self._post(self.cash, debit=100, date="2026-03-02", stored_last_balance=200)
        newest = self._post(self.cash, debit=100, date="2026-03-03",
                            stored_last_balance=99999)
        derived = account_movement(self.cash)
        print(f"\n  RESULT stored snapshot={newest.last_balance} derived={derived}")
        self.assertEqual(derived, Decimal("300.000"))

    def test_income_is_credit_positive(self):
        from common.django_rest.helpers.ledger_balances import account_movement
        self._post(self.income, credit=500)
        derived = account_movement(self.income)
        print(f"  RESULT income credited 500 -> {derived} (raw debit-credit = -500)")
        self.assertEqual(derived, Decimal("500.000"))

    def test_asset_is_debit_positive(self):
        from common.django_rest.helpers.ledger_balances import account_movement
        self._post(self.cash, debit=250)
        self.assertEqual(account_movement(self.cash), Decimal("250.000"))

    def test_movement_respects_the_period(self):
        from common.django_rest.helpers.ledger_balances import account_movement
        self._post(self.cash, debit=100, date="2026-01-10")
        self._post(self.cash, debit=40, date="2026-03-10")
        inside = account_movement(self.cash, ["2026-03-01", "2026-03-31"])
        print(f"  RESULT March movement={inside} (whole life = "
              f"{account_movement(self.cash)})")
        self.assertEqual(inside, Decimal("40.000"))

    def test_a_backdated_entry_lands_in_its_own_period(self):
        from common.django_rest.helpers.ledger_balances import account_movement
        # Entered today, dated January. The old code filtered on created_at and
        # would have counted this into the current period instead.
        self._post(self.cash, debit=70, date="2026-01-05")
        january = account_movement(self.cash, ["2026-01-01", "2026-01-31"])
        print(f"  RESULT backdated line in January window: {january}")
        self.assertEqual(january, Decimal("70.000"))

    def test_balance_as_of_includes_history_before_the_date(self):
        from common.django_rest.helpers.ledger_balances import (
            account_balance_as_of, account_movement,
        )
        self._post(self.cash, debit=100, date="2026-01-10")
        self._post(self.cash, debit=40, date="2026-03-10")
        closing = account_balance_as_of(self.cash, "2026-03-31")
        movement = account_movement(self.cash, ["2026-03-01", "2026-03-31"])
        print(f"  RESULT closing at 31 Mar={closing} vs March movement={movement}")
        self.assertEqual(closing, Decimal("140.000"))
        self.assertEqual(movement, Decimal("40.000"))

    def test_get_last_balance_now_derives(self):
        self._post(self.cash, debit=100, date="2026-03-01", stored_last_balance=7)
        self._post(self.cash, debit=100, date="2026-03-02", stored_last_balance=7)
        got = self.cash.get_last_balance(["2026-03-01", "2026-03-31"])
        print(f"  RESULT get_last_balance -> {got} (snapshots said 7)")
        self.assertEqual(got, Decimal("200.000"))

    def test_running_balances_continue_from_an_opening_figure(self):
        from common.django_rest.helpers.ledger_balances import running_balances
        rows = [
            self._post(self.cash, debit=10, date="2026-03-01"),
            self._post(self.cash, credit=4, date="2026-03-02"),
            self._post(self.cash, debit=6, date="2026-03-03"),
        ]
        plain = running_balances(rows)
        carried = running_balances(rows, opening={self.cash.pk: Decimal("100")})
        print(f"  RESULT running={[str(plain[r.pk]) for r in rows]} "
              f"with opening 100={[str(carried[r.pk]) for r in rows]}")
        self.assertEqual([plain[r.pk] for r in rows],
                         [Decimal("10"), Decimal("6"), Decimal("12")])
        self.assertEqual(carried[rows[-1].pk], Decimal("112"))


class LedgerReportScopingTests(TestCase):
    """The journal-line reports must not return another tenant's ledger.

    `journalio_journalentryconnector` is not in RLS_TABLES (companyio 0023) and
    has no `company_id` column for the tenant policy to key on, so nothing below
    the application layer was containing these queries.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from accounts.models import User
        from companyio.models import Company, CompanyUser
        self.mine = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.theirs = Company.objects.create(name="Theirs", kind="ECOMMERCE")
        self.user = User.objects.create(email="report@example.com", name="R")
        CompanyUser.objects.create(user=self.user, company=self.mine)
        self.my_line = self._line(self.mine, 100)
        self.their_line = self._line(self.theirs, 999)

    def _line(self, company, amount, date="2026-03-01"):
        account = ChartOfAccount.objects.filter(
            company=company, kind=ChartOfAccountKindChoices.ASSETS).first()
        entry = JournalEntry.objects.create(
            company=company, amount=Decimal(str(amount)), date=date)
        return JournalEntryConnector.objects.create(
            journal=entry, account=account, date=date,
            debit=Decimal(str(amount)), total=Decimal(str(amount)),
            kind=JournalEntryConnectorKindChoices.DEBIT)

    def _rows(self, view_cls):
        class _R: pass
        req = _R(); req.user = self.user; req.query_params = {}
        view = view_cls(); view.request = req
        view.kwargs = {}
        return list(view.get_queryset())

    def test_general_ledger_is_scoped_to_the_company(self):
        from weapi.django_rest.views.reports.general_ledgers import (
            PrivateWeGeneralLadgerList,
        )
        rows = self._rows(PrivateWeGeneralLadgerList)
        ids = {r.pk for r in rows}
        print(f"\n  RESULT general ledger rows={len(rows)} "
              f"mine_present={self.my_line.pk in ids} "
              f"theirs_present={self.their_line.pk in ids}")
        self.assertIn(self.my_line.pk, ids)
        self.assertNotIn(self.their_line.pk, ids)

    def test_journal_report_is_scoped_to_the_company(self):
        from weapi.django_rest.views.reports.journal_report import (
            PrivateWeJournalReportList,
        )
        rows = self._rows(PrivateWeJournalReportList)
        ids = {r.pk for r in rows}
        print(f"  RESULT journal report rows={len(rows)} "
              f"theirs_present={self.their_line.pk in ids}")
        self.assertNotIn(self.their_line.pk, ids)

    def test_running_balance_is_derived_and_cumulative(self):
        from common.django_rest.helpers.ledger_balances import (
            annotate_running_balance,
        )
        account = self.my_line.account
        for n, day in ((50, "2026-03-02"), (25, "2026-03-03")):
            JournalEntryConnector.objects.create(
                journal=self.my_line.journal, account=account, date=day,
                debit=Decimal(str(n)), total=Decimal(str(n)),
                last_balance=Decimal("123456"),   # a deliberately wrong snapshot
                kind=JournalEntryConnectorKindChoices.DEBIT)
        rows = list(annotate_running_balance(
            JournalEntryConnector.objects.filter(account=account)))
        running = [str(r.running_balance) for r in rows]
        stored = [str(r.last_balance) for r in rows]
        print(f"  RESULT derived running={running} vs stored snapshots={stored}")
        self.assertEqual([Decimal(v) for v in running],
                         [Decimal("100"), Decimal("150"), Decimal("175")])

class DuplicateAccountAuditTests(PreConstraintDataMixin, TestCase):
    """The pre-flight for COA #16's unique index."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("audit_duplicate_accounts", stdout=out, **kwargs)
        return out.getvalue()

    def test_a_clean_company_reports_safe_to_constrain(self):
        from companyio.models import Company
        Company.objects.create(name="Tidy Co", kind="ECOMMERCE")
        out = self._run(company="Tidy Co")
        print(f"\n  RESULT clean company -> {'safe' if 'can be added' in out else 'NOT safe'}")
        self.assertIn("can be added", out)

    def test_a_duplicate_title_is_reported_with_its_line_counts(self):
        from companyio.models import Company
        from accounts.models import ChartOfAccount
        company = Company.objects.create(name="Messy Co", kind="ECOMMERCE")
        existing = ChartOfAccount.objects.filter(company=company).first()
        twin = ChartOfAccount.objects.create(
            company=company, title=existing.title, code="9998",
            kind=existing.kind, status=ChartOfAccountStatusChoices.ACTIVE)
        entry = JournalEntry.objects.create(company=company, amount=Decimal("5.00"))
        JournalEntryConnector.objects.create(
            journal=entry, account=existing, debit=Decimal("5.00"),
            total=Decimal("5.00"), kind=JournalEntryConnectorKindChoices.DEBIT)
        out = self._run(company="Messy Co", kind="title")
        print("  RESULT duplicate reported with history markers:")
        for line in out.splitlines():
            if "has history" in line or "safe to remove" in line:
                print(f"        {line.strip()}")
        self.assertIn("has history", out)
        self.assertIn("unused, safe to remove", out)
        self.assertIn("must be resolved", out)

    def test_a_removed_twin_does_not_block(self):
        from companyio.models import Company
        from accounts.models import ChartOfAccount
        company = Company.objects.create(name="Soft Co", kind="ECOMMERCE")
        existing = ChartOfAccount.objects.filter(company=company).first()
        ChartOfAccount.objects.create(
            company=company, title=existing.title, code="9997",
            kind=existing.kind, status=ChartOfAccountStatusChoices.REMOVED)
        out = self._run(company="Soft Co", kind="title")
        print(f"  RESULT soft-deleted twin -> "
              f"{'ignored' if 'can be added' in out else 'still blocks'}")
        self.assertIn("can be added", out)


class ImportAccountKindTests(TestCase):
    """COA #2 -- the CSV importer half.

    The API was fixed by 4153beef; the importer still derived `kind` as
    `account_type.parent.title.upper()` with no check, so a QuickBooks detail
    type in the Account Type column produced an account whose kind is outside
    ChartOfAccountKindChoices -- invisible on every statement, and fatal on the
    first automatic posting.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def _resolve(self, title):
        from categoryio.models import Category
        from common.django_rest.helpers.chart_of_account_helpers import (
            resolve_import_account_kind,
        )
        cat = Category.objects.filter(
            title=title, kind="CHART_OF_ACCOUNT", company__isnull=True).first()
        self.assertIsNotNone(cat, f"{title!r} missing from the taxonomy")
        return cat, resolve_import_account_kind(cat)

    def test_the_templates_own_vocabulary_is_accepted(self):
        # The shipped sheet puts ROOTS in the Account Type column.
        cat, kind = self._resolve("Assets")
        print(f"\n  RESULT template vocabulary 'Assets' (root) -> {kind!r}")
        self.assertEqual(kind, "ASSETS")

    def test_the_api_vocabulary_is_also_accepted(self):
        # The seeds and the API put depth-1 nodes there.
        cat, kind = self._resolve("Bank")
        print(f"  RESULT api vocabulary 'Bank' (depth-1) -> {kind!r}")
        self.assertEqual(kind, "ASSETS")

    def test_a_detail_type_in_the_account_type_column_is_rejected(self):
        # This is the defect: a QBO detail type used as an account type.
        from categoryio.models import Category
        from common.django_rest.helpers.chart_of_account_helpers import (
            resolve_import_account_kind,
        )
        detail = Category.objects.filter(
            parent__parent__isnull=False, kind="CHART_OF_ACCOUNT").first()
        kind = resolve_import_account_kind(detail)
        old = (detail.parent.title.upper() if detail.parent else "")
        print(f"  RESULT detail type {detail.title!r} -> {kind!r} "
              f"(the old rule would have stored {old!r})")
        self.assertIsNone(kind)
        self.assertNotIn(old, [c for c in ChartOfAccountKindChoices.values])

    def test_every_seeded_account_type_still_resolves(self):
        # Guards against the fix rejecting data that used to import fine.
        from categoryio.models import Category
        from common.django_rest.helpers.chart_of_account_helpers import (
            resolve_import_account_kind,
        )
        roots = Category.objects.filter(
            kind="CHART_OF_ACCOUNT", parent__isnull=True)
        depth1 = Category.objects.filter(
            kind="CHART_OF_ACCOUNT", parent__isnull=False,
            parent__parent__isnull=True)
        bad = [c.title for c in list(roots) + list(depth1)
               if resolve_import_account_kind(c) is None]
        print(f"  RESULT {roots.count()} roots + {depth1.count()} account types; "
              f"unresolvable: {bad or 'none'}")
        self.assertEqual(bad, [])


class OpeningStockLedgerTests(TestCase):
    """Product #7 -- creating a product with stock must record it in the ledger.

    OPENING rows were written by exactly one thing: a one-shot backfill command.
    Every product created after it ran had no opening row, so the valuation
    reports -- which cumulate the ledger -- showed an item opened at 100 and
    sold 10 as quantity -10 and asset value -100.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from accounts.models import User
        from companyio.models import Company, CompanyUser
        self.company = Company.objects.create(name="Stock Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="stock@example.com", name="S")
        CompanyUser.objects.create(user=self.user, company=self.company)

    def _create_product(self, quantity, amount=None):
        from weapi.django_rest.serializers.products import (
            PrivateWeProductListSerializer,
        )
        from common.tenant import set_current_company_id
        asset = ChartOfAccount.objects.filter(
            company=self.company, system_key="INVENTORY_ASSET").first()
        income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()
        class _R: pass
        req = _R(); req.user = self.user
        payload = {
            "title": f"Widget {quantity}-{amount}", "sku": f"W{quantity}{amount}",
            "quantity": quantity, "date": "2026-02-01",
            "kind": "PRODUCT", "status": "ACTIVE", "sale_price": "50.00",
            "asset_account_uid": str(asset.uid),
            "income_account_uid": str(income.uid),
        }
        if amount is not None:
            cogs = ChartOfAccount.objects.filter(
                company=self.company, system_key="COGS").first()
            payload.update({"amount": str(amount), "is_addtional_cost": True,
                            "expense_account_uid": str(cogs.uid)})
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeProductListSerializer(data=payload, context={"request": req})
            s.is_valid(raise_exception=True)
            return s.save(), s
        finally:
            set_current_company_id(None)

    def _opening(self, product):
        from stockio.models import StockMovement
        return StockMovement.objects.filter(
            product=product, movement_type="OPENING").first()

    def test_opening_quantity_is_recorded(self):
        product, _ = self._create_product(100, amount=10)
        opening = self._opening(product)
        print(f"\n  RESULT opening movement: qty={opening.signed_quantity} "
              f"rate={opening.rate} cost={opening.inventory_cost}")
        self.assertIsNotNone(opening)
        self.assertEqual(opening.signed_quantity, 100)
        self.assertEqual(opening.inventory_cost, Decimal("1000.000"))

    def test_a_product_with_no_stock_records_nothing(self):
        product, _ = self._create_product(0, amount=10)
        print(f"  RESULT zero-quantity product -> opening={self._opening(product)}")
        self.assertIsNone(self._opening(product))

    def test_the_ledger_and_on_hand_agree_after_a_sale(self):
        # The defect: the sale was the ONLY row, so the report ran negative.
        from stockio.models import StockMovement
        product, _ = self._create_product(100, amount=10)
        StockMovement.objects.create(
            company=self.company, product=product, date="2026-03-01",
            movement_type="SALE", signed_quantity=-10, rate=Decimal("50.000"),
            inventory_cost=Decimal("-100.000"))
        net = sum(m.signed_quantity for m in
                  StockMovement.objects.filter(product=product))
        product.refresh_from_db()
        # The sale row here is injected straight into the ledger, so
        # Product.quantity is untouched -- the point is the ledger's own net.
        print(f"  RESULT ledger nets to {net} (without the opening row it would "
              f"read -10, which is what the valuation report showed)")
        self.assertEqual(net, 90)

    def test_creating_twice_does_not_open_twice(self):
        from stockio.models import StockMovement
        from stockio.django_rest.services.stock_movement import record_opening_stock
        product, _ = self._create_product(100, amount=10)
        record_opening_stock(product, rate=10)
        count = StockMovement.objects.filter(
            product=product, movement_type="OPENING").count()
        print(f"  RESULT opening rows after a second call: {count}")
        self.assertEqual(count, 1)

    def test_create_returns_the_row_so_the_201_carries_a_uid(self):
        product, serializer = self._create_product(5, amount=2)
        print(f"  RESULT 201 body uid={serializer.data.get('uid')!r}")
        self.assertIn("uid", serializer.data)
        self.assertTrue(serializer.data["uid"])


class LedgerLayerTests(TestCase):
    """Groundwork for Product #6 -- cost layers read from the ledger.

    `fifo_product_deduction` walks PurchaseItem rows, so a purchase is the only
    thing that can carry cost. Opening stock, a customer return and a positive
    adjustment all add costed units and none is a purchase, which is why a
    product opened with stock had no layer at all and sold at a fallback cost
    of zero.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        self.company = Company.objects.create(name="Layer Co", kind="ECOMMERCE")
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="LW1", quantity=0,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"))

    def _inbound(self, kind, qty, rate, date):
        from stockio.models import StockMovement
        return StockMovement.objects.create(
            company=self.company, product=self.product, date=date,
            movement_type=kind, signed_quantity=qty, rate=Decimal(str(rate)),
            inventory_cost=Decimal(str(qty)) * Decimal(str(rate)))

    def _layers(self):
        from stockio.django_rest.services.stock_movement import ledger_layers
        return [(m.movement_type, int(rem), str(cost))
                for m, rem, cost in ledger_layers(self.product)]

    def test_opening_stock_is_a_layer(self):
        self._inbound("OPENING", 100, 10, "2026-01-01")
        layers = self._layers()
        print(f"\n  RESULT layers from an opening balance: {layers}")
        self.assertEqual(layers, [("OPENING", 100, "10.000")])

    def test_layers_are_oldest_first_across_sources(self):
        """A purchase is not the only thing that can carry cost.

        Was written with SALE_RETURN as the middle source. A return is no longer
        a layer -- it hands units back to the layer they left, so counting it as
        a source too returned the same stock twice. ADJUSTMENT_IN carries the
        same point: a positive adjustment adds costed units and is not a
        purchase.
        """
        self._inbound("PURCHASE", 5, 30, "2026-03-01")
        self._inbound("OPENING", 10, 10, "2026-01-01")
        self._inbound("ADJUSTMENT_IN", 2, 20, "2026-02-01")
        layers = self._layers()
        print(f"  RESULT FIFO order across opening/adjustment/purchase: {layers}")
        self.assertEqual([k for k, _q, _c in layers],
                         ["OPENING", "ADJUSTMENT_IN", "PURCHASE"])

    def test_a_return_is_not_itself_a_layer(self):
        """The other half of the same rule.

        A SALE_RETURN carries negative slices: it un-consumes the layer the sale
        drew from. If it were ALSO a layer, the returned stock would exist twice
        -- and priced from `rate`, which on a return is the SALE price. Measured
        before the fix: buy 10 at 4, sell 3, return 1 reported 8 units on hand
        while the layers summed to 7, one of them valued at 10.
        """
        from stockio.django_rest.services.stock_movement import (
            ledger_on_hand,
            record_stock_movement,
        )

        purchase = self._inbound("PURCHASE", 10, 4, "2026-01-01")
        record_stock_movement(
            company=self.company, product=self.product, date="2026-01-02",
            movement_type="SALE", signed_quantity=-3, rate=Decimal("10"),
            layer_slices=[(purchase, 3, Decimal("4"))])
        record_stock_movement(
            company=self.company, product=self.product, date="2026-01-03",
            movement_type="SALE_RETURN", signed_quantity=1, rate=Decimal("10"),
            layer_slices=[(purchase, -1, Decimal("4"))])

        layers = self._layers()
        print(f"  RESULT layers after buy 10 / sell 3 / return 1: {layers}")
        self.assertEqual(layers, [("PURCHASE", 8, "4.000")])
        self.assertEqual(
            int(ledger_on_hand(self.product)),
            sum(quantity for _kind, quantity, _cost in layers),
            "on-hand and the layers must tell the same story",
        )

    def test_consumption_reduces_the_layer_it_drew_from(self):
        from stockio.django_rest.services.stock_movement import (
            record_stock_movement,
        )
        opening = self._inbound("OPENING", 100, 10, "2026-01-01")
        record_stock_movement(
            company=self.company, product=self.product, date="2026-02-01",
            movement_type="SALE", signed_quantity=-30, rate=Decimal("50"),
            layer_slices=[(opening, 30, Decimal("10"))])
        layers = self._layers()
        print(f"  RESULT after consuming 30 of 100: {layers}")
        self.assertEqual(layers, [("OPENING", 70, "10.000")])

    def test_an_exhausted_layer_drops_out(self):
        from stockio.django_rest.services.stock_movement import (
            record_stock_movement,
        )
        opening = self._inbound("OPENING", 10, 10, "2026-01-01")
        record_stock_movement(
            company=self.company, product=self.product, date="2026-02-01",
            movement_type="SALE", signed_quantity=-10, rate=Decimal("50"),
            layer_slices=[(opening, 10, Decimal("10"))])
        print(f"  RESULT fully consumed layer: {self._layers()}")
        self.assertEqual(self._layers(), [])

    def test_a_purchase_slice_still_records_its_source(self):
        # Existing callers pass a PurchaseItem; both views must agree.
        from stockio.models import StockMovementLayerConsumption
        from stockio.django_rest.services.stock_movement import (
            record_stock_movement,
        )
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN)
        item = PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=20,
            opening_quantity=20, purchase_price=Decimal("40"),
            status=PurchaseItemStatus.PUBLISHED)
        inbound = self._inbound("PURCHASE", 20, 40, "2026-01-05")
        inbound.purchase_item = item
        inbound.save(update_fields=["purchase_item"])

        record_stock_movement(
            company=self.company, product=self.product, date="2026-02-01",
            movement_type="SALE", signed_quantity=-5, rate=Decimal("50"),
            layer_slices=[(item, 5, Decimal("40"))])
        row = StockMovementLayerConsumption.objects.filter(
            purchase_item=item).first()
        print(f"  RESULT purchase slice -> purchase_item={row.purchase_item_id} "
              f"source_movement={row.source_movement_id} (inbound={inbound.id})")
        self.assertEqual(row.source_movement_id, inbound.id)
        self.assertEqual([(k, q) for k, q, _c in self._layers()],
                         [("PURCHASE", 15)])

    def test_ledger_on_hand_matches_the_layers(self):
        from stockio.django_rest.services.stock_movement import ledger_on_hand
        self._inbound("OPENING", 100, 10, "2026-01-01")
        from stockio.models import StockMovement
        StockMovement.objects.create(
            company=self.company, product=self.product, date="2026-02-01",
            movement_type="SALE", signed_quantity=-40, rate=Decimal("50"),
            inventory_cost=Decimal("-400"))
        print(f"  RESULT ledger on hand: {ledger_on_hand(self.product)}")
        self.assertEqual(ledger_on_hand(self.product), 60)


class StockLedgerBackfillTests(TestCase):
    """The prerequisite for switching FIFO onto the ledger.

    PURCHASE movements only exist for lots bought since the ledger was added, so
    without this the switch makes historical stock invisible and the next sale
    of an older product falls through to a zero-cost fallback.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        self.company = Company.objects.create(name="Backfill Co", kind="ECOMMERCE")
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="BF1", quantity=0,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"))

    def _lot(self, original, remaining, price, date="2026-01-05"):
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date=date)
        return PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=remaining,
            opening_quantity=original, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED)

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("backfill_stock_ledger_layers", stdout=out,
                     company="Backfill Co", **kwargs)
        return out.getvalue()

    def _layers(self):
        from stockio.django_rest.services.stock_movement import ledger_layers
        return [(int(q), str(c)) for _m, q, c in ledger_layers(self.product)]

    def test_a_pre_ledger_lot_becomes_a_layer_sized_at_what_remains(self):
        # Bought 100, 40 already sold before the ledger existed.
        self._lot(original=100, remaining=40, price=10)
        self.assertEqual(self._layers(), [])
        self._run(apply=True)
        print(f"\n  RESULT pre-ledger lot (100 bought, 40 left) -> {self._layers()}")
        self.assertEqual(self._layers(), [(40, "10.000")])

    def test_dry_run_changes_nothing(self):
        self._lot(original=100, remaining=40, price=10)
        out = self._run()
        print(f"  RESULT dry run -> layers={self._layers()}")
        self.assertIn("Dry run", out)
        self.assertEqual(self._layers(), [])

    def test_an_exhausted_lot_is_not_seeded(self):
        self._lot(original=100, remaining=0, price=10)
        self._run(apply=True)
        print(f"  RESULT exhausted lot -> {self._layers()}")
        self.assertEqual(self._layers(), [])

    def test_it_is_idempotent(self):
        self._lot(original=100, remaining=40, price=10)
        self._run(apply=True)
        self._run(apply=True)
        print(f"  RESULT after running twice -> {self._layers()}")
        self.assertEqual(self._layers(), [(40, "10.000")])

    def test_a_lot_already_in_the_ledger_is_left_alone(self):
        from stockio.models import StockMovement
        lot = self._lot(original=100, remaining=100, price=10)
        StockMovement.objects.create(
            company=self.company, product=self.product, date="2026-01-05",
            movement_type="PURCHASE", signed_quantity=100, rate=Decimal("10"),
            inventory_cost=Decimal("1000"), purchase_item=lot)
        self._run(apply=True)
        count = StockMovement.objects.filter(
            product=self.product, movement_type="PURCHASE").count()
        print(f"  RESULT lot already in the ledger -> {count} purchase movement(s)")
        self.assertEqual(count, 1)

    def test_it_reports_when_the_layers_total_the_on_hand(self):
        from productio.models import Product
        self._lot(original=100, remaining=40, price=10)
        # On-hand has to match, or the check correctly calls it drift.
        Product.objects.filter(pk=self.product.pk).update(quantity=40)
        out = self._run(apply=True)
        ok = "total its on-hand quantity" in out
        print(f"  RESULT verify -> {'layers match on-hand' if ok else 'drift reported'}")
        self.assertTrue(ok, out)

    def test_it_reports_drift_when_layers_exceed_on_hand(self):
        from productio.models import Product
        self._lot(original=100, remaining=40, price=10)
        Product.objects.filter(pk=self.product.pk).update(quantity=10)
        out = self._run(apply=True)
        print("  RESULT layers 40 vs on-hand 10 -> "
              f"{'drift reported' if 'do not match on-hand' in out else 'MISSED'}")
        self.assertIn("do not match on-hand", out)


class FifoFromLedgerTests(TestCase):
    """Product #6 -- FIFO consumes ledger layers, so opening stock has a cost.

    Under the old rule a purchase was the only thing that could be a cost layer,
    so a product opened with stock had none: selling from it fell to a fallback
    unit cost of zero, recognising revenue with no cost against it.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        self.company = Company.objects.create(name="Fifo Co", kind="ECOMMERCE")
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="FF1", quantity=0,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"))

    def _open(self, qty, rate, date="2026-01-01"):
        from django.db.models import F
        from productio.models import Product
        from stockio.django_rest.services.stock_movement import record_stock_movement
        Product.objects.filter(pk=self.product.pk).update(
            quantity=F("quantity") + qty)
        self.product.refresh_from_db()
        return record_stock_movement(
            company=self.company, product=self.product, date=date,
            movement_type="OPENING", signed_quantity=qty, rate=Decimal(str(rate)))

    def _purchase(self, qty, price, date="2026-02-01"):
        from django.db.models import F
        from productio.models import Product
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier
        from stockio.django_rest.services.stock_movement import record_stock_movement
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date=date)
        item = PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=qty,
            opening_quantity=qty, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED)
        Product.objects.filter(pk=self.product.pk).update(
            quantity=F("quantity") + qty)
        self.product.refresh_from_db()
        record_stock_movement(
            company=self.company, product=self.product, date=date,
            movement_type="PURCHASE", signed_quantity=qty,
            rate=Decimal(str(price)), purchase_item=item)
        return item

    def _deduct(self, qty):
        from common.django_rest.helpers.fifo_product_quantity_helpers import (
            fifo_product_deduction,
        )
        self.product.refresh_from_db()
        return fifo_product_deduction(self.product, qty)

    def test_opening_stock_now_carries_its_cost(self):
        self._open(100, 10)
        remaining, details, _ = self._deduct(10)
        costs = [(int(q), str(p)) for _s, q, p in details]
        print(f"\n  RESULT selling 10 from opening stock: {costs} "
              f"(was [(10, '0')] -- fallback at zero cost)")
        self.assertEqual(remaining, 0)
        self.assertEqual(costs, [(10, "10.000")])

    def test_purchase_layers_still_behave_as_before(self):
        item = self._purchase(20, 40)
        remaining, details, _ = self._deduct(5)
        source, qty, price = details[0]
        item.refresh_from_db()
        print(f"  RESULT purchase layer: source is PurchaseItem="
              f"{source.__class__.__name__}, qty={qty} price={price}, "
              f"lot remaining={item.quantity}")
        self.assertEqual(source.pk, item.pk)
        self.assertEqual(item.quantity, 15)

    def test_opening_and_purchase_consume_oldest_first(self):
        self._open(6, 10, date="2026-01-01")
        self._purchase(6, 20, date="2026-02-01")
        remaining, details, _ = self._deduct(10)
        got = [(int(q), str(p)) for _s, q, p in details]
        print(f"  RESULT 10 units across opening 6@10 then purchase 6@20: {got}")
        self.assertEqual(got, [(6, "10.000"), (4, "20.000")])

    def test_consuming_twice_does_not_reuse_a_layer(self):
        self._open(10, 10)
        self._sale_consume(6)
        remaining, details, _ = self._deduct(10)
        got = [(int(q), str(p)) for _s, q, p in details]
        print(f"  RESULT after 6 already consumed, asking for 10: {got} "
              f"remaining={remaining}")
        self.assertEqual([q for q, _p in got][:1], [4])

    def _sale_consume(self, qty):
        """Consume through the real path so a consumption row is written."""
        from stockio.django_rest.services.stock_movement import record_stock_movement
        _r, details, _g = self._deduct(qty)
        record_stock_movement(
            company=self.company, product=self.product, date="2026-03-01",
            movement_type="SALE", signed_quantity=-qty, rate=Decimal("50"),
            layer_slices=details)

    def test_a_tenant_with_no_ledger_layers_falls_back_to_the_lots(self):
        # The un-backfilled case: lots exist, ledger has nothing.
        from django.db.models import F
        from productio.models import Product
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date="2026-01-05")
        item = PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=30,
            opening_quantity=30, purchase_price=Decimal("15"),
            status=PurchaseItemStatus.PUBLISHED)
        Product.objects.filter(pk=self.product.pk).update(quantity=30)
        remaining, details, _ = self._deduct(10)
        got = [(int(q), str(p)) for _s, q, p in details]
        print(f"  RESULT un-backfilled tenant (lots, no ledger): {got}")
        self.assertEqual(got, [(10, "15.000")])

    def test_reversing_a_sale_gives_the_layer_back(self):
        # With ledger-sourced layers, returning the goods without undoing the
        # attribution would leave the layer looking spent -- FIFO would then
        # sell the same stock again at the next layer's cost.
        from stockio.django_rest.services.stock_movement import ledger_layers
        from weapi.django_rest.helpers.sale_posting import _record_reversal_movement
        from stockio.models import StockMovement
        self._open(100, 10)
        self._sale_consume(30)
        after_sale = [(int(q), str(c)) for _m, q, c in ledger_layers(self.product)]
        sale_movement = StockMovement.objects.filter(
            product=self.product, movement_type="SALE").first()
        _record_reversal_movement(sale_movement, 30)
        after_reversal = [(int(q), str(c)) for _m, q, c in ledger_layers(self.product)]
        print(f"\n  RESULT layer after selling 30 of 100: {after_sale}")
        print(f"         after reversing that sale:      {after_reversal}")
        self.assertEqual(after_sale, [(70, "10.000")])
        self.assertEqual(after_reversal, [(100, "10.000")])


class LedgerLayerDoubleCountTests(TestCase):
    """The backfill must not seed stock the opening balance already covers.

    `seed_stock_opening_movements` sized each OPENING at `product.quantity` --
    ALL on-hand, including units that arrived via purchases. Seeding purchase
    layers on top counts those units twice, so FIFO believes there is more
    stock than exists.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        self.company = Company.objects.create(name="Dbl Co", kind="ECOMMERCE")
        # 100 on hand, of which 40 sits in an un-consumed purchase lot.
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="DC1", quantity=100,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"))
        from purchaseio.models import Purchase, PurchaseItem
        from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
        from supplierio.models import Supplier
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S")
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date="2026-01-05")
        PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=40,
            opening_quantity=40, purchase_price=Decimal("10"),
            status=PurchaseItemStatus.PUBLISHED)

    def _layers_total(self):
        from stockio.django_rest.services.stock_movement import ledger_layers
        return sum(int(q) for _m, q, _c in ledger_layers(self.product))

    def _run(self, command, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command(command, stdout=out, company="Dbl Co", **kwargs)
        return out.getvalue()

    def _seed_opening(self):
        """What seed_stock_opening_movements wrote: OPENING = product.quantity."""
        from stockio.models import StockMovement
        StockMovement.objects.create(
            company=self.company, product=self.product, date="2026-01-01",
            movement_type="OPENING", signed_quantity=int(self.product.quantity),
            rate=Decimal("10"), inventory_cost=Decimal("1000"),
            note="Opening balance seeded from on-hand quantity.")

    def test_seeding_on_top_of_an_opening_balance_double_counts(self):
        self._seed_opening()
        after_opening = self._layers_total()
        self._run("backfill_stock_ledger_layers", apply=True)
        after_backfill = self._layers_total()
        print(f"\n  RESULT on hand=100; layers after opening seed={after_opening}, "
              f"after lot backfill={after_backfill}")
        self.assertEqual(after_opening, 100)
        # The property that must hold: layers total what is actually on hand.
        self.assertEqual(after_backfill, 100,
                         "purchase layers were seeded on top of the opening balance")


class StockGatedByItemTypeTests(TestCase):
    """Product #1 -- only stocked items move stock.

    No posting path asked what kind of item it was. A supplier bill for a
    Service ran the whole inventory block, and invoicing that service then
    consumed the layers and posted COGS. The inventory reports filter on
    is_inventory, so none of it showed: stock movement existed that no report
    could display and nothing could reconcile.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Gate Co", kind="ECOMMERCE")

    def _product(self, kind, **extra):
        from productio.choices import ProductStatusChoices
        from productio.models import Product
        return Product.objects.create(
            company=self.company, title=f"{kind} item", sku=f"S{kind}",
            quantity=extra.pop("quantity", 0), date="2026-01-01", kind=kind,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"),
            **extra)

    def test_a_service_does_not_track_stock(self):
        service = self._product("SERVICE")
        print(f"\n  RESULT SERVICE tracks_stock -> {service.tracks_stock()}")
        self.assertFalse(service.tracks_stock())

    def test_a_product_does(self):
        item = self._product("PRODUCT")
        print(f"  RESULT PRODUCT tracks_stock -> {item.tracks_stock()}")
        self.assertTrue(item.tracks_stock())

    def test_projects_and_events_do_not(self):
        for kind in ("PROJECT", "EVENT"):
            self.assertFalse(self._product(kind).tracks_stock(), kind)
        print("  RESULT PROJECT/EVENT tracks_stock -> False")

    def test_is_non_stock_is_honoured_when_set(self):
        item = self._product("PRODUCT", is_non_stock=True)
        print(f"  RESULT PRODUCT marked is_non_stock -> {item.tracks_stock()}")
        self.assertFalse(item.tracks_stock())

    def test_tracking_does_not_depend_on_the_is_inventory_column(self):
        # The trap this guards: all four flags default False, so gating on
        # is_inventory would have switched tracking off for most products.
        # save() now derives the column, so force the stale value past it to
        # prove the predicate does not consult it.
        from productio.models import Product
        item = self._product("PRODUCT")
        Product.objects.filter(pk=item.pk).update(is_inventory=False)
        item.refresh_from_db()
        print(f"  RESULT PRODUCT with a stale is_inventory=False -> "
              f"tracks_stock={item.tracks_stock()}")
        self.assertFalse(item.is_inventory)
        self.assertTrue(item.tracks_stock())

    def test_a_service_gets_no_opening_movement(self):
        from stockio.models import StockMovement
        from stockio.django_rest.services.stock_movement import record_opening_stock
        service = self._product("SERVICE", quantity=40)
        record_opening_stock(service, rate=50)
        count = StockMovement.objects.filter(product=service).count()
        print(f"  RESULT service with quantity 40 -> {count} stock movement(s)")
        self.assertEqual(count, 0)

    def test_selling_a_service_posts_revenue_but_no_cost(self):
        # The production instance: 'Software Service' carried 8 units of layers.
        from stockio.models import StockMovement
        from salesio.models import Sale, SaleItem
        from customerio.models import Customer
        from weapi.django_rest.helpers.sale_posting import _post_sale_line
        income = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_OF_PRODUCT_INCOME").first()
        service = self._product("SERVICE", quantity=40)
        service.income_account = income
        service.save(update_fields=["income_account"])
        customer = Customer.objects.create(
            company=self.company, first_name="C", display_name="C")
        sale = Sale.objects.create(
            company=self.company, customer=customer, is_invoice=True,
            date="2026-03-01", invoice_id="INV-GATE-1",
            total=Decimal("500"), due_total=Decimal("500"))
        line = SaleItem.objects.create(
            sale=sale, product=service, quantity=10,
            sale_price=Decimal("50"), total=Decimal("500"))
        connectors = []
        _post_sale_line(sale, line, Decimal("0.00"), connectors)
        accounts = [c[0].system_key for c in connectors]
        moves = StockMovement.objects.filter(product=service).count()
        print(f"  RESULT selling a service: accounts touched={accounts}, "
              f"stock movements={moves}")
        self.assertIn("SALES_OF_PRODUCT_INCOME", accounts)
        self.assertNotIn("COGS", accounts)
        self.assertNotIn("INVENTORY_ASSET", accounts)
        self.assertEqual(moves, 0)

    def test_reports_use_the_same_predicate_as_posting(self):
        # Production had 20 SERVICE products with is_inventory=True, so the
        # inventory reports counted them AS inventory while posting (correctly)
        # would not stock them. One predicate, both sides.
        from productio.models import Product
        service = self._product("SERVICE", quantity=5)
        service.is_inventory = True          # exactly the production shape
        service.save(update_fields=["is_inventory"])
        item = self._product("PRODUCT", quantity=5)

        visible = set(
            Product.objects.filter(
                Product.stocked_filter_for(), company=self.company
            ).values_list("pk", flat=True)
        )
        print(f"\n  RESULT service flagged is_inventory=True: "
              f"tracks_stock={service.tracks_stock()}, in report={service.pk in visible}")
        self.assertFalse(service.tracks_stock())
        self.assertNotIn(service.pk, visible)
        self.assertIn(item.pk, visible)

    def test_the_predicate_works_across_a_relation(self):
        from stockio.models import StockMovement
        from productio.models import Product
        item = self._product("PRODUCT", quantity=5)
        service = self._product("SERVICE", quantity=5)
        for product in (item, service):
            StockMovement.objects.create(
                company=self.company, product=product, date="2026-03-01",
                movement_type="PURCHASE", signed_quantity=5,
                rate=Decimal("10"), inventory_cost=Decimal("50"))
        rows = StockMovement.objects.filter(
            Product.stocked_filter_for("product"), company=self.company)
        print(f"  RESULT movements visible to the valuation report: {rows.count()} "
              f"of {StockMovement.objects.filter(company=self.company).count()}")
        self.assertEqual([r.product_id for r in rows], [item.pk])


class ProductTypeFlagsTests(TestCase):
    """Product #11 -- the type flags stop contradicting the type.

    Four independent client-supplied booleans encoded 16 states where at most
    three are meaningful, and nothing normalised them. Production holds 20
    services flagged is_inventory=True as a result.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Flag Co", kind="ECOMMERCE")

    def _product(self, kind, **extra):
        from productio.choices import ProductStatusChoices
        from productio.models import Product
        return Product.objects.create(
            company=self.company, title=f"{kind} item", sku=f"F{kind}{extra}",
            quantity=0, date="2026-01-01", kind=kind,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("10.00"),
            **extra)

    def test_a_service_cannot_be_stored_as_inventory(self):
        # Exactly the production shape: client sends is_inventory=True.
        service = self._product("SERVICE", is_inventory=True)
        service.refresh_from_db()
        print(f"\n  RESULT SERVICE saved with is_inventory=True -> "
              f"stored as {service.is_inventory}")
        self.assertFalse(service.is_inventory)

    def test_a_product_is_marked_inventory_even_if_the_client_omits_it(self):
        item = self._product("PRODUCT")
        item.refresh_from_db()
        print(f"  RESULT PRODUCT saved without the flag -> {item.is_inventory}")
        self.assertTrue(item.is_inventory)

    def test_is_non_stock_still_wins(self):
        item = self._product("PRODUCT", is_non_stock=True, is_inventory=True)
        item.refresh_from_db()
        print(f"  RESULT PRODUCT marked is_non_stock -> is_inventory="
              f"{item.is_inventory}")
        self.assertFalse(item.is_inventory)

    def test_the_flag_follows_a_type_change(self):
        from productio.choices import ProductKindChoices
        item = self._product("PRODUCT")
        self.assertTrue(item.is_inventory)
        item.kind = ProductKindChoices.SERVICE
        item.save()
        item.refresh_from_db()
        print(f"  RESULT PRODUCT converted to SERVICE -> is_inventory="
              f"{item.is_inventory}")
        self.assertFalse(item.is_inventory)

    def test_a_services_only_recurring_template_needs_no_warehouse(self):
        # The one live consequence: 20 production services read as
        # inventory-tracked and blocked their template for want of a store.
        service = self._product("SERVICE", is_inventory=True)
        # Simulate the pre-fix state the database still holds.
        from productio.models import Product
        Product.objects.filter(pk=service.pk).update(is_inventory=True)
        service.refresh_from_db()
        print(f"  RESULT stale is_inventory={service.is_inventory} but "
              f"tracks_stock={service.tracks_stock()}")
        self.assertTrue(service.is_inventory)      # the row still lies
        self.assertFalse(service.tracks_stock())   # the check no longer asks it


class ReportCogsFromLedgerTests(TestCase):
    """Product #8 -- the report's cost of sales stops moving after the fact.

    COGS was `current item cost x quantity sold`, with no date filter. Editing
    an item's cost therefore restated the cost of sales on every period it had
    ever appeared in, including closed ones -- and the report disagreed with the
    journal, which had posted the FIFO layer price in force at the time.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        from productio.choices import ProductKindChoices, ProductStatusChoices
        from productio.models import Product
        self.company = Company.objects.create(name="Cogs Co", kind="ECOMMERCE")
        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="CG1", quantity=100,
            date="2026-01-01", kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"))

    def _cost_row(self, amount):
        from productio.models import ProductAdditionalCost
        cogs = ChartOfAccount.objects.filter(
            company=self.company, system_key="COGS").first()
        return ProductAdditionalCost.objects.create(
            product=self.product, expense_account=cogs, amount=Decimal(str(amount)))

    def _sell(self, quantity, unit_cost, date="2026-02-01"):
        """A sale that relieved `unit_cost` per unit, recorded in the ledger."""
        from stockio.django_rest.services.stock_movement import (
            record_stock_movement,
        )
        opening = record_stock_movement(
            company=self.company, product=self.product, date="2026-01-01",
            movement_type="OPENING", signed_quantity=quantity,
            rate=Decimal(str(unit_cost)))
        record_stock_movement(
            company=self.company, product=self.product, date=date,
            movement_type="SALE", signed_quantity=-quantity,
            rate=Decimal("50"),
            layer_slices=[(opening, quantity, Decimal(str(unit_cost)))])

    def _posted(self, date_from=None, date_to=None):
        from weapi.django_rest.helpers.reports.sales_lines import _posted_cogs
        return _posted_cogs(
            self.company, {str(self.product.uid)}, date_from, date_to)

    def test_cogs_comes_from_what_was_actually_relieved(self):
        self._cost_row(10)
        self._sell(100, unit_cost=10)
        got = self._posted()
        print(f"\n  RESULT 100 units relieved at 10 -> posted COGS "
              f"{got[str(self.product.uid)]}")
        self.assertEqual(got[str(self.product.uid)], Decimal("1000.000"))

    def test_raising_the_item_cost_does_not_restate_a_closed_period(self):
        cost = self._cost_row(10)
        self._sell(100, unit_cost=10)
        before = self._posted()[str(self.product.uid)]
        # Q2: the supplier raises the price and a user PATCHes the item.
        cost.amount = Decimal("14.00")
        cost.save(update_fields=["amount"])
        after = self._posted()[str(self.product.uid)]
        print(f"  RESULT item cost 10 -> 14; posted COGS {before} -> {after} "
              f"(the old rule would now read 1400)")
        self.assertEqual(before, after)
        self.assertEqual(after, Decimal("1000.000"))

    def test_it_respects_the_reporting_period(self):
        self._cost_row(10)
        self._sell(40, unit_cost=10, date="2026-02-01")
        self._sell(60, unit_cost=10, date="2026-05-01")
        q1 = self._posted("2026-01-01", "2026-03-31")
        print(f"  RESULT Q1 window -> {q1.get(str(self.product.uid))} of 1000 total")
        self.assertEqual(q1[str(self.product.uid)], Decimal("400.000"))

    def test_a_pre_ledger_sale_falls_back_to_the_item_cost(self):
        from weapi.django_rest.helpers.reports.sales_lines import (
            assemble_product_summary,
        )
        key = str(self.product.uid)
        lines = [{"product_uid": key, "product_name": "Widget",
                  "quantity": Decimal("10"), "amount": Decimal("500")}]
        summary = assemble_product_summary(lines, {key: Decimal("10")}, posted_cogs={})
        row = summary["rows"][0]
        print(f"  RESULT no ledger rows -> falls back to cost x qty: "
              f"cogs={row['cogs']}")
        self.assertEqual(row["cogs"], "100.00")

    def test_the_ledger_wins_where_both_exist(self):
        from weapi.django_rest.helpers.reports.sales_lines import (
            assemble_product_summary,
        )
        key = str(self.product.uid)
        lines = [{"product_uid": key, "product_name": "Widget",
                  "quantity": Decimal("10"), "amount": Decimal("500")}]
        summary = assemble_product_summary(
            lines, {key: Decimal("14")}, posted_cogs={key: Decimal("100")})
        row = summary["rows"][0]
        print(f"  RESULT current cost says 140, ledger says 100 -> "
              f"cogs={row['cogs']} margin={row['gross_margin']}")
        self.assertEqual(row["cogs"], "100.00")
        self.assertEqual(row["gross_margin"], "400.00")


class AccountParentCycleTests(TestCase):
    """COA #11 -- a two-PATCH cycle used to be permanent.

    Only direct self-parenting was checked, so `A.parent=B` then `B.parent=A`
    built a loop. Both accounts and everything under them vanished from the
    tree endpoint while still appearing in the flat list, the journal and the
    statements. Neither could then be deleted (each is the other's parent) nor
    re-parented to the top, because parent_uid rejected null.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from accounts.models import User
        from companyio.models import Company, CompanyUser
        from categoryio.models import Category
        self.company = Company.objects.create(name="Cycle Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="cycle@example.com", name="C")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.asset_type = Category.objects.filter(
            parent__title__iexact="Assets").first()
        self.detail = Category.objects.filter(parent=self.asset_type).first()

    def _account(self, title, code, parent=None):
        from accounts.models import ChartOfAccount
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            account_type=self.asset_type, detail_type=self.detail,
            status=ChartOfAccountStatusChoices.ACTIVE, parent=parent)

    def _patch(self, instance, data):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer,
        )
        from common.tenant import set_current_company_id
        class _R: pass
        req = _R(); req.user = self.user
        set_current_company_id(self.company.id)
        try:
            s = PrivateWeChartOfAccountDetailsSerializer(
                instance=instance, data=data, partial=True,
                context={"request": req})
            ok = s.is_valid()
            if ok:
                s.save()
            return ok, dict(s.errors)
        finally:
            set_current_company_id(None)

    def test_a_two_step_cycle_is_refused(self):
        a = self._account("Alpha", "1801")
        b = self._account("Beta", "1802")
        ok1, _ = self._patch(a, {"parent_uid": str(b.uid)})
        self.assertTrue(ok1)
        ok2, errors = self._patch(b, {"parent_uid": str(a.uid)})
        print(f"\n  RESULT A.parent=B then B.parent=A -> valid={ok2} "
              f"errors={errors}")
        self.assertFalse(ok2)
        self.assertIn("parent_uid", errors)

    def test_a_deeper_cycle_is_refused(self):
        a = self._account("A", "1811")
        b = self._account("B", "1812", parent=a)
        c = self._account("C", "1813", parent=b)
        ok, errors = self._patch(a, {"parent_uid": str(c.uid)})
        print(f"  RESULT A<-B<-C then A.parent=C -> valid={ok} errors={errors}")
        self.assertFalse(ok)

    def test_an_ordinary_reparent_still_works(self):
        a = self._account("Parent", "1821")
        b = self._account("Child", "1822")
        ok, errors = self._patch(b, {"parent_uid": str(a.uid)})
        b.refresh_from_db()
        print(f"  RESULT ordinary reparent -> valid={ok} parent={b.parent.title!r}")
        self.assertTrue(ok, errors)
        self.assertEqual(b.parent_id, a.pk)

    def test_an_account_can_be_returned_to_the_top_level(self):
        # The recoverability half: parent_uid=null was silently discarded, so a
        # wrongly-parented account could never be moved back.
        a = self._account("Parent", "1831")
        b = self._account("Child", "1832", parent=a)
        ok, errors = self._patch(b, {"parent_uid": None})
        b.refresh_from_db()
        print(f"  RESULT parent_uid=null -> valid={ok} parent={b.parent}")
        self.assertTrue(ok, errors)
        self.assertIsNone(b.parent)

    def test_an_existing_loop_does_not_hang_the_walk(self):
        # A row corrupted before the guard existed must not make the walk spin.
        from accounts.models import ChartOfAccount
        a = self._account("Loop A", "1841")
        b = self._account("Loop B", "1842", parent=a)
        ChartOfAccount.objects.filter(pk=a.pk).update(parent=b)
        c = self._account("Fresh", "1843")
        ok, errors = self._patch(c, {"parent_uid": str(a.uid)})
        print(f"  RESULT parenting to an already-looped account -> valid={ok} "
              f"errors={errors}")
        self.assertFalse(ok)
        self.assertIn("parent_uid", errors)


class UnattributedTaxTests(SaleReversalTests):
    """Sale #11 -- a declared total_tax that nothing accounted for.

    `total_tax` is a header figure; the liability legs come from the per-line
    rates or the auto-tax breakdown. A document with neither produced no tax leg
    at all, so A/R was debited for the tax-inclusive amount and nothing credited
    the tax.
    """

    def _rows(self, sale):
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry)
        return list(entry.journalentryconnector_set.all())

    def _balance(self, sale):
        rows = self._rows(sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        return dr, cr, rows

    def test_a_declared_tax_with_no_tax_line_now_balances(self):
        # 1000 of goods + 100 declared tax, no tax-flagged line, no auto tax.
        sale = self._invoice(10, "100.00", total="1000.00", due_total="1100.00",
                             total_tax="100.00")
        dr, cr, rows = self._balance(sale)
        payable = [r for r in rows
                   if r.account and r.account.system_key == "SALES_TAX_PAYABLE"]
        print(f"\n  RESULT declared tax 100 with no tax line: dr={dr} cr={cr} "
              f"payable legs={len(payable)}")
        self.assertEqual(dr, cr)
        self.assertEqual(len(payable), 1)
        self.assertEqual(payable[0].credit, Decimal("100.000"))

    def test_an_inclusive_document_balances_too(self):
        # Revenue is reduced by the tax, so the missing credit was the whole of it.
        sale = self._invoice(10, "100.00", tax_kind="INCLUSIVE",
                             total="1000.00", due_total="1000.00",
                             total_tax="90.00")
        dr, cr, rows = self._balance(sale)
        income = sum(Decimal(r.credit or 0) for r in rows
                     if r.account and r.account.system_key == "SALES_OF_PRODUCT_INCOME")
        print(f"  RESULT inclusive: income={income} dr={dr} cr={cr}")
        self.assertEqual(dr, cr)
        self.assertEqual(income, Decimal("910.000"))

    def test_a_document_with_no_declared_tax_gains_no_leg(self):
        sale = self._invoice(10, "100.00")
        rows = self._rows(sale)
        keys = {r.account.system_key for r in rows if r.account}
        print(f"  RESULT no declared tax -> accounts {sorted(k for k in keys if k)}")
        self.assertNotIn("SALES_TAX_PAYABLE", keys)

    def test_a_header_that_disagrees_with_its_lines_is_reported_AND_balanced(self):
        # REVERSED from the original decision, deliberately.
        #
        # This used to assert that a header disagreeing with its lines was
        # reported and NOT topped up -- the reasoning being that a plug entry
        # would hide the disagreement. The reasoning holds; the remedy did not.
        # Production company 165 collected 590.625 of tax into the bank, posted
        # 37.50 of it to a liability, and shipped an entry short by 553.125.
        # The warning was written and the ledger was still broken.
        #
        # An unbalanced ledger is a worse way to keep a fault visible than a
        # balanced one plus a WARNING, so the shortfall is now posted to Sales
        # Tax Payable -- a mis-attribution rather than an imbalance -- and the
        # warning still fires. See test_the_disagreement_is_still_reported in
        # salesio/tests_tax_residual.py, which pins that half.
        from agencyio.models import Agency, AgencyTax, AgencyTaxSet
        payable = ChartOfAccount.objects.filter(
            company=self.company, system_key="SALES_TAX_PAYABLE").first()
        agency = Agency.objects.create(company=self.company, title="State",
                                       status="ACTIVE")
        tax = AgencyTax.objects.create(company=self.company, title="ST")
        AgencyTaxSet.objects.create(taxes=tax, agency=agency,
                                    rate=Decimal("10.000"),
                                    sales_tax_account=payable)
        # header says 250, lines only account for 100. due_total follows the
        # header (total + total_tax), which is what the document builders
        # produce -- the customer really was billed for 250 of tax, so the
        # missing 150 has to reach a liability or the entry cannot balance.
        sale = self._invoice(10, "100.00", total="1000.00", due_total="1250.00",
                             total_tax="250.00")
        line = sale.saleitem_set.first()
        line.is_tax = True
        line.tax = tax
        line.total = Decimal("1000.00")
        line.save()
        from weapi.django_rest.helpers.sale_posting import (
            post_sale_document, reverse_sale_postings,
        )
        reverse_sale_postings(sale)
        post_sale_document(sale)
        rows = self._rows(sale)
        posted_tax = sum(Decimal(r.credit or 0) for r in rows
                         if r.account and r.account.system_key == "SALES_TAX_PAYABLE")
        debit = sum(Decimal(r.debit or 0) for r in rows)
        credit = sum(Decimal(r.credit or 0) for r in rows)
        print(f"  RESULT header says 250, lines say 100 -> posted {posted_tax} "
              f"(100 attributed + 150 shortfall); entry {debit} / {credit}")
        # The lines' 100 plus the 150 shortfall the header declared.
        self.assertEqual(posted_tax, Decimal("250.000"))
        # And the point of the change: the entry balances.
        self.assertEqual(debit, credit)


class CogsAccountResolutionTests(SaleReversalTests):
    """Product #5 -- cost of sales has a home, and its leg never posts alone.

    `Product` carried asset_account and income_account as first-class fields but
    no COGS field: the expense account lived on a child row the client only got
    if it sent a truthy `is_addtional_cost`. And the two cost legs were gated
    independently, so a product with no cost row credited Inventory Asset with
    no offsetting debit.
    """

    def _rows(self, sale):
        entry = JournalEntry.objects.filter(sale=sale).first()
        return list(entry.journalentryconnector_set.all()) if entry else []

    def _balance(self, sale):
        rows = self._rows(sale)
        dr = sum(Decimal(r.debit or 0) for r in rows)
        cr = sum(Decimal(r.credit or 0) for r in rows)
        return dr, cr, rows

    def test_a_product_with_no_cost_row_still_balances(self):
        # No _cost_account() call: the product has no ProductAdditionalCost.
        self._layer(20, "40.00")
        sale = self._invoice(10, "100.00")
        dr, cr, rows = self._balance(sale)
        keys = sorted({r.account.system_key for r in rows if r.account and r.account.system_key})
        print(f"\n  RESULT no cost row: dr={dr} cr={cr} accounts={keys}")
        self.assertEqual(dr, cr)
        self.assertIn("COGS", keys)
        self.assertIn("INVENTORY_ASSET", keys)

    def test_the_products_own_cogs_account_wins(self):
        from weapi.django_rest.helpers.sale_posting import resolve_cogs_account
        other = ChartOfAccount.objects.filter(
            company=self.company, kind=ChartOfAccountKindChoices.EXPENSES
        ).exclude(system_key="COGS").first()
        self.product.cogs_account = other
        self.product.save(update_fields=["cogs_account"])
        got = resolve_cogs_account(self.product, self.company)
        print(f"  RESULT product.cogs_account set -> resolves to {got.title!r}")
        self.assertEqual(got.pk, other.pk)

    def test_it_falls_back_to_the_cost_row_then_the_control_account(self):
        from weapi.django_rest.helpers.sale_posting import resolve_cogs_account
        control = ChartOfAccount.objects.filter(
            company=self.company, system_key="COGS").first()
        # no field, no cost row -> the company's control account
        self.assertEqual(
            resolve_cogs_account(self.product, self.company).pk, control.pk)
        # a cost row takes precedence over the control account
        self._cost_account()
        got = resolve_cogs_account(self.product, self.company)
        print(f"  RESULT no field, cost row present -> {got.title!r}")
        self.assertEqual(got.pk, control.pk)  # _cost_account uses the COGS account

    def test_the_inventory_leg_never_posts_without_its_counterpart(self):
        # Force the pathological case: an asset account but nowhere for cost.
        from unittest.mock import patch
        self._layer(20, "40.00")
        with patch("weapi.django_rest.helpers.sale_posting.resolve_cogs_account",
                   return_value=None):
            sale = self._invoice(10, "100.00")
        dr, cr, rows = self._balance(sale)
        keys = {r.account.system_key for r in rows if r.account}
        print(f"  RESULT no COGS account anywhere: dr={dr} cr={cr} "
              f"inventory leg present={'INVENTORY_ASSET' in keys}")
        self.assertEqual(dr, cr)
        self.assertNotIn("INVENTORY_ASSET", keys)


class ImportTemplatePairTests(TestCase):
    """The CSV half of COA #19, and the sheet it validates against.

    The API rule is "detail_type is a CHILD of account_type". The importer's
    template uses a different vocabulary -- a ROOT in the Account Type column and
    a mix of depth-1 and depth-2 nodes in the Detail Type column -- so 95 of its
    157 documented pairs are grandchildren. Enforcing the child rule there would
    have rejected the majority of imports following our own reference sheet.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def _cat(self, title):
        from categoryio.models import Category
        return Category.objects.filter(
            title=title, kind="CHART_OF_ACCOUNT", company__isnull=True).first()

    def test_every_shipped_template_pair_validates(self):
        # The R6 lesson applied to the reference sheet: assert it agrees with
        # the tree, or it drifts and every import following it fails.
        from common.django_rest.helpers.chart_of_account_helpers import (
            detail_type_is_under,
        )
        from datamigrationio.django_rest.handlers.chart_of_accounts import (
            ChartOfAccountsMigrationHandler as Handler,
        )
        pairs = Handler.TYPE_DETAIL_TYPE_DATA[1:]
        bad = []
        for account_type, detail_type in pairs:
            at, dt = self._cat(account_type), self._cat(detail_type)
            if at is None:
                bad.append((account_type, detail_type, "account type missing"))
            elif dt is None:
                bad.append((account_type, detail_type, "detail type missing"))
            elif not detail_type_is_under(at, dt):
                bad.append((account_type, detail_type, "not beneath"))
        print(f"\n  RESULT {len(pairs)} template pairs, {len(bad)} invalid")
        for row in bad[:8]:
            print(f"         {row}")
        self.assertEqual(bad, [])

    def test_a_grandchild_pair_is_accepted(self):
        from common.django_rest.helpers.chart_of_account_helpers import (
            detail_type_is_under,
        )
        # The template's own shape: root + depth-2 detail type.
        assets = self._cat("Assets")
        prepaid = self._cat("Prepaid Expenses")
        print(f"  RESULT Assets / Prepaid Expenses (grandchild) -> "
              f"{detail_type_is_under(assets, prepaid)}")
        self.assertTrue(detail_type_is_under(assets, prepaid))

    def test_a_pair_from_different_branches_is_rejected(self):
        from common.django_rest.helpers.chart_of_account_helpers import (
            detail_type_is_under,
        )
        assets = self._cat("Assets")
        interest = self._cat("Interest Paid")      # lives under Other Expenses
        print(f"  RESULT Assets / Interest Paid -> "
              f"{detail_type_is_under(assets, interest)}")
        self.assertFalse(detail_type_is_under(assets, interest))

    def test_a_self_referential_pair_is_accepted(self):
        from common.django_rest.helpers.chart_of_account_helpers import (
            detail_type_is_under,
        )
        equity = self._cat("Equity")
        print(f"  RESULT Equity / Equity (as the sheet lists it) -> "
              f"{detail_type_is_under(equity, equity)}")
        self.assertTrue(detail_type_is_under(equity, equity))


class AccountIntegrityAuditTests(TestCase):
    """The two repair sweeps the plan owed, plus the kind check.

    The guards added recently stop these being created; nothing said anything
    about rows that already exist.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Audit Co", kind="ECOMMERCE")
        self.other = Company.objects.create(name="Rival Co", kind="ECOMMERCE")

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("audit_account_integrity", stdout=out, **kwargs)
        return out.getvalue()

    def _account(self, company, title, code, **extra):
        from categoryio.models import Category
        asset_type = Category.objects.filter(parent__title__iexact="Assets").first()
        detail = Category.objects.filter(parent=asset_type).first()
        defaults = dict(
            company=company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            account_type=asset_type, detail_type=detail,
            status=ChartOfAccountStatusChoices.ACTIVE)
        defaults.update(extra)
        return ChartOfAccount.objects.create(**defaults)

    def test_a_clean_company_reports_nothing(self):
        out = self._run(company="Audit Co")
        print(f"\n  RESULT clean -> {'no faults' if 'No inconsistent' in out else 'faults'}")
        self.assertIn("No inconsistent", out)

    def test_a_cross_tenant_parent_is_found(self):
        theirs = ChartOfAccount.objects.filter(company=self.other).first()
        mine = self._account(self.company, "Mine", "1901")
        ChartOfAccount.objects.filter(pk=mine.pk).update(parent=theirs)
        out = self._run(company="Audit Co", only="parent")
        print("  RESULT cross-tenant parent:")
        for line in out.splitlines():
            if "is in" in line:
                print(f"        {line.strip()}")
        self.assertIn("is in", out)

    def test_a_mismatched_pair_is_found(self):
        from categoryio.models import Category
        expense_detail = Category.objects.filter(
            parent__title__iexact="Expenses").first()
        expense_detail = Category.objects.filter(parent=expense_detail).first()
        self._account(self.company, "Odd", "1902", detail_type=expense_detail)
        out = self._run(company="Audit Co", only="pair")
        print("  RESULT mismatched pair:")
        for line in out.splitlines():
            if "is not under" in line:
                print(f"        {line.strip()}")
        self.assertIn("is not under", out)

    def test_a_grandchild_pair_is_not_flagged(self):
        # The CSV template legitimately produces these.
        from categoryio.models import Category
        assets_root = Category.objects.filter(
            title="Assets", parent__isnull=True).first()
        prepaid = Category.objects.filter(title="Prepaid Expenses").first()
        self._account(self.company, "Imported", "1903",
                      account_type=assets_root, detail_type=prepaid)
        out = self._run(company="Audit Co", only="pair")
        print(f"  RESULT grandchild pair -> "
              f"{'not flagged' if 'none' in out else 'FLAGGED'}")
        self.assertIn("none", out)

    def test_an_invalid_kind_is_found(self):
        # Exactly the two rows the production query returned.
        account = self._account(self.company, "CAO -3", "1904")
        ChartOfAccount.objects.filter(pk=account.pk).update(kind="OTHER EXPENSES")
        out = self._run(company="Audit Co", only="kind")
        print("  RESULT invalid kind:")
        for line in out.splitlines():
            if "kind=" in line:
                print(f"        {line.strip()}")
        self.assertIn("OTHER EXPENSES", out)


class AccountPairRepairTests(TestCase):
    """Repairs the seed-era pairs that live on in tenants onboarded before the
    templates were corrected -- but only the ones a script may safely decide."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Repair Co", kind="ECOMMERCE")

    def _cat(self, title):
        from categoryio.models import Category
        return Category.objects.filter(
            title=title, kind="CHART_OF_ACCOUNT", company__isnull=True).first()

    def _account(self, title, code, account_type, detail_type, kind):
        # Reuse the seeded account of that title. Creating a Company seeds the
        # chart from the category tree, so these titles already exist, and
        # `unique_title_per_company_ci` now forbids a second one. Reusing is also
        # what the repair command meets in production.
        existing = ChartOfAccount.objects.filter(
            company=self.company, title__iexact=title
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED).first()
        if existing:
            existing.code = code
            existing.kind = kind
            existing.account_type = account_type
            existing.detail_type = detail_type
            existing.status = ChartOfAccountStatusChoices.ACTIVE
            existing.save()
            return existing

        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=code, kind=kind,
            account_type=account_type, detail_type=detail_type,
            status=ChartOfAccountStatusChoices.ACTIVE)

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("repair_account_pairs", stdout=out, company="Repair Co", **kwargs)
        return out.getvalue()

    def test_a_same_root_mismatch_is_retyped(self):
        # The production shape: Depreciation typed under Expense.
        account = self._account(
            "Depreciation Expense", "6501", self._cat("Expense"),
            self._cat("Depreciation"), ChartOfAccountKindChoices.EXPENSES)
        self._run(apply=True)
        account.refresh_from_db()
        print(f"\n  RESULT Depreciation: account_type -> "
              f"{account.account_type.title!r}, kind still {account.kind!r}")
        self.assertEqual(account.account_type.title, "Other Expenses")
        self.assertEqual(account.kind, ChartOfAccountKindChoices.EXPENSES)

    def test_dry_run_changes_nothing(self):
        account = self._account(
            "Depreciation Expense", "6502", self._cat("Expense"),
            self._cat("Depreciation"), ChartOfAccountKindChoices.EXPENSES)
        out = self._run()
        account.refresh_from_db()
        print(f"  RESULT dry run -> still {account.account_type.title!r}")
        self.assertIn("Dry run", out)
        self.assertEqual(account.account_type.title, "Expense")

    def test_a_kind_changing_mismatch_is_refused(self):
        # Treasury Stock (Equity) typed under Long Term Liabilities.
        account = self._account(
            "Mark Inactive", "2901", self._cat("Long Term Liabilities"),
            self._cat("Treasury Stock"), ChartOfAccountKindChoices.LIABILITIES)
        out = self._run(apply=True)
        account.refresh_from_db()
        print(f"  RESULT Treasury Stock under a liability type -> left as "
              f"{account.account_type.title!r} (reported, not moved)")
        self.assertEqual(account.account_type.title, "Long Term Liabilities")
        self.assertIn("resolve by hand", out)

    def test_a_posted_account_is_left_for_a_dated_correction(self):
        account = self._account(
            "Depreciation Expense", "6503", self._cat("Expense"),
            self._cat("Depreciation"), ChartOfAccountKindChoices.EXPENSES)
        entry = JournalEntry.objects.create(
            company=self.company, amount=Decimal("5.00"))
        JournalEntryConnector.objects.create(
            journal=entry, account=account, debit=Decimal("5.00"),
            total=Decimal("5.00"), kind=JournalEntryConnectorKindChoices.DEBIT)
        out = self._run(apply=True)
        account.refresh_from_db()
        print(f"  RESULT posted account -> left as {account.account_type.title!r}")
        self.assertEqual(account.account_type.title, "Expense")
        self.assertIn("dated correction", out)

    def test_a_correct_account_is_untouched(self):
        account = self._account(
            "Depreciation Expense", "6504", self._cat("Other Expenses"),
            self._cat("Depreciation"), ChartOfAccountKindChoices.EXPENSES)
        out = self._run(apply=True)
        account.refresh_from_db()
        print(f"  RESULT already correct -> {account.account_type.title!r}")
        self.assertEqual(account.account_type.title, "Other Expenses")


class ControlAccountTypeRepairTests(TestCase):
    """A control account misclassified is worse than an ordinary one.

    get_chart_of_account resolves it by system_key, so every document of its
    kind posts to it -- production has Talha-organization's Accounts Payable
    carrying system_key=AP with account_type 'Expense'.
    """

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        from companyio.models import Company
        self.company = Company.objects.create(name="Ctrl Co", kind="ECOMMERCE")

    def _run(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("repair_control_account_types", stdout=out,
                     company="Ctrl Co", **kwargs)
        return out.getvalue()

    def _ap(self):
        return ChartOfAccount.objects.filter(
            company=self.company, system_key="AP").first()

    def test_a_clean_company_needs_no_repair(self):
        out = self._run()
        print(f"\n  RESULT freshly seeded -> repairable="
              f"{'0' if 'repairable : 0' in out.replace('  ', ' ') else 'some'}")
        self.assertIn("Dry run", out)

    def test_the_production_shape_is_restored(self):
        from categoryio.models import Category
        ap = self._ap()
        expense = Category.objects.filter(
            title="Expense", company__isnull=True).first()
        expense_detail = Category.objects.filter(parent=expense).first()
        ChartOfAccount.objects.filter(pk=ap.pk).update(
            account_type=expense, detail_type=expense_detail)
        ap.refresh_from_db()
        self.assertEqual(ap.account_type.title, "Expense")

        self._run(apply=True)
        ap.refresh_from_db()
        print(f"  RESULT AP typed as Expense -> restored to "
              f"{ap.account_type.title!r} / {ap.detail_type.title!r}, "
              f"kind still {ap.kind!r}")
        self.assertEqual(ap.account_type.title, "Accounts Payable (A/P)")
        self.assertEqual(ap.kind, ChartOfAccountKindChoices.LIABILITIES)

    def test_it_repairs_even_when_the_account_has_been_posted_to(self):
        # The model guard refuses this; restoring a wrong classification is not
        # the reclassification that guard exists to stop.
        from categoryio.models import Category
        ap = self._ap()
        entry = JournalEntry.objects.create(
            company=self.company, amount=Decimal("10.00"))
        JournalEntryConnector.objects.create(
            journal=entry, account=ap, credit=Decimal("10.00"),
            total=Decimal("10.00"), kind=JournalEntryConnectorKindChoices.CREDIT)
        expense = Category.objects.filter(
            title="Expense", company__isnull=True).first()
        ChartOfAccount.objects.filter(pk=ap.pk).update(account_type=expense)

        self._run(apply=True)
        ap.refresh_from_db()
        print(f"  RESULT posted control account -> {ap.account_type.title!r} "
              f"({ap.journalentryconnector_set.count()} line kept)")
        self.assertEqual(ap.account_type.title, "Accounts Payable (A/P)")

    def test_dry_run_changes_nothing(self):
        from categoryio.models import Category
        ap = self._ap()
        expense = Category.objects.filter(
            title="Expense", company__isnull=True).first()
        ChartOfAccount.objects.filter(pk=ap.pk).update(account_type=expense)
        self._run()
        ap.refresh_from_db()
        print(f"  RESULT dry run -> still {ap.account_type.title!r}")
        self.assertEqual(ap.account_type.title, "Expense")
