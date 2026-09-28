"""What the Chart of Account register lists, and what its Balance column means.

`GET /we/chart-of-accounts/{uid}/sessions` is the Bank Register's row source. It
was never written as a register -- it is a raw dump of journal legs that a
register screen was pointed at -- and four things about it were wrong at once.

**The balance was destroyed by filtering.** It came from `annotate_running_balance`,
a window function applied in `get_queryset`. DRF runs `filter_queryset` *after*
`get_queryset`, and SQL evaluates WHERE before window functions, so every filter
landed inside the same SELECT as the OVER clause and the cumulative sum
restarted at the first surviving row. Filter a $50,000 account to August and its
first row read as though the account had opened the month at zero. Silent, and
plausible enough to be believed.

**The date filter filtered a different column from the one it ordered by.**
`DateFromToRangeFilter` filters `created_at`, the keystroke; the register orders
by `date`, the transaction date. A document dated in March and entered in June
answered to June.

**Drafts and soft-deleted entries were on the books.** No `journal__status`
clause, while Reconcile's `candidate_connectors` requires PUBLISHED. The two
screens disagreed about which lines exist, so no reconciliation could tie out.

**An unknown account was indistinguishable from an empty one.** The account was
a filter clause, not a lookup, so a foreign uid returned `200 {"count": 0}`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.http import Http404

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.views.chart_of_accounts import (
    PrivateWeChartOfAccountSessionList,
)


class FakeRequest:
    def __init__(self, user, **params):
        self.user = user
        self.query_params = params


def register(user, account_uid, **params):
    """Drive the view the way DRF does: get_queryset, then filter_queryset."""
    view = PrivateWeChartOfAccountSessionList()
    view.request = FakeRequest(user, **params)
    view.kwargs = {"uid": account_uid}
    view.format_kwarg = None
    return list(view.filter_queryset(view.get_queryset()))


class RegisterTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="R", email="register@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.account = ChartOfAccount.objects.create(
            company=self.company, title="City Bank", code="BANK",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.published = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
            status=JournalEntryStatusChoices.PUBLISHED,
        )

    def line(self, amount, day, entry=None, side=None):
        side = side or JournalEntryConnectorKindChoices.DEBIT
        debit = Decimal(amount) if side == JournalEntryConnectorKindChoices.DEBIT else Decimal("0")
        credit = Decimal(amount) if side == JournalEntryConnectorKindChoices.CREDIT else Decimal("0")
        return JournalEntryConnector.objects.create(
            journal=entry or self.published, account=self.account, date=day,
            debit=debit, credit=credit, kind=side,
            last_balance=Decimal("123456"),  # a deliberately wrong snapshot
        )

    def balances(self, rows):
        return [Decimal(str(r.running_balance)) for r in rows]


class BalanceSurvivesFilteringTests(RegisterTestCase):
    """The Balance column is the account's balance, not the page's."""

    def setUp(self):
        super().setUp()
        self.line("100", "2026-03-01")
        self.line("50", "2026-03-02")
        self.line("25", "2026-03-03")

    def test_the_unfiltered_register_runs_100_150_175(self):
        rows = register(self.user, self.account.uid)
        self.assertEqual(
            self.balances(rows),
            [Decimal("175"), Decimal("150"), Decimal("100")],  # newest first
        )

    def test_a_date_filter_does_not_restart_the_balance(self):
        """The bug: these used to read 50 and 75, as if March began at zero."""
        rows = register(self.user, self.account.uid, date_after="2026-03-02")
        self.assertEqual([r.date for r in rows],
                         [date(2026, 3, 3), date(2026, 3, 2)])
        self.assertEqual(self.balances(rows), [Decimal("175"), Decimal("150")])

    def test_a_field_filter_does_not_restart_the_balance(self):
        """Same hazard through DjangoFilterBackend rather than the date range."""
        rows = register(self.user, self.account.uid,
                        kind=JournalEntryConnectorKindChoices.DEBIT)
        self.assertEqual(self.balances(rows),
                         [Decimal("175"), Decimal("150"), Decimal("100")])

    def test_the_stored_snapshot_is_not_what_is_served(self):
        rows = register(self.user, self.account.uid)
        self.assertNotIn(Decimal("123456"), self.balances(rows))


class LedgerDateFilterTests(RegisterTestCase):
    """Filtered on the transaction date, the column the register orders by."""

    def setUp(self):
        super().setUp()
        self.backdated = self.line("100", "2026-03-15")
        # Entered in June, dated in March -- the case that answered to June.
        JournalEntryConnector.objects.filter(pk=self.backdated.pk).update(
            created_at="2026-06-20T10:00:00Z"
        )

    def test_a_backdated_line_answers_to_its_document_date(self):
        rows = register(self.user, self.account.uid,
                        date_after="2026-03-01", date_before="2026-03-31")
        self.assertEqual([r.pk for r in rows], [self.backdated.pk])

    def test_it_does_not_answer_to_the_month_it_was_keyed_in(self):
        rows = register(self.user, self.account.uid,
                        date_after="2026-06-01", date_before="2026-06-30")
        self.assertEqual(rows, [])

    def test_the_closing_day_is_included(self):
        """`created_at__lte=<midnight>` used to drop the whole final day."""
        rows = register(self.user, self.account.uid,
                        date_after="2026-03-15", date_before="2026-03-15")
        self.assertEqual([r.pk for r in rows], [self.backdated.pk])

    def test_the_legacy_created_at_spelling_still_filters(self):
        """Clients already send these. A filter that silently stops is worse."""
        rows = register(self.user, self.account.uid,
                        created_at_after="2026-03-01",
                        created_at_before="2026-03-31")
        self.assertEqual([r.pk for r in rows], [self.backdated.pk])

    def test_a_malformed_date_is_refused(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            register(self.user, self.account.uid, date_after="15-03-2026")


class OnlyPostedLinesTests(RegisterTestCase):
    """A draft is not on the books, and neither is a deleted entry."""

    def setUp(self):
        super().setUp()
        self.posted = self.line("100", "2026-03-01")
        self.draft_entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
            status=JournalEntryStatusChoices.DRAFT,
        )
        self.removed_entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
            status=JournalEntryStatusChoices.REMOVED,
        )
        self.drafted = self.line("500", "2026-03-02", entry=self.draft_entry)
        self.deleted = self.line("900", "2026-03-03", entry=self.removed_entry)

    def test_only_published_lines_are_listed(self):
        rows = register(self.user, self.account.uid)
        self.assertEqual([r.pk for r in rows], [self.posted.pk])

    def test_unposted_lines_do_not_move_the_balance(self):
        """They were counted into the running total as well as listed."""
        rows = register(self.user, self.account.uid)
        self.assertEqual(self.balances(rows), [Decimal("100")])


class RegisterOrderingTests(RegisterTestCase):
    def test_the_newest_line_is_first(self):
        """It opened on the oldest ten rows; today needed ?page=400."""
        self.line("1", "2026-01-01")
        self.line("2", "2026-06-01")
        self.line("3", "2026-03-01")
        rows = register(self.user, self.account.uid)
        self.assertEqual(
            [r.date for r in rows],
            [date(2026, 6, 1), date(2026, 3, 1), date(2026, 1, 1)],
        )


class AccountResolutionTests(RegisterTestCase):
    """An unknown account is a 404, not an empty register."""

    def test_another_companys_account_is_not_found(self):
        theirs = Company.objects.create(name="Theirs", kind="ECOMMERCE")
        their_account = ChartOfAccount.objects.create(
            company=theirs, title="Their Bank", code="TB",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        with self.assertRaises(Http404):
            register(self.user, their_account.uid)

    def test_an_unknown_uid_is_not_found(self):
        import uuid

        with self.assertRaises(Http404):
            register(self.user, uuid.uuid4())

    def test_a_draft_account_still_has_a_readable_register(self):
        """The API create path never sets a status, so this was every
        API-created account: a permanently empty register."""
        drafted = ChartOfAccount.objects.create(
            company=self.company, title="New", code="NEW",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.DRAFT,
        )
        JournalEntryConnector.objects.create(
            journal=self.published, account=drafted, date="2026-03-01",
            debit=Decimal("10"), kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        self.assertEqual(len(register(self.user, drafted.uid)), 1)


class CreditNormalRegisterTests(RegisterTestCase):
    """A credit card's balance grows on the credit side."""

    def test_a_liability_register_signs_by_the_accounts_own_direction(self):
        card = ChartOfAccount.objects.create(
            company=self.company, title="Card", code="CARD",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        for amount, day, side in (
            ("100", "2026-03-01", JournalEntryConnectorKindChoices.CREDIT),
            ("40", "2026-03-02", JournalEntryConnectorKindChoices.DEBIT),
        ):
            JournalEntryConnector.objects.create(
                journal=self.published, account=card, date=day, kind=side,
                debit=Decimal(amount) if side == JournalEntryConnectorKindChoices.DEBIT else Decimal("0"),
                credit=Decimal(amount) if side == JournalEntryConnectorKindChoices.CREDIT else Decimal("0"),
            )
        rows = register(self.user, card.uid)
        # A charge raises the card; a payment brings it down.
        self.assertEqual(self.balances(rows), [Decimal("60"), Decimal("100")])


def serialize(user, account_uid, **params):
    """Serialize the register the way the view does, context included."""
    view = PrivateWeChartOfAccountSessionList()
    view.request = FakeRequest(user, **params)
    view.kwargs = {"uid": account_uid}
    view.format_kwarg = None
    rows = view.filter_queryset(view.get_queryset())
    return view.get_serializer(rows, many=True).data


class RegisterRowFieldsTests(RegisterTestCase):
    """The fields the register screen actually renders."""

    def setUp(self):
        super().setUp()
        self.published.entry_number = "#JE-000123"
        self.published.description = "entry level memo"
        self.published.save()
        self.row = self.line("100", "2026-03-01")

    def only(self, **params):
        rows = serialize(self.user, self.account.uid, **params)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_the_transaction_type_is_the_journals_kind_not_the_audit_action(self):
        row = self.only()
        self.assertEqual(row["model_kind"], JournalEntryKindChoices.CHART_OF_ACCOUNT)
        self.assertEqual(row["request_kind"], "CREATED")   # the old Type column
        self.assertEqual(row["kind"], "DEBIT")             # the posting side

    def test_the_document_uid_is_the_journals_not_the_legs(self):
        """`/reconcile/complete` resolves journal__uid; a leg uid 400s there."""
        row = self.only()
        self.assertEqual(row["document_uid"], str(self.published.uid))
        self.assertNotEqual(row["document_uid"], row["uid"])
        self.assertEqual(row["uid"], str(self.row.uid))

    def test_the_entry_number_is_flat(self):
        self.assertEqual(self.only()["entry_number"], "#JE-000123")

    def test_the_leg_carries_its_own_date(self):
        self.assertEqual(self.only()["date"], "2026-03-01")

    def test_the_memo_falls_back_to_the_entry(self):
        """Sale, purchase, pay-bill and deposit legs carry no memo of their own."""
        self.assertEqual(self.only()["description"], "entry level memo")

    def test_a_leg_memo_wins_over_the_entrys(self):
        self.row.description = "leg level memo"
        self.row.save()
        self.assertEqual(self.only()["description"], "leg level memo")

    def test_an_ordinary_line_is_not_an_adjustment(self):
        self.assertIs(self.only()["is_adjustment"], False)

    def test_an_amendment_leg_is_flagged(self):
        self.row.request_kind = "UPDATED"
        self.row.save()
        self.assertIs(self.only()["is_adjustment"], True)


class DepositAndPaymentTests(RegisterTestCase):
    """Money in and money out, in the account's own direction."""

    def test_on_a_bank_a_debit_is_a_deposit(self):
        self.line("100", "2026-03-01", side=JournalEntryConnectorKindChoices.DEBIT)
        row = serialize(self.user, self.account.uid)[0]
        self.assertEqual(Decimal(row["deposit"]), Decimal("100"))
        self.assertEqual(Decimal(row["payment"]), Decimal("0"))

    def test_on_a_credit_card_a_debit_is_a_payment(self):
        """The labels invert, and the row carries no account to infer it from."""
        card = ChartOfAccount.objects.create(
            company=self.company, title="Card", code="CARD",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        JournalEntryConnector.objects.create(
            journal=self.published, account=card, date="2026-03-01",
            debit=Decimal("40"), credit=Decimal("0"),
            kind=JournalEntryConnectorKindChoices.DEBIT,
        )
        row = serialize(self.user, card.uid)[0]
        self.assertEqual(Decimal(row["payment"]), Decimal("40"))
        self.assertEqual(Decimal(row["deposit"]), Decimal("0"))


class PayeeTests(RegisterTestCase):
    """One field, resolved server-side, in a defined precedence."""

    def row_with(self, **party):
        JournalEntryConnector.objects.create(
            journal=self.published, account=self.account, date="2026-03-01",
            debit=Decimal("10"), kind=JournalEntryConnectorKindChoices.DEBIT,
            **party,
        )
        return serialize(self.user, self.account.uid)[0]["payee"]

    def test_a_supplier_payee(self):
        from supplierio.models import Supplier

        supplier = Supplier.objects.create(
            company=self.company, first_name="Acme", display_name="Acme Ltd"
        )
        self.assertEqual(self.row_with(supplier=supplier)["name"], "Acme Ltd")

    def test_a_customer_payee_uses_its_name_parts(self):
        from customerio.models import Customer

        customer = Customer.objects.create(
            company=self.company, first_name="Nusrat", last_name="Chowdhury"
        )
        payee = self.row_with(customer=customer)
        self.assertEqual(payee["name"], "Nusrat Chowdhury")
        self.assertEqual(payee["kind"], "CUSTOMER")

    def test_a_payroll_leg_carries_the_employee(self):
        """Payroll sets `employee` and nothing else -- these rendered blank."""
        from employeeio.models import Employee

        employee = Employee.objects.create(
            company=self.company, first_name="Abid", last_name="Ragib",
            user=User.objects.create_user(
                name="Abid", email="abid@example.com", password="pass1234!"
            ),
        )
        payee = self.row_with(employee=employee)
        self.assertEqual(payee["name"], "Abid Ragib")
        self.assertEqual(payee["kind"], "EMPLOYEE")

    def test_no_party_is_null_not_a_blank_object(self):
        self.assertIsNone(self.row_with())


class RegisterQueryCountTests(RegisterTestCase):
    """A register page must not cost a query per row.

    The serializer nests journal, customer and supplier and reads employee. With
    none of them fetched that is four queries a row -- plus a fifth for
    `PrivateSupplierSlimSerializer.total_credit`, a `Sum` over the supplier's
    credit notes, which is why this endpoint does not use that serializer.
    Measured before the fix on a ten-row page: thirteen queries, ten of them
    that aggregate.

    The assertion is that the count does not move with the row count, not that
    it equals some number. An absolute figure is not stable -- the same page
    measured alone and inside the full suite differs by two, depending on what
    else has warmed up -- and it is not the property worth guarding. Flatness is.
    """

    CEILING = 10

    def build(self, rows):
        from customerio.models import Customer
        from supplierio.models import Supplier

        for index in range(rows):
            entry = JournalEntry.objects.create(
                company=self.company,
                kind=JournalEntryKindChoices.PURCHASE,
                status=JournalEntryStatusChoices.PUBLISHED,
            )
            JournalEntryConnector.objects.create(
                journal=entry, account=self.account,
                date=f"2026-03-{index + 1:02d}", debit=Decimal("10"),
                kind=JournalEntryConnectorKindChoices.DEBIT,
                supplier=Supplier.objects.create(
                    company=self.company, first_name=f"S{index}",
                    display_name=f"S{index} Ltd",
                ),
                customer=Customer.objects.create(
                    company=self.company, first_name=f"C{index}", last_name="X"
                ),
            )

    def measure(self, rows):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        JournalEntryConnector.objects.all().delete()
        self.build(rows)
        with CaptureQueriesContext(connection) as captured:
            serialized = serialize(self.user, self.account.uid)
        self.assertEqual(len(serialized), rows)
        return len(captured.captured_queries)

    def test_the_cost_does_not_grow_with_the_page(self):
        """Ten times the rows, same number of queries."""
        small = self.measure(3)
        large = self.measure(30)
        self.assertEqual(
            small, large,
            f"{small} queries for 3 rows but {large} for 30 -- per-row work "
            f"has come back into the register serializer",
        )
        self.assertLessEqual(large, self.CEILING)


class CategoryTests(RegisterTestCase):
    """The contra account, and when it is a split."""

    def contra(self, title, kind=ChartOfAccountKindChoices.INCOMES):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def leg(self, account, side, amount, entry=None, **extra):
        return JournalEntryConnector.objects.create(
            journal=entry or self.published, account=account, date="2026-03-01",
            kind=side,
            debit=Decimal(amount) if side == JournalEntryConnectorKindChoices.DEBIT else Decimal("0"),
            credit=Decimal(amount) if side == JournalEntryConnectorKindChoices.CREDIT else Decimal("0"),
            **extra,
        )

    def category_of_bank_row(self):
        rows = serialize(self.user, self.account.uid)
        return rows[0]["category"]

    def test_a_two_leg_entry_names_the_other_account(self):
        self.leg(self.account, JournalEntryConnectorKindChoices.DEBIT, "100")
        self.leg(self.contra("Sales Income"), JournalEntryConnectorKindChoices.CREDIT, "100")
        self.assertEqual(self.category_of_bank_row(), "Sales Income")

    def test_two_distinct_contras_are_a_split(self):
        self.leg(self.account, JournalEntryConnectorKindChoices.DEBIT, "100")
        self.leg(self.contra("Sales Income"), JournalEntryConnectorKindChoices.CREDIT, "60")
        self.leg(self.contra("Shipping Income"), JournalEntryConnectorKindChoices.CREDIT, "40")
        self.assertEqual(self.category_of_bank_row(), "-Split-")

    def test_the_same_contra_twice_is_not_a_split(self):
        """A three-line invoice writes three legs to one income account.

        Counting legs rather than distinct accounts would call that a split.
        """
        self.leg(self.account, JournalEntryConnectorKindChoices.DEBIT, "100")
        income = self.contra("Sales Income")
        for amount in ("40", "35", "25"):
            self.leg(income, JournalEntryConnectorKindChoices.CREDIT, amount)
        self.assertEqual(self.category_of_bank_row(), "Sales Income")

    def test_a_one_legged_entry_has_no_category(self):
        """Reachable: a sale whose cost account is missing posts neither leg
        of a pair, and `assert_entry_balances` logs rather than raises."""
        self.leg(self.account, JournalEntryConnectorKindChoices.DEBIT, "100")
        self.assertIsNone(self.category_of_bank_row())

    def test_legs_on_the_same_account_both_sides_leave_no_contra(self):
        self.leg(self.account, JournalEntryConnectorKindChoices.DEBIT, "100")
        self.leg(self.account, JournalEntryConnectorKindChoices.CREDIT, "100")
        self.assertIsNone(self.category_of_bank_row())


class ReconciliationStatusTests(RegisterTestCase):
    """U, C and R, decided by the session's status and not the FK alone."""

    def session(self, status):
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        # `reconciliation_closed_iff_reconciled_on` requires the date on a
        # CLOSED or UNDONE session and forbids it on an OPEN one.
        settled = status in (
            BankReconciliationStatusChoices.CLOSED,
            BankReconciliationStatusChoices.UNDONE,
        )
        undone = status == BankReconciliationStatusChoices.UNDONE
        return BankReconciliation.objects.create(
            company=self.company, bank_account=self.account, status=status,
            statement_ending_balance=Decimal("0"),
            beginning_balance=Decimal("0"),
            statement_ending_date="2026-03-31",
            reconciled_on="2026-03-31" if settled else None,
            # `reconciliation_undone_implies_reason_and_date` -- an undo has to
            # say when and why.
            undone_on="2026-04-01" if undone else None,
            undo_reason="bank restated the statement" if undone else "",
        )

    def status_of(self, **extra):
        JournalEntryConnector.objects.create(
            journal=self.published, account=self.account, date="2026-03-01",
            debit=Decimal("10"), kind=JournalEntryConnectorKindChoices.DEBIT,
            **extra,
        )
        return serialize(self.user, self.account.uid)[0]["reconciliation_status"]

    def test_an_untouched_line_is_unmarked(self):
        self.assertEqual(self.status_of(), "U")

    def test_a_line_on_a_closed_session_is_reconciled(self):
        from transactionio.choices import BankReconciliationStatusChoices

        session = self.session(BankReconciliationStatusChoices.CLOSED)
        self.assertEqual(
            self.status_of(reconciliation=session, cleared_on="2026-03-31"), "R"
        )

    def test_a_released_line_keeps_its_tick_and_reads_cleared(self):
        """Undo sets `reconciliation=None` and deliberately keeps `cleared_on`."""
        self.assertEqual(self.status_of(cleared_on="2026-03-31"), "C")

    def test_a_line_stranded_on_an_undone_session_is_not_reconciled(self):
        """Undo releases through `candidate_connectors`, which also filters on
        journal status and the statement date -- so a line can keep the FK.
        Null-checking it would call those reconciled forever."""
        from transactionio.choices import BankReconciliationStatusChoices

        session = self.session(BankReconciliationStatusChoices.UNDONE)
        self.assertEqual(
            self.status_of(reconciliation=session, cleared_on="2026-03-31"), "C"
        )

    def test_the_status_filter_spans_the_account_not_the_page(self):
        from transactionio.choices import BankReconciliationStatusChoices

        session = self.session(BankReconciliationStatusChoices.CLOSED)
        for extra in ({}, {"cleared_on": "2026-03-31"},
                      {"reconciliation": session, "cleared_on": "2026-03-31"}):
            JournalEntryConnector.objects.create(
                journal=self.published, account=self.account, date="2026-03-01",
                debit=Decimal("10"), kind=JournalEntryConnectorKindChoices.DEBIT,
                **extra,
            )
        for wanted, count in (("U", 1), ("C", 1), ("R", 1), ("U,C", 2)):
            with self.subTest(status=wanted):
                rows = register(self.user, self.account.uid,
                                reconciliation_status=wanted)
                self.assertEqual(len(rows), count)

    def test_an_unknown_status_is_refused(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            register(self.user, self.account.uid, reconciliation_status="X")


class RegisterPermissionTests(TestCase):
    """The register is guarded as its account is, not as an internal model.

    With no explicit `required_permissions`, the resolver infers the codename
    from the serializer's model and asked for `view_journalentryconnector` --
    granted by no role, seed or catalogue entry in the repo. The resolver fails
    closed, so the endpoint was a 403 for everyone who is not a superuser or
    `is_admin`: every invited co-worker. It was not even pickable in the role
    builder, which lists permissions by model name.
    """

    def test_it_requires_the_chart_of_account_permission(self):
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
            PrivateWeChartOfAccountSessionList,
        )

        self.assertEqual(
            PrivateWeChartOfAccountSessionList.required_permissions,
            ["view_chartofaccount"],
        )
        # The same permission the account header beside it resolves to.
        self.assertEqual(
            PrivateWeChartOfAccountDetails.serializer_class.Meta.model.__name__,
            "ChartOfAccount",
        )

    def test_the_codename_is_a_real_permission_row(self):
        """A misspelling resolves to nothing and fails closed -- a view that
        looks guarded and is still a 403 for everyone."""
        from django.contrib.auth.models import Permission

        self.assertTrue(
            Permission.objects.filter(codename="view_chartofaccount").exists()
        )

    def test_it_is_gated_on_the_same_feature_as_the_account_it_belongs_to(self):
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountDetails,
            PrivateWeChartOfAccountSessionList,
        )

        self.assertEqual(
            PrivateWeChartOfAccountSessionList.required_feature,
            PrivateWeChartOfAccountDetails.required_feature,
        )
        self.assertEqual(
            PrivateWeChartOfAccountSessionList.required_feature,
            "is_chart_of_account",
        )

    def test_the_feature_key_exists_in_the_catalogue(self):
        from subscriptionio.feature_catalog import FEATURE_CATALOG

        legacy = {
            feature.get("legacy_field")
            for group in FEATURE_CATALOG
            for feature in group.get("features", [])
        }
        self.assertIn("is_chart_of_account", legacy)


class RegisterSearchTests(RegisterTestCase):
    """Search has to match what a person would type into it."""

    def setUp(self):
        super().setUp()
        from supplierio.models import Supplier

        self.published.entry_number = "#JE-048317"
        self.published.save()
        self.row = JournalEntryConnector.objects.create(
            journal=self.published, account=self.account, date="2026-03-01",
            debit=Decimal("100"), kind=JournalEntryConnectorKindChoices.DEBIT,
            description="March office rent",
            supplier=Supplier.objects.create(
                company=self.company, first_name="Kamrul", last_name="Islam",
                display_name="Kamrul Islam",
            ),
        )
        # A second row that must NOT match, so a passing search is not just
        # "everything comes back".
        JournalEntryConnector.objects.create(
            journal=self.published, account=self.account, date="2026-03-02",
            debit=Decimal("5"), kind=JournalEntryConnectorKindChoices.DEBIT,
            description="something else entirely",
        )

    def found(self, term):
        return [r.pk for r in register(self.user, self.account.uid, search=term)]

    def test_it_matches_a_memo(self):
        self.assertEqual(self.found("office rent"), [self.row.pk])

    def test_it_matches_a_payee_across_first_and_last_name(self):
        self.assertEqual(self.found("Kamrul Islam"), [self.row.pk])

    def test_it_matches_an_entry_number(self):
        self.assertEqual(len(self.found("048317")), 2)  # both share the entry

    def test_a_term_matching_nothing_returns_nothing(self):
        self.assertEqual(self.found("zzzznope"), [])


class TransactionTypeFilterTests(RegisterTestCase):
    """The Type column needs a filter, and `?kind=` is not it."""

    def test_journal_kind_filters_the_transaction_type(self):
        other = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.PAY_BILL,
            status=JournalEntryStatusChoices.PUBLISHED,
        )
        self.line("100", "2026-03-01")
        billed = self.line("50", "2026-03-02", entry=other)

        rows = register(self.user, self.account.uid,
                        journal__kind=JournalEntryKindChoices.PAY_BILL)
        self.assertEqual([r.pk for r in rows], [billed.pk])

    def test_kind_is_still_the_posting_side(self):
        """Kept as-is: renaming it would break existing clients."""
        self.line("100", "2026-03-01")
        self.assertEqual(
            len(register(self.user, self.account.uid, kind="DEBIT")), 1
        )


