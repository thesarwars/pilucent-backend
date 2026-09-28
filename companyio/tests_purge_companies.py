"""Deleting a tenant permanently, and the wall that normally stops it.

All four PROTECT foreign keys in this schema live on `JournalEntryConnector`,
and PROTECT fires even from inside the same cascade, so an ordinary
`Company.delete()` raises rather than taking the books with it. That guard is
correct for every tenant-facing path -- the superadmin API soft-removes instead.

The Django admin stands in for a database GUI, where a delete is meant to be
final. These pin that the teardown is complete (nothing left pointing at a dead
company), ordered (no half-deleted entries), and honest (the leg count is shown
before anything is written).
"""

from decimal import Decimal
from io import StringIO

from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.admin import CompanyAdmin
from companyio.deletion import count_ledger_legs, purge_companies
from companyio.models import Company, CompanyUser

from customerio.models import Customer

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from salesio.models import Sale, SaleItem


class CompanyPurgeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Junk Test Co")
        self.keeper = Company.objects.create(name="Real Co")

    def post_ledger(self, company, legs=2):
        """A company with real bookkeeping: an entry and its balanced legs."""
        account = ChartOfAccount.objects.create(
            company=company,
            title="Wages",
            code="6000",
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        entry = JournalEntry.objects.create(
            company=company, kind=JournalEntryKindChoices.PAYROLL_SALARY_PROCESS
        )
        for index in range(legs):
            JournalEntryConnector.objects.create(
                journal=entry,
                account=account,
                kind=(
                    JournalEntryConnectorKindChoices.DEBIT
                    if index % 2 == 0
                    else JournalEntryConnectorKindChoices.CREDIT
                ),
                debit=Decimal("250.32") if index % 2 == 0 else 0,
                credit=0 if index % 2 == 0 else Decimal("250.32"),
            )
        return entry, account

    def purge(self, *args):
        out = StringIO()
        call_command("purge_companies", *args, stdout=out, stderr=out)
        return out.getvalue()

    # -- the wall this exists to get past -----------------------------------

    def test_a_plain_delete_still_raises(self):
        """Guards the premise: PROTECT must keep stopping the ordinary path."""
        from django.db.models.deletion import ProtectedError

        self.post_ledger(self.company)

        with self.assertRaises(ProtectedError):
            Company.objects.filter(pk=self.company.pk).delete()

        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    # -- the teardown --------------------------------------------------------

    def test_a_company_with_books_is_deleted_whole(self):
        entry, account = self.post_ledger(self.company)

        purge_companies(Company.objects.filter(pk=self.company.pk))

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(ChartOfAccount.objects.filter(pk=account.pk).exists())
        self.assertFalse(
            JournalEntryConnector.objects.filter(journal_id=entry.pk).exists()
        )

    def test_no_entry_is_left_holding_half_its_legs(self):
        """The failure the teardown order exists to prevent.

        A cascade into the connectors deletes some legs and leaves JournalEntry
        -- which has no FK to an account or a line item -- holding the rest.
        Permanently unbalanced, with nothing recording why.
        """
        entry, _ = self.post_ledger(self.company, legs=4)

        purge_companies(Company.objects.filter(pk=self.company.pk))

        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())
        self.assertEqual(
            JournalEntryConnector.objects.filter(journal_id=entry.pk).count(), 0
        )

    def test_another_companys_ledger_is_untouched(self):
        self.post_ledger(self.company)
        keeper_entry, keeper_account = self.post_ledger(self.keeper)

        purge_companies(Company.objects.filter(pk=self.company.pk))

        self.assertTrue(Company.objects.filter(pk=self.keeper.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=keeper_entry.pk).exists())
        self.assertEqual(
            JournalEntryConnector.objects.filter(journal_id=keeper_entry.pk).count(), 2
        )
        self.assertTrue(ChartOfAccount.objects.filter(pk=keeper_account.pk).exists())

    def test_legs_reached_through_a_sale_line_are_collected(self):
        """`saleitem` is a PROTECT route of its own, not just `journal`."""
        entry, account = self.post_ledger(self.company)
        customer = Customer.objects.create(company=self.company, first_name="Acme")
        sale = Sale.objects.create(company=self.company, customer=customer)
        item = SaleItem.objects.create(sale=sale)
        JournalEntryConnector.objects.create(
            journal=entry,
            account=account,
            saleitem=item,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("10"),
            credit=0,
        )

        self.assertEqual(count_ledger_legs([self.company]), 3)

        purge_companies(Company.objects.filter(pk=self.company.pk))

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(SaleItem.objects.filter(pk=item.pk).exists())

    def test_a_company_with_no_books_deletes_too(self):
        purge_companies(Company.objects.filter(pk=self.company.pk))
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_members_go_but_the_user_stays(self):
        user = User.objects.create_user(
            name="Member", email="member@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=user, company=self.company)

        purge_companies(Company.objects.filter(pk=self.company.pk))

        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(CompanyUser.objects.filter(user=user).exists())

    # -- the command ---------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        self.post_ledger(self.company)

        output = self.purge(str(self.company.id))

        self.assertIn("Dry run", output)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertEqual(JournalEntryConnector.objects.count(), 2)

    def test_dry_run_states_the_cost_in_legs(self):
        self.post_ledger(self.company, legs=4)

        output = self.purge(str(self.company.id))

        self.assertIn("4 journal leg(s) will be destroyed", output)
        self.assertIn("irreversible", output)

    def test_apply_deletes(self):
        self.post_ledger(self.company)

        self.purge(str(self.company.id), "--apply")

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_the_eight_character_uid_prefix_from_the_admin_resolves(self):
        # Pinned rather than taken from a random uid. Roughly one uid in forty
        # begins with eight digits, which is indistinguishable from a company
        # id -- so this assertion used to fail about 2% of runs, and the flake
        # was the bug (see AmbiguousIdentifierTests).
        Company.objects.filter(pk=self.company.pk).update(
            uid="9511db03-698a-4c52-bde3-eea1b88aa7a1"
        )
        output = self.purge("9511db03")

        self.assertIn("Companies to delete: 1", output)
        self.assertIn("Junk Test Co", output)

    def test_an_all_digit_prefix_is_disambiguated_explicitly(self):
        """The case that used to resolve as an id and name another company."""
        Company.objects.filter(pk=self.company.pk).update(
            uid="12345678-698a-4c52-bde3-eea1b88aa7a1"
        )
        output = self.purge("uid:12345678")

        self.assertIn("Companies to delete: 1", output)
        self.assertIn("Junk Test Co", output)

    def test_full_uid_and_numeric_id_resolve(self):
        for identifier in (str(self.company.uid), str(self.company.id)):
            with self.subTest(identifier=identifier):
                self.assertIn("Companies to delete: 1", self.purge(identifier))

    def test_comma_separated_identifiers_are_accepted(self):
        output = self.purge(f"{self.company.id},{self.keeper.id}")
        self.assertIn("Companies to delete: 2", output)

    def test_keep_with_books_skips_the_transacting_one(self):
        self.post_ledger(self.company)

        output = self.purge(
            str(self.company.id), str(self.keeper.id), "--keep-with-books", "--apply"
        )

        self.assertIn("SKIPPED, still holding books", output)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(Company.objects.filter(pk=self.keeper.pk).exists())

    def test_no_match_is_an_error(self):
        with self.assertRaises(CommandError):
            self.purge("99999")

    def test_garbage_identifier_is_an_error(self):
        with self.assertRaises(CommandError):
            self.purge("not-a-uid-or-id")

    # -- the admin path ------------------------------------------------------

    def test_the_admin_no_longer_refuses(self):
        """The 'Cannot delete Companiess' page, gone.

        `get_deleted_objects` returning a non-empty `protected` is what renders
        that refusal. The rows are still deleted -- by `delete_queryset` -- so
        reporting them as blockers would refuse an operation that succeeds.
        """
        self.post_ledger(self.company)
        modeladmin = CompanyAdmin(Company, AdminSite())
        request = RequestFactory().post("/admin/companyio/company/")
        request.user = User.objects.create_superuser(
            name="Root", email="root@example.com", password="pass1234!"
        )

        queryset = Company.objects.filter(pk=self.company.pk)
        _, model_count, _, protected = modeladmin.get_deleted_objects(queryset, request)

        self.assertEqual(list(protected), [])
        self.assertIn(
            "journal entry connectors (ledger, IRREVERSIBLE)",
            model_count,
            "the confirmation page must still state the ledger cost",
        )
        self.assertEqual(model_count["journal entry connectors (ledger, IRREVERSIBLE)"], 2)

    def test_admin_delete_queryset_tears_the_ledger_down(self):
        entry, _ = self.post_ledger(self.company)
        modeladmin = CompanyAdmin(Company, AdminSite())
        request = RequestFactory().post("/admin/companyio/company/")

        modeladmin.delete_queryset(request, Company.objects.filter(pk=self.company.pk))

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())

    def test_admin_delete_model_tears_the_ledger_down(self):
        self.post_ledger(self.company)
        modeladmin = CompanyAdmin(Company, AdminSite())
        request = RequestFactory().post("/admin/companyio/company/")

        modeladmin.delete_model(request, self.company)

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())


