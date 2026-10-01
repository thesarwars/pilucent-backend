"""The census nobody had: what the 32 drifting accounts are actually made of.

`audit_ledger --only drift` reports a total. It does not say which accounts can
safely be recomputed, which would be destroyed by recomputing, or -- the question
that blocks any repair -- which of the two defensible definitions of "the journal
total" a repair should use.

These tests pin the classification, and in particular the two buckets that must
never be recomputed automatically:

* **UNBACKED** -- a balance with no journal lines. Recompute means zero, and on
  production that is `Import - Wages` at -4,000,000.
* **CONTROL_TYPED** -- a control account carrying a figure a human entered.

and the one that most likely can be: **SIGN_INVERTED**, where `stored` is exactly
`-journal`, the signature of a writer that has since been fixed.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices,
)
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector


class RepairAccountBalancesTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Drifty", kind="ECOMMERCE")

    def account(self, title, kind, stored, system_key=None):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal(stored), system_key=system_key,
        )

    def leg(self, account, debit="0", credit="0", status=None):
        entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.JOURNAL_ENTRY,
            status=status or JournalEntryStatusChoices.PUBLISHED,
            date=date(2026, 3, 1), amount=Decimal(debit) or Decimal(credit),
        )
        return JournalEntryConnector.objects.create(
            journal=entry, account=account, date=date(2026, 3, 1),
            debit=Decimal(debit), credit=Decimal(credit),
            kind=(
                JournalEntryConnectorKindChoices.DEBIT
                if Decimal(debit)
                else JournalEntryConnectorKindChoices.CREDIT
            ),
        )

    def run_command(self, **kwargs):
        out = StringIO()
        call_command("repair_account_balances", stdout=out, **kwargs)
        return out.getvalue()


class ItClassifiesTests(RepairAccountBalancesTestCase):
    def test_an_account_that_agrees_is_not_reported(self):
        agreeing = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "100")
        self.leg(agreeing, debit="100")

        self.assertIn("No drift found", self.run_command())

    def test_a_plain_mismatch_is_repairable(self):
        self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(ChartOfAccount.objects.get(title="Cash"), debit="100")

        output = self.run_command()
        self.assertIn("REPAIRABLE", output)
        self.assertIn("Cash", output)

    def test_a_balance_with_no_legs_is_unbacked_and_never_recomputed(self):
        """`Import - Wages` holds -4,000,000 this way on production."""
        self.account("Import - Wages", ChartOfAccountKindChoices.EXPENSES, "-4000")

        output = self.run_command()
        self.assertIn("UNBACKED", output)
        self.assertIn("NEVER recompute", output)

    def test_an_exact_sign_inversion_is_called_out_separately(self):
        """`stored == -journal` to the penny: a writer that has since been fixed."""
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES, "19098.52"
        )
        # A liability's natural direction is credit, so a debit leg of 19,098.52
        # derives -19,098.52 -- the exact negative of what is stored.
        self.leg(payable, debit="19098.52")

        output = self.run_command()
        self.assertIn("SIGN_INVERTED", output)

    def test_a_control_account_carrying_drift_is_held_back(self):
        """Pilucent INC's A/R holds 2,399,995 a human entered."""
        receivable = self.account(
            "Accounts Receivable (A/R)", ChartOfAccountKindChoices.ASSETS,
            "2399995", system_key=ChartOfAccountSystemKeyChoices.AR,
        )
        self.leg(receivable, debit="5")

        output = self.run_command()
        self.assertIn("CONTROL_TYPED", output)
        self.assertIn("erases a decision", output)

    def test_a_zero_balance_with_no_legs_is_not_drift(self):
        self.account("Unused", ChartOfAccountKindChoices.ASSETS, "0")
        self.assertIn("No drift found", self.run_command())


