"""Phase 4: the constraints that make a reconciliation record interpretable.

`BankReconciliation` had no `Meta` at all. Every rule about what a row may say
lived in one serializer, so anything reaching the table another way -- a shell,
the admin, an importer, a future endpoint -- could write a row that no reader
could interpret:

- two sessions on one account and one statement date, each ticking a different
  half of the same activity and each closing at a difference of zero;
- `is_closed=True` with `reconciled_on` NULL, indistinguishable from a session
  somebody closed by hand;
- a forced close with no reason and no recorded amount, indistinguishable from
  a clean one -- which is the entire point of recording it;
- a row with no account or no company at all, which `__str__` then crashed on.

Each test drives the DATABASE, not the serializer. A constraint that only the
serializer honours is not a constraint.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import JournalEntryKindChoices, JournalEntryStatusChoices
from journalio.models import JournalEntry

from transactionio.choices import BankReconciliationStatusChoices

from transactionio.models import BankReconciliation


class SessionIntegrityBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Integrity Co")
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="Operating", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )
        cls.other_bank = ChartOfAccount.objects.create(
            company=cls.company, title="Second", code="1001",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )

    def session(self, **extra):
        fields = dict(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("0"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 8, 1),
        )
        fields.update(extra)
        return BankReconciliation.objects.create(**fields)

    def assert_refused(self, **extra):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.session(**extra)


class OneSessionPerPeriodTests(SessionIntegrityBase):
    def test_two_sessions_on_one_account_and_date_are_refused(self):
        self.session()
        self.assert_refused()

    def test_a_different_statement_date_is_allowed(self):
        self.session()
        self.session(statement_ending_date=date(2026, 9, 1))  # must not raise

    def test_a_different_account_on_the_same_date_is_allowed(self):
        self.session()
        self.session(bank_account=self.other_bank)  # must not raise

    def test_another_company_on_the_same_date_is_allowed(self):
        """The constraint is per tenant, not global."""
        other = Company.objects.create(name="Someone Else")
        other_account = ChartOfAccount.objects.create(
            company=other, title="Their Ops", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )
        self.session()
        self.session(company=other, bank_account=other_account)  # must not raise


class ClosedPairingTests(SessionIntegrityBase):
    def test_closed_without_a_date_is_refused(self):
        self.assert_refused(
            status=BankReconciliationStatusChoices.CLOSED, reconciled_on=None
        )

    def test_open_with_a_date_is_refused(self):
        self.assert_refused(
            status=BankReconciliationStatusChoices.OPEN,
            reconciled_on=date(2026, 8, 2),
        )

    def test_the_two_legitimate_shapes_are_allowed(self):
        self.session(
            status=BankReconciliationStatusChoices.OPEN, reconciled_on=None
        )
        self.session(
            statement_ending_date=date(2026, 9, 1),
            status=BankReconciliationStatusChoices.CLOSED,
            reconciled_on=date(2026, 9, 2),
        )


class ForcedPairingTests(SessionIntegrityBase):
    def test_forced_without_a_reason_is_refused(self):
        self.assert_refused(
            status=BankReconciliationStatusChoices.CLOSED,
            reconciled_on=date(2026, 8, 2),
            is_forced=True, forced_reason=None, forced_difference=Decimal("40"),
        )

    def test_forced_without_an_amount_is_refused(self):
        self.assert_refused(
            status=BankReconciliationStatusChoices.CLOSED,
            reconciled_on=date(2026, 8, 2),
            is_forced=True, forced_reason="fee", forced_difference=None,
        )

    def test_a_complete_forced_close_is_allowed(self):
        self.session(
            status=BankReconciliationStatusChoices.CLOSED,
            reconciled_on=date(2026, 8, 2),
            is_forced=True, forced_reason="fee", forced_difference=Decimal("40"),
        )


class RequiredFieldTests(SessionIntegrityBase):
    def test_a_session_without_an_account_is_refused(self):
        self.assert_refused(bank_account=None)

    def test_a_session_without_a_company_is_refused(self):
        self.assert_refused(company=None)

    def test_str_does_not_crash_without_an_account(self):
        """It dereferenced `bank_account.title` unguarded."""
        recon = self.session()
        recon.bank_account = None
        recon.bank_account_id = None
        self.assertIn("no account", str(recon))


class OneDiscrepancyEntryTests(SessionIntegrityBase):
    """BR-14. Enforced by the database, not by one helper's `get_or_create`."""

    def _entry(self, recon):
        return JournalEntry.objects.create(
            company=self.company, date=date(2026, 8, 1), amount=Decimal("40"),
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.BANK_RECONCILIATION,
            bank_reconciliation=recon,
        )

    def test_a_second_adjustment_for_one_session_is_refused(self):
        recon = self.session()
        self._entry(recon)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._entry(recon)

    def test_ordinary_entries_are_unaffected(self):
        """The index is partial -- NULL is the normal case and must stay free."""
        for _ in range(3):
            JournalEntry.objects.create(
                company=self.company, date=date(2026, 8, 1), amount=Decimal("1"),
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.SALE,
            )
        self.assertEqual(
            JournalEntry.objects.filter(bank_reconciliation__isnull=True).count(), 3
        )


