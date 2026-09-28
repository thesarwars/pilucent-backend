"""DELETE could remove an account that had already been posted to.

`perform_destroy` checked two things -- `is_fixed`, and whether the account was
somebody's parent -- and then set `status = REMOVED`. No balance check, no
journal-history check, no check on what still mapped to it.

The damage is quiet. The delete is soft, and `JournalEntryConnector.account` is
`PROTECT`, so the lines survive -- but PROTECT guards a *hard* delete and this is
a status flip, so it never fires. `get_status_all()` then drops the account from
the balance sheet while its journal lines stay in the ledger: assets fall, the
other side does not, and the statement stops balancing with nothing raising
anywhere.

Two reasons it stayed hidden. Seeding marks nearly every account `is_fixed`
(3,573 of 3,759 live rows), so the accounts that could reach the rest of the
method were only the few a tenant had built themselves. And the original gap
analysis specified this check alongside the `is_fixed` one -- `14b110c0` shipped
the first half only.

Spec BLZ-FIN-COA-SPEC-001 §9.5: delete is for hygiene, "allowed when the account
has zero postings ever, no children, no references, and is not a system account.
Everything else is soft-only through deactivation."

This makes DELETE **strictly stricter** -- nothing that was refused becomes
allowed. That matters: the `is_fixed` gate is doing load-bearing work it was
never meant to (it is the only thing protecting title-resolved payroll accounts
from rename), so loosening anything here would be unsafe until that is untangled.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
)
from accounts.models import ChartOfAccount, User

from companyio.choices import CompanyKindChoices
from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from productio.models import Product

from rest_framework.exceptions import ValidationError


class FakeRequest:
    def __init__(self, user):
        self.user = user


class DeletePreconditionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="A", email="a@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    _seq = 0

    def account(self, title="Tenant Account", **kwargs):
        type(self)._seq += 1
        kwargs.setdefault("kind", ChartOfAccountKindChoices.EXPENSES)
        kwargs.setdefault("status", Status.ACTIVE)
        kwargs.setdefault("opening_balance", Decimal("0"))
        kwargs.setdefault("is_fixed", False)
        return ChartOfAccount.objects.create(
            company=self.company, title=f"{title} {type(self)._seq}",
            code=f"69{type(self)._seq:02d}", **kwargs
        )

    def delete(self, account):
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
        )

        view = PrivateWeChartOfAccountDetails()
        view.request = FakeRequest(self.user)
        return view.perform_destroy(account)

    def post_a_line(self, account, amount=Decimal("40000")):
        entry = JournalEntry.objects.create(
            company=self.company, entry_number=f"JE-{account.pk}",
            amount=amount, status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        JournalEntryConnector.objects.create(
            journal=entry, account=account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=amount, credit=0, total=amount, last_balance=0,
        )
        return entry

    # ------------------------------------------------------------ still works

    def test_a_clean_account_still_deletes(self):
        account = self.account()

        self.delete(account)

        account.refresh_from_db()
        self.assertEqual(account.status, Status.REMOVED)

    # -------------------------------------------------------- journal history

    def test_an_account_with_posted_lines_is_refused(self):
        """The one that silently unbalanced the balance sheet."""
        account = self.account("Equipment & Machinery")
        self.post_a_line(account)

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("COA-154", str(caught.exception))
        account.refresh_from_db()
        self.assertEqual(account.status, Status.ACTIVE)

    def test_the_refusal_points_at_deactivation(self):
        """Deactivate exists now and is the correct destination."""
        account = self.account()
        self.post_a_line(account)

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("inactive", str(caught.exception).lower())

    def test_the_journal_lines_survive_the_refusal(self):
        account = self.account()
        self.post_a_line(account)

        with self.assertRaises(ValidationError):
            self.delete(account)

        self.assertTrue(account.has_journal_lines())

    # --------------------------------------------------------------- balance

    def test_an_account_holding_a_balance_is_refused(self):
        account = self.account(opening_balance=Decimal("250.00"))

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("COA-150", str(caught.exception))
        self.assertIn("250", str(caught.exception))

    # ------------------------------------------------------------ references

    def test_a_live_mapping_is_refused(self):
        account = self.account(
            "Consulting Revenue", kind=ChartOfAccountKindChoices.INCOMES
        )
        Product.objects.create(
            company=self.company, title="Advisory day", income_account=account,
            quantity=0, date=date(2026, 8, 1),
        )

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("COA-151", str(caught.exception))

    # ------------------------------------------- nothing became more permissive

    def test_a_control_account_is_still_refused(self):
        """`is_fixed` is unchanged. This must not have loosened."""
        account = self.account(is_fixed=True)

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("control account", str(caught.exception).lower())

    def test_a_parent_is_still_refused(self):
        parent = self.account("Marketing")
        self.account("Marketing Digital", parent=parent)

        with self.assertRaises(ValidationError) as caught:
            self.delete(parent)

        self.assertIn("parent", str(caught.exception).lower())

    def test_the_is_fixed_guard_runs_before_the_new_ones(self):
        """A control account must report as one, not as "has history"."""
        account = self.account(is_fixed=True)
        self.post_a_line(account)

        with self.assertRaises(ValidationError) as caught:
            self.delete(account)

        self.assertIn("control account", str(caught.exception).lower())
        self.assertNotIn("COA-154", str(caught.exception))


class DeleteMatchesDeactivateTests(TestCase):
    """The two paths must not disagree about what is safe to retire."""

    def test_delete_enforces_what_deactivate_enforces(self):
        import inspect

        from weapi.django_rest.views import chart_of_accounts

        source = inspect.getsource(chart_of_accounts.PrivateWeChartOfAccountDetails)

        for check in ("has_journal_lines()", "blocking_references(", "COA-150", "COA-151"):
            with self.subTest(check=check):
                self.assertIn(check, source)

    def test_delete_is_stricter_than_deactivate_not_looser(self):
        """Deactivate permits posted history; delete must not.

        An account with a past is exactly what deactivation is for, and exactly
        what delete has to refuse -- otherwise the softer action is the safer
        one, which is backwards.
        """
        import inspect

        from weapi.django_rest.views import chart_of_accounts

        deactivate = inspect.getsource(
            chart_of_accounts.PrivateWeChartOfAccountDeactivate
        )
        delete = inspect.getsource(chart_of_accounts.PrivateWeChartOfAccountDetails)

        self.assertNotIn("has_journal_lines()", deactivate)
        self.assertIn("has_journal_lines()", delete)