class ItMeasuresTheBasisQuestionTests(RepairAccountBalancesTestCase):
    """The measurement that decides what a repair should even write."""

    def test_it_reports_when_the_two_definitions_agree(self):
        self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(ChartOfAccount.objects.get(title="Cash"), debit="100")

        self.assertIn("the two definitions agree", self.run_command())

    def test_a_draft_leg_makes_the_basis_matter_and_is_surfaced(self):
        """A DRAFT entry moves the stored column but the register hides it."""
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        self.leg(cash, debit="40", status=JournalEntryStatusChoices.DRAFT)

        output = self.run_command()
        self.assertIn("depends on the basis chosen: 1", output)

    def test_a_removed_leg_counts_the_same_way(self):
        """`DELETE /we/journals/{uid}` sets REMOVED and reverses nothing."""
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        self.leg(cash, debit="40", status=JournalEntryStatusChoices.REMOVED)

        self.assertIn("depends on the basis chosen: 1", self.run_command())

    def test_a_basis_dependent_account_that_does_NOT_drift_is_still_counted(self):
        """The commonest shape, and the one an earlier version could not see.

        Delete a manual journal entry and its balance is never backed out
        (`views/journals.py:86-88`). The stored column and the all-legs total
        then agree perfectly -- and are both wrong by the deleted entry. Keying
        the basis measurement off the drift results filtered exactly this case
        out, so the census reported zero and looked reassuring.
        """
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "140")
        self.leg(cash, debit="100")
        self.leg(cash, debit="40", status=JournalEntryStatusChoices.REMOVED)

        output = self.run_command()
        # Stored 140 == all-legs 140, so it is NOT drift...
        self.assertIn("No drift found", output)
        # ...but it IS basis-dependent, and the census must say so.
        self.assertIn("depends on the basis chosen: 1", output)
        self.assertIn("never backed out", output)

    def test_the_summary_says_how_many_basis_dependent_accounts_also_drift(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "140")
        self.leg(cash, debit="100")
        self.leg(cash, debit="40", status=JournalEntryStatusChoices.REMOVED)

        self.assertIn("0 of them also drift", self.run_command())


class ItWritesNothingWithoutApplyTests(RepairAccountBalancesTestCase):
    """Dry run is the default, and that is load-bearing."""

    def test_the_stored_balance_is_left_exactly_as_it_was(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        self.run_command()

        cash.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("150.000"))

    def test_no_journal_entry_is_created(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        before = JournalEntry.objects.count()

        self.run_command()

        self.assertEqual(JournalEntry.objects.count(), before)

    def test_a_dry_run_says_how_to_apply(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        self.assertIn("--apply", self.run_command())


class ApplyingIsGatedTests(RepairAccountBalancesTestCase):
    def test_apply_without_a_company_is_refused(self):
        """One company at a time, so the change is reviewable."""
        from django.core.management.base import CommandError

        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        with self.assertRaises(CommandError) as caught:
            self.run_command(apply=True)
        self.assertIn("--apply requires --company", str(caught.exception))

        cash.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("150.000"))

    def test_it_repairs_a_plain_mismatch(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        output = self.run_command(company="Drifty", apply=True)

        cash.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("100.000"))
        self.assertIn("1 account(s) repaired", output)

    def test_it_repairs_a_sign_inversion(self):
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES, "19098.52"
        )
        self.leg(payable, debit="19098.52")

        self.run_command(company="Drifty", apply=True)

        payable.refresh_from_db()
        self.assertEqual(payable.opening_balance, Decimal("-19098.520"))

    def test_it_refuses_to_touch_a_control_account(self):
        """Recomputing erases a decision rather than a defect."""
        receivable = self.account(
            "Accounts Receivable (A/R)", ChartOfAccountKindChoices.ASSETS,
            "2399995", system_key=ChartOfAccountSystemKeyChoices.AR,
        )
        self.leg(receivable, debit="5")

        self.run_command(company="Drifty", apply=True)

        receivable.refresh_from_db()
        self.assertEqual(receivable.opening_balance, Decimal("2399995.000"))

    def test_it_refuses_to_touch_an_unbacked_balance(self):
        """Recompute means zero, and four million stops existing."""
        imported = self.account(
            "Import - Wages", ChartOfAccountKindChoices.EXPENSES, "-4000000"
        )

        self.run_command(company="Drifty", apply=True)

        imported.refresh_from_db()
        self.assertEqual(imported.opening_balance, Decimal("-4000000.000"))

    def test_only_narrows_what_is_written(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        payable = self.account(
            "Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES, "19098.52"
        )
        self.leg(payable, debit="19098.52")

        self.run_command(company="Drifty", apply=True, only="SIGN_INVERTED")

        cash.refresh_from_db()
        payable.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("150.000"))
        self.assertEqual(payable.opening_balance, Decimal("-19098.520"))

    def test_only_cannot_widen_past_the_writable_buckets(self):
        """`--only CONTROL_TYPED --apply` must still write nothing."""
        receivable = self.account(
            "Accounts Receivable (A/R)", ChartOfAccountKindChoices.ASSETS,
            "2399995", system_key=ChartOfAccountSystemKeyChoices.AR,
        )
        self.leg(receivable, debit="5")

        self.run_command(company="Drifty", apply=True, only="CONTROL_TYPED")

        receivable.refresh_from_db()
        self.assertEqual(receivable.opening_balance, Decimal("2399995.000"))

    def test_running_it_twice_is_a_no_op(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        self.run_command(company="Drifty", apply=True)
        second = self.run_command(company="Drifty", apply=True)

        cash.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("100.000"))
        self.assertIn("No drift found", second)

    def test_it_posts_no_journal_entry(self):
        """The balance is a cache of the journal, not an event to record."""
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        before = JournalEntry.objects.count()

        self.run_command(company="Drifty", apply=True)

        self.assertEqual(JournalEntry.objects.count(), before)

    def test_the_change_is_recorded_in_auditlog(self):
        """`update_opening_balance` writes through a queryset and is audit-blind.

        A repair is exactly the write that has to be recoverable afterwards, so
        it goes through `.save()`.
        """
        from auditlog.models import LogEntry

        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        before = LogEntry.objects.count()

        self.run_command(company="Drifty", apply=True)

        self.assertGreater(LogEntry.objects.count(), before)

    def test_an_account_someone_else_already_fixed_is_left_alone(self):
        """Re-derived under the lock, not trusted from the scan."""
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        # Simulate the scan seeing drift and the row being corrected before the
        # write lands, by having the ledger move to agree with the stored value.
        from accounts.management.commands.repair_account_balances import Command

        command = Command()
        command.stdout = type("S", (), {"write": lambda self, *a, **k: None})()
        command.style = type("St", (), {
            "MIGRATE_HEADING": staticmethod(lambda x: x),
            "SUCCESS": staticmethod(lambda x: x),
            "WARNING": staticmethod(lambda x: x),
        })()
        stale = [{
            "account_id": cash.id, "bucket": "REPAIRABLE",
            "account": "Cash", "stored": Decimal("999"),
        }]
        command._apply(self.company, stale, None)

        cash.refresh_from_db()
        self.assertEqual(cash.opening_balance, Decimal("100.000"))