class UnsavedSessionTests(SessionIntegrityBase):
    def test_candidates_for_an_unsaved_session_do_not_raise(self):
        """Django refuses an unsaved instance in a related filter.

        A preview against a session not yet written died with a bare ValueError
        rather than returning the obvious answer, which is "nothing is cleared".
        """
        from transactionio.django_rest.helpers.reconciliation import (
            candidate_connectors,
        )

        unsaved = BankReconciliation(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("0"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 8, 1),
        )
        self.assertEqual(candidate_connectors(unsaved, cleared=True).count(), 0)
        self.assertEqual(candidate_connectors(unsaved).count(), 0)


class RlsCoversEveryTenantTableTests(TestCase):
    """BR-27. Structural, because RLS is PostgreSQL-only and tests run on SQLite.

    Asserted against the app registry rather than against a hardcoded list, so
    a model added to `transactionio` later fails this until somebody decides
    whether it is tenant data. A test that merely checked five known names would
    stay green through exactly the omission that left these tables uncovered in
    the first place -- `0023` and `0025` each took the tables that were obvious
    at the time.
    """

    MIGRATION = "companyio/migrations/0026_enable_rls_transactions.py"

    def _source(self):
        import pathlib

        return pathlib.Path(self.MIGRATION).read_text()

    def test_every_model_carrying_company_is_covered(self):
        from django.apps import apps

        source = self._source()
        uncovered = [
            model._meta.db_table
            for model in apps.get_app_config("transactionio").get_models()
            if "company" in {f.name for f in model._meta.get_fields()}
            and f'"{model._meta.db_table}"' not in source
        ]
        self.assertEqual(
            uncovered, [],
            f"these transactionio tables carry company_id and have no RLS "
            f"policy: {uncovered}",
        )

    def test_models_without_a_tenant_key_are_not_claimed(self):
        """The list is exact, not a superset.

        `common/db/rls.py` only emits SQL for the `company_id` convention, so
        naming a table that has no such column would produce a policy that
        cannot be satisfied.
        """
        from django.apps import apps

        source = self._source()
        wrongly_claimed = [
            model._meta.db_table
            for model in apps.get_app_config("transactionio").get_models()
            if "company" not in {f.name for f in model._meta.get_fields()}
            and f'"{model._meta.db_table}"' in source
        ]
        self.assertEqual(
            wrongly_claimed, [],
            f"these tables have no company_id but are named in the RLS "
            f"migration: {wrongly_claimed}",
        )

    def test_the_policy_builder_is_the_shared_one(self):
        """One definition of tenant isolation in the schema, not several."""
        from common.db.rls import enable_rls_sql

        sql = enable_rls_sql("transactionio_bankreconciliation")

        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("FORCE ROW LEVEL SECURITY", sql)
        self.assertIn("app.company_id", sql)
        self.assertIn("WITH CHECK", sql)

    def test_the_migration_is_reversible(self):
        source = self._source()
        self.assertIn("enable_rls_for_tables", source)
        self.assertIn("disable_rls_for_tables", source)