class SeededRoleCanReachTheRegisterTests(TestCase):
    """An invited co-worker holds a role, and the role has to reach the screen.

    Invited users are created without `is_admin` and put in the seeded `user`
    Group. That Group held three permissions -- companyuser view, user view and
    user change -- and nothing for accounting, so every accounting endpoint was
    a 403 for exactly the population `CompanyRole` exists to serve. Owners never
    saw it: self-registration sets `is_admin`, which short-circuits the check.
    """

    @staticmethod
    def user_group_codenames():
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from accounts.django_rest.helpers.group_seeds import (
            USER_GROUP_PERMISSIONS,
            resolve_permissions,
        )

        return set(
            resolve_permissions(
                USER_GROUP_PERMISSIONS, Permission, ContentType
            ).values_list("codename", flat=True)
        )

    def test_the_user_role_can_view_the_chart_of_accounts(self):
        self.assertIn("view_chartofaccount", self.user_group_codenames())

    def test_it_grants_the_permission_the_register_asks_for(self):
        """The two must not drift apart -- either one alone is still a 403."""
        from weapi.django_rest.views.chart_of_accounts import (
            PrivateWeChartOfAccountSessionList,
        )

        required = set(PrivateWeChartOfAccountSessionList.required_permissions)
        self.assertTrue(required <= self.user_group_codenames())

    def test_it_grants_sight_of_the_books_and_not_control_of_them(self):
        """Read only. Writing to the ledger stays with roles an admin grants."""
        granted = self.user_group_codenames()
        for codename in (
            "add_chartofaccount",
            "change_chartofaccount",
            "delete_chartofaccount",
            "add_bankreconciliation",
            "change_bankreconciliation",
            "add_journalentry",
            "change_journalentry",
        ):
            with self.subTest(codename=codename):
                self.assertNotIn(codename, granted)

    def test_the_employee_role_is_untouched(self):
        """Employee Self-Service is a published matrix; accounting is a No row."""
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from accounts.django_rest.helpers.group_seeds import (
            EMPLOYEE_GROUP_PERMISSIONS,
            resolve_permissions,
        )

        codenames = set(
            resolve_permissions(
                EMPLOYEE_GROUP_PERMISSIONS, Permission, ContentType
            ).values_list("codename", flat=True)
        )
        self.assertNotIn("view_chartofaccount", codenames)