class AmbiguousIdentifierTests(TestCase):
    """An 8-digit token is both a company id and a uid prefix.

    `parse_identifiers` tested `isdigit()` before the uid-prefix branch, so such
    a token silently became an id. Roughly one uid in forty starts with eight
    digits, so an operator copying a prefix out of the admin had about a 2%
    chance of naming a different company -- and this command destroys what it
    names. It is also why `test_the_eight_character_uid_prefix_from_the_admin_resolves`
    flaked: the fixture's random uid occasionally started with eight digits.

    Ambiguity cannot be resolved from the token, so it is refused rather than
    guessed.
    """

    def parse(self, *tokens):
        from companyio.management.commands.purge_companies import Command

        return Command().parse_identifiers(list(tokens))

    def test_an_eight_digit_token_is_refused_rather_than_guessed(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as caught:
            self.parse("12345678")
        self.assertIn("Ambiguous", str(caught.exception))
        self.assertIn("id:", str(caught.exception))
        self.assertIn("uid:", str(caught.exception))

    def test_an_explicit_id_resolves_as_an_id(self):
        uids, prefixes, ids, bad = self.parse("id:12345678")
        self.assertEqual(ids, [12345678])
        self.assertEqual((uids, prefixes, bad), ([], [], []))

    def test_an_explicit_uid_prefix_resolves_as_a_prefix(self):
        uids, prefixes, ids, bad = self.parse("uid:12345678")
        self.assertEqual(prefixes, ["12345678"])
        self.assertEqual((uids, ids, bad), ([], [], []))

    def test_an_unambiguous_short_id_still_works_bare(self):
        _, _, ids, bad = self.parse("42")
        self.assertEqual((ids, bad), ([42], []))

    def test_an_unambiguous_hex_prefix_still_works_bare(self):
        _, prefixes, _, bad = self.parse("9511db03")
        self.assertEqual((prefixes, bad), (["9511db03"], []))

    def test_a_full_uid_still_works_bare(self):
        import uuid as uuid_module

        value = uuid_module.uuid4()
        uids, prefixes, ids, bad = self.parse(str(value))
        self.assertEqual(uids, [value])
        self.assertEqual((prefixes, ids, bad), ([], [], []))

    def test_an_explicit_full_uid_resolves(self):
        import uuid as uuid_module

        value = uuid_module.uuid4()
        uids, _, _, bad = self.parse(f"uid:{value}")
        self.assertEqual((uids, bad), ([value], []))

    def test_a_nonsense_explicit_token_is_unparseable_not_a_crash(self):
        _, _, ids, bad = self.parse("id:notanumber")
        self.assertEqual(ids, [])
        self.assertEqual(bad, ["id:notanumber"])