class MalformedIdentifierTests(TestCase):
    """BR-22, and it is already closed -- but by DRF, not by our code.

    The gap analysis called this a 500: `.get(uid=...)` catches only
    `DoesNotExist`, and a malformed value never reaches the lookup as a uuid at
    all, so it raises `django.core.exceptions.ValidationError` before
    `DoesNotExist` can be considered. That reasoning is right as far as it goes.

    What it misses is that the lookup sits inside `validate()`, and DRF's
    `run_validation` catches **both** its own `ValidationError` and Django's,
    converting either into a 400:

        except (ValidationError, DjangoValidationError) as exc:
            raise ValidationError(detail=as_serializer_error(exc))

    Verified: the raw lookup raises `django.core.exceptions.ValidationError`,
    and the serializer surfaces
    `{'non_field_errors': ['"not-a-uuid" is not a valid UUID.']}`.

    So these are guards on a property that holds by accident of placement, which
    is exactly the kind worth pinning. **Move either lookup out of `validate()`
    -- into `save()`, a view, or a helper called after validation -- and it
    becomes the 500 the gap analysis described.** `save()` already re-reads the
    session, and it does so by `pk` off an object validation already resolved,
    which is why that is safe.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import User
        from companyio.models import CompanyUser

        cls.company = Company.objects.create(name="Malformed Co")
        cls.user = User.objects.create_user(
            name="M", email="malformed@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="Operating", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )

    class _Req:
        def __init__(self, user):
            self.user = user

    def _serializer(self, **data):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        payload = {"reconciliation_id": "not-a-uuid", "journal_entry_ids": ["x"]}
        payload.update(data)
        return PrivateWeTransactionMatchSerializer(
            data=payload, context={"request": self._Req(self.user)}
        )

    def test_a_malformed_reconciliation_id_is_a_validation_error(self):
        from rest_framework.serializers import ValidationError

        with self.assertRaises(ValidationError):
            self._serializer().is_valid(raise_exception=True)

    def test_a_malformed_journal_entry_id_is_a_validation_error(self):
        from rest_framework.serializers import ValidationError

        from transactionio.models import BankReconciliation

        recon = BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("0"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 8, 1),
        )
        with self.assertRaises(ValidationError):
            self._serializer(
                reconciliation_id=str(recon.uid),
                journal_entry_ids=["also-not-a-uuid"],
            ).is_valid(raise_exception=True)


class UndoneSessionConstraintTests(SessionIntegrityBase):
    """Phase 5's additions to the same model. The status enum's constraints.

    An undone session keeps its row -- it is the only durable audit surface,
    this model being unregistered with auditlog -- but it must not hold its
    statement period hostage, or undo would make a period permanently
    unreconcilable, which is the opposite of its purpose.
    """

    UNDONE = BankReconciliationStatusChoices.UNDONE
    CLOSED = BankReconciliationStatusChoices.CLOSED
    OPEN = BankReconciliationStatusChoices.OPEN

    def undone(self, **extra):
        fields = dict(
            status=self.UNDONE,
            reconciled_on=date(2026, 8, 2),
            undone_on=date(2026, 8, 3),
            undo_reason="statement was wrong",
        )
        fields.update(extra)
        return self.session(**fields)

    def test_an_undone_session_frees_its_period(self):
        """The whole point: undo must let the period be reconciled again."""
        self.undone()
        self.session()  # a fresh live session, same account, same date

    def test_two_undone_sessions_may_share_a_period(self):
        """Reconciled, undone, reconciled again, undone again."""
        self.undone()
        self.undone()

    def test_two_LIVE_sessions_still_may_not_share_a_period(self):
        self.session()
        self.assert_refused()

    def test_an_undone_session_and_a_closed_one_may_share_a_period(self):
        self.undone()
        self.session(status=self.CLOSED, reconciled_on=date(2026, 8, 9))

    def test_undone_without_a_reason_is_refused(self):
        self.assert_refused(
            status=self.UNDONE, reconciled_on=date(2026, 8, 2),
            undone_on=date(2026, 8, 3), undo_reason=None,
        )

    def test_undone_without_a_date_is_refused(self):
        self.assert_refused(
            status=self.UNDONE, reconciled_on=date(2026, 8, 2),
            undone_on=None, undo_reason="statement was wrong",
        )

    def test_an_undone_session_keeps_the_close_it_is_undoing(self):
        """`reconciled_on` survives, because it records the act being undone."""
        recon = self.undone()
        recon.refresh_from_db()
        self.assertIsNotNone(
            recon.reconciled_on,
            "the close date was erased, so the record no longer says what was "
            "undone or when",
        )

    def test_an_undone_session_may_not_pretend_it_never_closed(self):
        self.assert_refused(
            status=self.UNDONE, reconciled_on=None,
            undone_on=date(2026, 8, 3), undo_reason="x",
        )
