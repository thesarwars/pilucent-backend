"""Who may write a journal line through `PATCH /we/journals/{uid}`, and what.

`PrivateWeJournalEntryDetailsSerializer.journal_items` is a raw `JSONField`, so
its contents reached the model without passing a single serializer field. The
update branch was:

    JournalEntryConnector.objects.filter(uid=item.get("uid")).update(**item)

Two independent holes in one line.

**No tenant scope.** The filter carried neither a company clause nor a
`journal=instance` clause, so *any* uid in `journalio_journalentryconnector`
resolved. `journalio` is in none of the three RLS table lists
(`companyio/migrations/0023`, `0025`, `0026`), so unlike Customer, Product, Sale
or Supplier there was no database backstop underneath the missing filter --
this was the whole control, and it was absent. Three of the five related
lookups above it (`ChartOfAccount`, `Customer`, `Warehouse`) were likewise
unscoped `.get(uid=...)` calls.

**No field allow-list.** `**item` wrote whatever the payload named, including
`reconciliation` and `cleared_on` -- the pair that *is* the reconcile status
(`transactionio/.../reconciliation.py:446-451`). A caller could therefore mark a
line reconciled without opening a reconciliation, or point it at a session that
undo would then skip, stranding it as permanently unreconcilable.

Separately, the *create* path mutated the stored balance with a hard-coded
side: a DEBIT leg always added and a CREDIT leg always subtracted.
`update_opening_balance`'s second argument is add/subtract in the account's own
direction, not an accounting side, so that is right for assets and expenses and
backwards for every liability, equity and income account. It is a live writer of
the drift `manage.py audit_ledger` measures.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.serializers.journals import (
    EDITABLE_JOURNAL_LINE_FIELDS,
    PrivateWeJournalEntryDetailsSerializer,
    PrivateWeJournalEntryListSerializer,
)

from rest_framework.serializers import ValidationError


class FakeRequest:
    def __init__(self, user):
        self.user = user


def make_account(company, title, kind=ChartOfAccountKindChoices.ASSETS, balance="0"):
    return ChartOfAccount.objects.create(
        company=company,
        title=title,
        code=title[:8],
        kind=kind,
        status=ChartOfAccountStatusChoices.ACTIVE,
        opening_balance=Decimal(balance),
    )


def make_entry(company):
    return JournalEntry.objects.create(
        company=company,
        kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
        status=JournalEntryStatusChoices.PUBLISHED,
    )


class JournalLineWriteScopingTests(TestCase):
    """A line outside the caller's own entry must not be writable."""

    def setUp(self):
        self.mine = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.theirs = Company.objects.create(name="Theirs", kind="ECOMMERCE")

        self.user = User.objects.create_user(
            name="A", email="journal-scope@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.mine)

        self.my_account = make_account(self.mine, "My Bank")
        self.their_account = make_account(self.theirs, "Their Bank")

        self.my_entry = make_entry(self.mine)
        self.their_entry = make_entry(self.theirs)

        self.their_line = JournalEntryConnector.objects.create(
            journal=self.their_entry,
            account=self.their_account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("100.000"),
            credit=Decimal("0.000"),
            description="theirs",
        )

    def serializer(self):
        return PrivateWeJournalEntryDetailsSerializer(
            context={"request": FakeRequest(self.user)}
        )

    def update(self, items):
        return self.serializer().update(
            self.my_entry, {"journal_items": items}
        )

    def test_a_line_on_another_companys_entry_is_refused(self):
        """The core hole: a foreign uid used to resolve and be rewritten."""
        with self.assertRaises(ValidationError):
            self.update(
                [
                    {
                        "uid": str(self.their_line.uid),
                        "account_uid": str(self.my_account.uid),
                        "kind": JournalEntryConnectorKindChoices.DEBIT,
                        "debit": "9999.000",
                        "credit": "0.000",
                    }
                ]
            )

        self.their_line.refresh_from_db()
        self.assertEqual(self.their_line.debit, Decimal("100.000"))
        self.assertEqual(self.their_line.journal_id, self.their_entry.id)
        self.assertEqual(self.their_line.account_id, self.their_account.id)

    def test_an_account_from_another_company_is_refused(self):
        with self.assertRaises(ValidationError):
            self.update(
                [
                    {
                        "account_uid": str(self.their_account.uid),
                        "kind": JournalEntryConnectorKindChoices.DEBIT,
                        "debit": "10.000",
                        "credit": "0.000",
                    }
                ]
            )
        self.assertFalse(
            JournalEntryConnector.objects.filter(journal=self.my_entry).exists()
        )

    def test_a_missing_account_uid_is_a_client_error_not_a_500(self):
        """It used to be `.get(uid=None)` -> DoesNotExist -> HTTP 500."""
        with self.assertRaises(ValidationError):
            self.update([{"kind": JournalEntryConnectorKindChoices.DEBIT}])

    def test_a_malformed_account_uid_is_a_client_error_not_a_500(self):
        with self.assertRaises(ValidationError):
            self.update([{"account_uid": "not-a-uuid"}])

    def test_a_line_on_the_callers_own_entry_still_updates(self):
        """The fix must not close the endpoint on its legitimate use."""
        mine = JournalEntryConnector.objects.create(
            journal=self.my_entry,
            account=self.my_account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("5.000"),
            credit=Decimal("0.000"),
        )
        self.update(
            [
                {
                    "uid": str(mine.uid),
                    "account_uid": str(self.my_account.uid),
                    "kind": JournalEntryConnectorKindChoices.DEBIT,
                    "debit": "42.000",
                    "credit": "0.000",
                    "description": "edited",
                }
            ]
        )
        mine.refresh_from_db()
        self.assertEqual(mine.debit, Decimal("42.000"))
        self.assertEqual(mine.description, "edited")

    def test_a_new_line_is_still_creatable(self):
        self.update(
            [
                {
                    "account_uid": str(self.my_account.uid),
                    "kind": JournalEntryConnectorKindChoices.CREDIT,
                    "debit": "0.000",
                    "credit": "7.000",
                }
            ]
        )
        line = JournalEntryConnector.objects.get(journal=self.my_entry)
        self.assertEqual(line.credit, Decimal("7.000"))


class JournalLineFieldAllowListTests(TestCase):
    """`**item` wrote whatever the payload named. Now it does not."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="B", email="journal-fields@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.account = make_account(self.company, "Bank")
        self.entry = make_entry(self.company)
        self.line = JournalEntryConnector.objects.create(
            journal=self.entry,
            account=self.account,
            kind=JournalEntryConnectorKindChoices.DEBIT,
            debit=Decimal("10.000"),
            credit=Decimal("0.000"),
        )

    def update(self, item):
        PrivateWeJournalEntryDetailsSerializer(
            context={"request": FakeRequest(self.user)}
        ).update(self.entry, {"journal_items": [item]})

    def base_item(self, **extra):
        item = {
            "uid": str(self.line.uid),
            "account_uid": str(self.account.uid),
            "kind": JournalEntryConnectorKindChoices.DEBIT,
            "debit": "10.000",
            "credit": "0.000",
        }
        item.update(extra)
        return item

    def test_reconcile_state_cannot_be_forged(self):
        """`reconciliation` + `cleared_on` are the reconcile status itself."""
        self.update(self.base_item(cleared_on="2026-01-31"))
        self.line.refresh_from_db()
        self.assertIsNone(self.line.cleared_on)
        self.assertIsNone(self.line.reconciliation_id)

    def test_derived_and_engine_owned_fields_cannot_be_set(self):
        self.update(
            self.base_item(
                last_balance="999999.000",
                total="888888.000",
                transaction_id="#JI-forged",
                request_kind="DELETED",
            )
        )
        self.line.refresh_from_db()
        self.assertEqual(self.line.last_balance, Decimal("0.000"))
        self.assertEqual(self.line.total, Decimal("0.000"))
        self.assertIsNone(self.line.transaction_id)
        self.assertEqual(self.line.request_kind, "CREATED")

    def test_an_unknown_posting_side_is_refused(self):
        with self.assertRaises(ValidationError):
            self.update(self.base_item(kind="SIDEWAYS"))

    def test_the_allow_list_holds_only_client_owned_fields(self):
        """Drift guard: adding a name here must be a deliberate decision.

        The list is small on purpose. Anything derived, engine-owned or
        reconcile-owned belongs outside it, and a future edit that widens it
        should have to change this assertion too. It worked: narrowing the list
        on 2026-09-02 failed this test, which is what it is for.
        """
        self.assertEqual(
            sorted(EDITABLE_JOURNAL_LINE_FIELDS),
            ["credit", "debit", "description", "kind"],
        )

    def test_a_line_cannot_be_dated_away_from_its_entry(self):
        """Header-authoritative dating, enforced at the one path that broke it.

        `create_journal_entry_connector` has always defaulted a leg's date to
        its entry's, and no writer ever set one to anything else -- except this
        allow-list, which let a client date a single line independently. A
        document whose legs sit in two periods leaves each of them individually
        unbalanced, so no period-scoped balance sheet could ever tie out.
        """
        self.assertNotIn("date", EDITABLE_JOURNAL_LINE_FIELDS)


class ManualJournalBalanceDirectionTests(TestCase):
    """A debit does not increase every account."""

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="C", email="journal-direction@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)

    def post(self, account, side, amount):
        serializer = PrivateWeJournalEntryListSerializer(
            context={"request": FakeRequest(self.user)}
        )
        serializer.create(
            {
                "company": self.company,
                "kind": JournalEntryKindChoices.CHART_OF_ACCOUNT,
                "journal_items": [
                    {
                        "account": account,
                        "kind": side,
                        "debit": (
                            Decimal(amount)
                            if side == JournalEntryConnectorKindChoices.DEBIT
                            else Decimal("0")
                        ),
                        "credit": (
                            Decimal(amount)
                            if side == JournalEntryConnectorKindChoices.CREDIT
                            else Decimal("0")
                        ),
                    }
                ],
            }
        )
        account.refresh_from_db()
        return account.opening_balance

    def test_a_debit_increases_an_asset(self):
        """The case the old hard-coding happened to get right."""
        account = make_account(
            self.company, "Bank", ChartOfAccountKindChoices.ASSETS, "100"
        )
        self.assertEqual(
            self.post(account, JournalEntryConnectorKindChoices.DEBIT, "40"),
            Decimal("140.000"),
        )

    def test_a_debit_decreases_a_liability(self):
        """The case it got backwards. A debit pays a liability down."""
        account = make_account(
            self.company, "Loan", ChartOfAccountKindChoices.LIABILITIES, "100"
        )
        self.assertEqual(
            self.post(account, JournalEntryConnectorKindChoices.DEBIT, "40"),
            Decimal("60.000"),
        )

    def test_a_credit_increases_a_liability(self):
        account = make_account(
            self.company, "Loan2", ChartOfAccountKindChoices.LIABILITIES, "100"
        )
        self.assertEqual(
            self.post(account, JournalEntryConnectorKindChoices.CREDIT, "40"),
            Decimal("140.000"),
        )

    def test_a_credit_increases_income(self):
        account = make_account(
            self.company, "Sales", ChartOfAccountKindChoices.INCOMES, "100"
        )
        self.assertEqual(
            self.post(account, JournalEntryConnectorKindChoices.CREDIT, "40"),
            Decimal("140.000"),
        )

    def test_a_credit_decreases_an_expense(self):
        account = make_account(
            self.company, "Rent", ChartOfAccountKindChoices.EXPENSES, "100"
        )
        self.assertEqual(
            self.post(account, JournalEntryConnectorKindChoices.CREDIT, "40"),
            Decimal("60.000"),
        )


class ManualJournalEntryKindTests(TestCase):
    """A hand-keyed entry is not a bill.

    `kind` is absent from the manual-journal serializer's fields, so every entry
    it wrote took the model default, PURCHASE. Every other member of that enum
    names the document an entry was posted from and a hand-keyed entry has no
    document -- so once the register's Type column started reading `journal.kind`,
    every manual entry in the system would have rendered as "Bill".
    """

    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="D", email="journal-kind@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.account = make_account(
            self.company, "Bank", ChartOfAccountKindChoices.ASSETS
        )

    def test_a_hand_keyed_entry_is_labelled_a_journal_entry(self):
        serializer = PrivateWeJournalEntryListSerializer(
            context={"request": FakeRequest(self.user)}
        )
        entry = serializer.create(
            {
                "company": self.company,
                "journal_items": [
                    {
                        "account": self.account,
                        "kind": JournalEntryConnectorKindChoices.DEBIT,
                        "debit": Decimal("10"),
                        "credit": Decimal("0"),
                    }
                ],
            }
        )
        self.assertEqual(entry.kind, JournalEntryKindChoices.JOURNAL_ENTRY)
        self.assertNotEqual(entry.kind, JournalEntryKindChoices.PURCHASE)

    def test_the_enum_carries_a_value_for_it(self):
        """There was none -- which is why the default stood in for one."""
        self.assertIn(
            "JOURNAL_ENTRY", JournalEntryKindChoices.values
        )


class ManualJournalRelabelMigrationTests(TestCase):
    """The data migration's predicate, checked against the real model.

    `0042_relabel_manual_journal_entries` rewrites `kind` on production rows, so
    its selection has to be exact. It claims an entry holding none of
    JournalEntry's document FKs was keyed by hand -- which is only true if the
    FK list it checks is the whole list.
    """

    @staticmethod
    def migration():
        import importlib

        return importlib.import_module(
            "journalio.migrations.0042_relabel_manual_journal_entries"
        )

    def test_the_fk_list_is_every_document_link_on_the_model(self):
        """Drift guard: a new document FK must be added here too.

        Miss one and an entry posted from that document, holding only that FK,
        looks unlinked and would be relabelled a hand-keyed entry.
        """
        on_model = {
            field.name
            for field in JournalEntry._meta.get_fields()
            if field.many_to_one and field.name != "company"
        }
        self.assertEqual(
            sorted(self.migration().DOCUMENT_FKS),
            sorted(on_model),
            "DOCUMENT_FKS has drifted from JournalEntry's foreign keys",
        )

    def test_it_selects_a_hand_keyed_entry(self):
        company = Company.objects.create(name="M", kind="ECOMMERCE")
        handkeyed = JournalEntry.objects.create(
            company=company,
            kind=JournalEntryKindChoices.PURCHASE,
            status=JournalEntryStatusChoices.PUBLISHED,
        )
        selected = self.migration()._orphans(JournalEntry, "PURCHASE")
        self.assertIn(handkeyed.pk, [entry.pk for entry in selected])

    def test_it_leaves_an_entry_posted_from_a_document_alone(self):
        from purchaseio.models import Purchase
        from supplierio.models import Supplier

        company = Company.objects.create(name="M", kind="ECOMMERCE")
        real = JournalEntry.objects.create(
            company=company,
            kind=JournalEntryKindChoices.PURCHASE,
            status=JournalEntryStatusChoices.PUBLISHED,
            purchase=Purchase.objects.create(
                company=company,
                supplier=Supplier.objects.create(
                    company=company, first_name="Acme", display_name="Acme Ltd"
                ),
            ),
        )
        selected = self.migration()._orphans(JournalEntry, "PURCHASE")
        self.assertNotIn(real.pk, [entry.pk for entry in selected])