class AccountHeaderTests(RegisterTestCase):
    """What the register hero is told, rather than left to infer."""

    def header(self, account):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer,
        )

        return PrivateWeChartOfAccountDetailsSerializer(
            account, context={"request": FakeRequest(self.user)}
        ).data

    def typed(self, title, type_title, kind):
        from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
        from categoryio.models import Category

        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=title[:8], kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
            account_type=Category.objects.create(
                title=type_title, kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                status=CategoryStatusChoices.ACTIVE,
            ),
        )

    def test_a_bank_deposits_and_pays(self):
        bank = self.typed("Second Bank", "Bank", ChartOfAccountKindChoices.ASSETS)
        self.assertEqual(
            self.header(bank)["column_labels"],
            {"deposit": "Deposit", "payment": "Payment"},
        )

    def test_a_credit_card_is_charged_and_paid_down(self):
        """The case the client was solving with a regex on a user-editable title."""
        card = self.typed("Amex", "Credit Cards", ChartOfAccountKindChoices.LIABILITIES)
        self.assertEqual(
            self.header(card)["column_labels"],
            {"deposit": "Charge", "payment": "Payment"},
        )

    def test_everything_else_increases_and_decreases(self):
        loan = self.typed("Loan", "Long Term Liabilities",
                          ChartOfAccountKindChoices.LIABILITIES)
        self.assertEqual(
            self.header(loan)["column_labels"],
            {"deposit": "Increase", "payment": "Decrease"},
        )

    def test_an_untyped_account_still_gets_labels(self):
        """`account_type` is nullable and legacy charts predate the taxonomy."""
        self.assertEqual(
            self.header(self.account)["column_labels"],
            {"deposit": "Increase", "payment": "Decrease"},
        )

    def test_the_sign_behind_the_columns_is_exposed(self):
        self.assertIs(self.header(self.account)["is_debit_natural"], True)
        card = self.typed("Amex", "Credit Cards", ChartOfAccountKindChoices.LIABILITIES)
        self.assertIs(self.header(card)["is_debit_natural"], False)

    def test_a_control_account_is_flagged_without_exposing_its_key(self):
        """`is_fixed` means "seeded" and is true of nearly every account, so it
        cannot key a control-account badge. The boolean can, and unlike
        `system_key` it cannot be used to repoint posting."""
        header = self.header(self.account)
        self.assertIs(header["is_control_account"], False)
        self.assertNotIn("system_key", header)

    def test_a_seeded_control_account_reads_as_one(self):
        from accounts.choices import ChartOfAccountSystemKeyChoices

        self.account.system_key = ChartOfAccountSystemKeyChoices.values[0]
        self.account.save()
        self.assertIs(self.header(self.account)["is_control_account"], True)

    def test_the_key_itself_stays_off_the_serializer(self):
        """`journalio/tests.py` asserts this too -- absence is stronger than
        read-only, and this change must not weaken it."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer,
        )

        self.assertNotIn(
            "system_key", PrivateWeChartOfAccountDetailsSerializer().get_fields()
        )

    def test_reconciled_through_is_null_when_nothing_has_closed(self):
        """Null is a different fact from a date in the past."""
        self.assertIsNone(self.header(self.account)["reconciled_through"])

    def test_reconciled_through_reports_the_latest_closed_session(self):
        """It was computable but unreachable -- the only caller was undo, so the
        watermark could only be learned by destroying a reconciliation."""
        from transactionio.choices import BankReconciliationStatusChoices
        from transactionio.models import BankReconciliation

        for ending in ("2026-01-31", "2026-02-28"):
            BankReconciliation.objects.create(
                company=self.company, bank_account=self.account,
                status=BankReconciliationStatusChoices.CLOSED,
                statement_ending_balance=Decimal("0"),
                beginning_balance=Decimal("0"),
                statement_ending_date=ending, reconciled_on=ending,
            )
        self.assertEqual(
            str(self.header(self.account)["reconciled_through"]), "2026-02-28"
        )


class AmountRangeFilterTests(RegisterTestCase):
    """A leg has no single amount column, which is why there was no filter."""

    def setUp(self):
        super().setUp()
        self.small = self.line("50", "2026-03-01")
        self.big = self.line("500", "2026-03-02")
        self.credit_side = self.line(
            "900", "2026-03-03", side=JournalEntryConnectorKindChoices.CREDIT
        )

    def found(self, **params):
        return {r.pk for r in register(self.user, self.account.uid, **params)}

    def test_a_minimum_excludes_smaller_lines(self):
        self.assertEqual(
            self.found(amount_min="100"), {self.big.pk, self.credit_side.pk}
        )

    def test_a_maximum_excludes_larger_lines(self):
        self.assertEqual(self.found(amount_max="100"), {self.small.pk})

    def test_both_bound_a_window(self):
        self.assertEqual(
            self.found(amount_min="100", amount_max="600"), {self.big.pk}
        )

    def test_it_matches_magnitude_not_the_posting_side(self):
        """Someone looking for "about nine hundred" means it either way."""
        self.assertIn(self.credit_side.pk, self.found(amount_min="900"))

    def test_a_non_numeric_bound_is_refused(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.found(amount_min="lots")

    def test_the_balance_still_spans_the_whole_account(self):
        """Same guarantee as every other filter: the column is the account's
        balance, not the filtered subset's."""
        rows = register(self.user, self.account.uid, amount_min="100")
        self.assertEqual(
            [Decimal(str(r.running_balance)) for r in rows],
            [Decimal("-350"), Decimal("550")],
        )