class ItScopesAndExportsTests(RepairAccountBalancesTestCase):
    def test_another_companys_account_is_not_reported(self):
        other = Company.objects.create(name="Elsewhere", kind="ECOMMERCE")
        ChartOfAccount.objects.create(
            company=other, title="Their Cash", code="TC",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("999"),
        )
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        output = self.run_command(company="Drifty")
        self.assertIn("Cash", output)
        self.assertNotIn("Their Cash", output)

    def test_a_numeric_selector_is_an_id_not_a_uid_prefix(self):
        """`purge_companies` matched a uid prefix and named the wrong company."""
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")

        self.assertIn("Cash", self.run_command(company=str(self.company.id)))

    def test_csv_carries_both_bases_per_account(self):
        cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(cash, debit="100")
        self.leg(cash, debit="40", status=JournalEntryStatusChoices.DRAFT)

        output = self.run_command(csv="-")
        self.assertIn("derived_all_legs", output)
        self.assertIn("derived_published", output)
        self.assertIn("status_gap", output)


class TheCompanySelectorIsStrictForWritesTests(RepairAccountBalancesTestCase):
    """`--company X` selected "Halo Axis" on production and repaired it.

    A substring matched with `icontains`, so a single letter picked a company
    nobody had named -- and it did so with `--apply` against live books. The
    repair happened to be correct and the company happened to be a legitimate
    target; neither was by design.
    """

    def setUp(self):
        super().setUp()
        self.halo = Company.objects.create(name="Halo Axis", kind="ECOMMERCE")
        self.cash = self.account("Cash", ChartOfAccountKindChoices.ASSETS, "150")
        self.leg(self.cash, debit="100")

    def test_a_single_letter_cannot_select_a_company_for_a_write(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as caught:
            self.run_command(company="X", apply=True)

        self.assertIn("will not accept a partial name", str(caught.exception))
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.opening_balance, Decimal("150.000"))

    def test_a_partial_name_is_refused_for_a_write_even_when_unambiguous(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(company="Drift", apply=True)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.opening_balance, Decimal("150.000"))

    def test_the_full_name_writes(self):
        self.run_command(company="Drifty", apply=True)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.opening_balance, Decimal("100.000"))

    def test_the_numeric_id_writes(self):
        self.run_command(company=str(self.company.id), apply=True)

        self.cash.refresh_from_db()
        self.assertEqual(self.cash.opening_balance, Decimal("100.000"))

    def test_apply_says_which_company_it_resolved_to_before_writing(self):
        output = self.run_command(company="Drifty", apply=True)
        self.assertIn("about to write to 'Drifty'", output)

    def test_an_ambiguous_substring_is_an_error_not_the_lowest_id(self):
        """Reading a substring is still allowed, but never silently narrowed."""
        from django.core.management.base import CommandError

        Company.objects.create(name="Drifty Two", kind="ECOMMERCE")

        with self.assertRaises(CommandError) as caught:
            self.run_command(company="Drift")

        self.assertIn("matches 2 companies", str(caught.exception))

    def test_reading_still_accepts_an_unambiguous_substring(self):
        """Costs nothing to get wrong, and is obvious on screen when you do."""
        self.assertIn("Cash", self.run_command(company="rifty"))

    def test_a_substring_read_resolves_to_the_company_it_names(self):
        """`Halo` is the other company here, and it holds no accounts."""
        self.assertIn("No drift found", self.run_command(company="Halo"))


class IncludeControlTests(RepairAccountBalancesTestCase):
    """`--include-control` widens the repair to control accounts. Nothing
    widens it to unbacked ones.

    The default hold-back was right as a default and wrong about these
    particular accounts. The tool buckets on `system_key`, which says "control
    account", not "a human entered this figure" -- and the production equation
    audit showed equity agreeing to the penny between the stored column and the
    journal at both drifting companies, so no stored-only Opening Balance Equity
    counterpart existed. A typed opening balance posts a paired entry, so one
    would have. These had drifted like any other account.
    """

    def setUp(self):
        super().setUp()
        self.receivable = self.account(
            "Accounts Receivable (A/R)", ChartOfAccountKindChoices.ASSETS,
            "2399995", system_key=ChartOfAccountSystemKeyChoices.AR,
        )
        self.leg(self.receivable, debit="5")
        self.imported = self.account(
            "Import - Wages", ChartOfAccountKindChoices.EXPENSES, "-4000000"
        )

    def test_without_the_flag_a_control_account_is_untouched(self):
        self.run_command(company="Drifty", apply=True)

        self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.opening_balance, Decimal("2399995.000"))

    def test_with_the_flag_a_control_account_is_repaired(self):
        output = self.run_command(company="Drifty", apply=True, include_control=True)

        self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.opening_balance, Decimal("5.000"))
        self.assertIn("1 account(s) repaired", output)

    def test_the_flag_never_reaches_an_unbacked_balance(self):
        """Four million whose only record is the column a recompute clears."""
        self.run_command(company="Drifty", apply=True, include_control=True)

        self.imported.refresh_from_db()
        self.assertEqual(self.imported.opening_balance, Decimal("-4000000.000"))

    def test_only_unbacked_with_the_flag_still_writes_nothing(self):
        self.run_command(
            company="Drifty", apply=True, include_control=True, only="UNBACKED"
        )

        self.imported.refresh_from_db()
        self.assertEqual(self.imported.opening_balance, Decimal("-4000000.000"))

    def test_the_never_writable_set_survives_a_careless_future_flag(self):
        """`_writable` filters it out whatever the buckets add up to."""
        from accounts.management.commands.repair_account_balances import (
            Command,
            NEVER_WRITABLE,
        )

        for include_control in (True, False):
            writable = Command()._writable(include_control)
            for bucket in NEVER_WRITABLE:
                self.assertNotIn(bucket, writable)

    def test_the_flag_still_needs_an_exact_company(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(company="Drift", apply=True, include_control=True)

        self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.opening_balance, Decimal("2399995.000"))

    def test_the_flag_does_nothing_without_apply(self):
        self.run_command(company="Drifty", include_control=True)

        self.receivable.refresh_from_db()
        self.assertEqual(self.receivable.opening_balance, Decimal("2399995.000"))
