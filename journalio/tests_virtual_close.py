"""Splitting one equity row into two must not move a single total.

P1.2b. The balance sheet carried lifetime earnings on a row labelled "Net
Income", while Retained Earnings -- 0.000 on all 60 production companies,
because nothing has ever posted to it -- sat beside it reading as though the
business had never made a penny. Spec BLZ-FIN-COA-SPEC-001 §5.1 is explicit
that the equation is

    Assets = Liabilities + Contributed Capital + Retained Earnings
             + (Income - Expenses) FOR THE CURRENT FISCAL YEAR

so the single row was mislabelled rather than miscalculated.

**The safety property this file exists to pin:**

    retained_prior(D) + net_income(D)  ==  the value the old single row showed

for every company, every as-of date and every fiscal anchor. It holds by
construction because the current period is derived by SUBTRACTING prior years
from the cumulative figure, never queried independently -- so `equity.total`
and `total_for_liabilities_and_equity` cannot move. These tests assert that
against real rows rather than trusting the algebra, because the algebra is only
true while the implementation keeps deriving rather than querying.

Why subtraction and not two range queries: `net_income_from_journal` filters on
`created_at`, the row's INSERT timestamp, while a lower bound would naturally be
written against the accounting `date`. Production holds rows where those
disagree by months. Composed on different fields the two halves can both exclude
a line -- dropping it from equity entirely -- or both include it and double it.
`test_a_backdated_line_is_never_lost_or_doubled` is that case.
"""

from datetime import date, datetime, time as dtime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.models import ChartOfAccount

from common.django_rest.helpers.fiscal import (
    fiscal_start_month,
    fiscal_year_start,
)

from companyio.models import Company, CompanySetting

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.reports.balance_sheet_engine import (
    build_comparison_rows,
    collect_as_of,
)
from weapi.django_rest.helpers.reports.net_income import net_income_from_journal


class VirtualCloseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Close Co {self._nth}", kind="ECOMMERCE"
        )
        self.income = self._account("Sales", ChartOfAccountKindChoices.INCOMES)
        self.expense = self._account("Rent", ChartOfAccountKindChoices.EXPENSES)
        self.bank = self._account("Bank", ChartOfAccountKindChoices.ASSETS)

    def _account(self, title, kind):
        # Looked up/created without narrowing on status: `status` defaults to
        # DRAFT, and a queryset filtered to ACTIVE silently sees nothing.
        return ChartOfAccount.objects.create(
            company=self.company, title=f"{title} {self._nth}", code="4000",
            kind=kind, status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def post(self, when, amount, account, side=JournalEntryConnectorKindChoices.CREDIT):
        """One journal line dated `when`, with its bank counterpart."""
        entry = JournalEntry.objects.create(
            company=self.company, entry_number=f"JE-{self._nth}-{when}-{amount}",
            amount=Decimal(amount), date=when,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
        )
        other = (
            JournalEntryConnectorKindChoices.DEBIT
            if side == JournalEntryConnectorKindChoices.CREDIT
            else JournalEntryConnectorKindChoices.CREDIT
        )
        made = []
        for account_row, kind in ((account, side), (self.bank, other)):
            made.append(JournalEntryConnector.objects.create(
                journal=entry, account=account_row, kind=kind,
                debit=Decimal(amount) if kind == JournalEntryConnectorKindChoices.DEBIT else 0,
                credit=Decimal(amount) if kind == JournalEntryConnectorKindChoices.CREDIT else 0,
                total=Decimal(amount), last_balance=0, date=when,
            ))

        # `created_at` is forced to match the accounting date, because the
        # readers under test filter on it rather than on `date` -- see
        # `TheCreatedAtFilterIsWrongTests` below. Without this every row a test
        # writes carries today's timestamp, so an as-of in the past excludes
        # the whole fixture and every figure reads 0.00.
        stamp = datetime.combine(when, dtime(12, 0), tzinfo=dt_timezone.utc)
        JournalEntryConnector.objects.filter(
            pk__in=[m.pk for m in made]
        ).update(created_at=stamp)
        JournalEntry.objects.filter(pk=entry.pk).update(created_at=stamp)
        return entry

    # -- the harness the report actually runs -------------------------------

    def rows_as_of(self, as_of):
        """Build the report the way the view does, and index its rows by key."""
        balances, accounts = collect_as_of(self.company, as_of)
        effective = as_of or date.today()
        fy_start = fiscal_year_start(self.company, effective)

        cumulative = net_income_from_journal(self.company, as_of)
        prior = net_income_from_journal(
            self.company, fy_start - timedelta(days=1)
        ).quantize(Decimal("0.01"))

        rows = build_comparison_rows(
            ["current"], {"current": balances}, accounts,
            net_income_by_column={"current": cumulative - prior},
            retained_prior_by_column={"current": prior},
        )
        return {r["key"]: r for r in rows}, cumulative, prior

    def value(self, rows, key):
        return Decimal(rows[key]["values"]["current"])


class TheInvariantTests(VirtualCloseCase):
    """The two rows must always sum to what the one row used to show."""

    def assert_partition(self, as_of, label):
        rows, cumulative, prior = self.rows_as_of(as_of)
        split = self.value(rows, "equity.retained_earnings_prior") + self.value(
            rows, "equity.net_income"
        )
        self.assertEqual(
            split,
            Decimal(cumulative).quantize(Decimal("0.01")),
            f"{label}: the split does not sum to the cumulative figure the "
            f"single row used to carry",
        )
        return rows

    def test_a_company_in_its_first_year(self):
        """Prior years is zero and the row still appears.

        A statement whose shape depends on its data breaks anything rendering a
        fixed layout, so the row is emitted at zero rather than omitted.
        """
        self.post(date(2026, 3, 1), "1000.00", self.income)

        rows = self.assert_partition(date(2026, 8, 1), "first year")

        self.assertIn("equity.retained_earnings_prior", rows)
        self.assertEqual(
            self.value(rows, "equity.retained_earnings_prior"), Decimal("0.00")
        )
        self.assertEqual(self.value(rows, "equity.net_income"), Decimal("1000.00"))

    def test_two_years_split_at_the_fiscal_boundary(self):
        self.post(date(2025, 6, 1), "700.00", self.income)
        self.post(date(2026, 3, 1), "1000.00", self.income)

        rows = self.assert_partition(date(2026, 8, 1), "two years")

        self.assertEqual(
            self.value(rows, "equity.retained_earnings_prior"), Decimal("700.00")
        )
        self.assertEqual(self.value(rows, "equity.net_income"), Decimal("1000.00"))

    def test_expenses_reduce_both_halves_correctly(self):
        self.post(date(2025, 6, 1), "700.00", self.income)
        self.post(
            date(2025, 7, 1), "200.00", self.expense,
            side=JournalEntryConnectorKindChoices.DEBIT,
        )
        self.post(date(2026, 3, 1), "1000.00", self.income)
        self.post(
            date(2026, 4, 1), "150.00", self.expense,
            side=JournalEntryConnectorKindChoices.DEBIT,
        )

        rows = self.assert_partition(date(2026, 8, 1), "income and expense")

        self.assertEqual(
            self.value(rows, "equity.retained_earnings_prior"), Decimal("500.00")
        )
        self.assertEqual(self.value(rows, "equity.net_income"), Decimal("850.00"))

    def test_a_backdated_line_is_never_lost_or_doubled(self):
        """The reason the current period is a subtraction, not a query.

        A line whose accounting date and insert timestamp fall in different
        fiscal years is exactly what breaks a two-range-query implementation:
        composed on different date fields the halves can both exclude it, or
        both include it. Under subtraction it lands in precisely one half
        whichever field the underlying filter uses, because the halves are
        defined as `total` and `total - prior`.
        """
        self.post(date(2025, 12, 15), "400.00", self.income)
        self.post(date(2026, 5, 1), "600.00", self.income)

        rows, cumulative, prior = self.rows_as_of(date(2026, 8, 1))
        retained = self.value(rows, "equity.retained_earnings_prior")
        current = self.value(rows, "equity.net_income")

        self.assertEqual(retained + current, Decimal(cumulative).quantize(Decimal("0.01")))
        self.assertEqual(retained + current, Decimal("1000.00"),
                         "a line went missing or was counted twice")

    def test_the_equity_total_does_not_move(self):
        """The whole point: this is a presentation split, not a new number."""
        self.post(date(2025, 6, 1), "700.00", self.income)
        self.post(date(2026, 3, 1), "1000.00", self.income)

        as_of = date(2026, 8, 1)
        balances, accounts = collect_as_of(self.company, as_of)
        cumulative = net_income_from_journal(self.company, as_of)

        # The report as it was: one row, no split.
        before = {
            r["key"]: r for r in build_comparison_rows(
                ["current"], {"current": balances}, accounts,
                net_income_by_column={"current": cumulative},
            )
        }
        after, _, _ = self.rows_as_of(as_of)

        for key in ("equity.total", "total_for_liabilities_and_equity",
                    "assets.total", "liabilities.total"):
            self.assertEqual(
                before[key]["values"]["current"],
                after[key]["values"]["current"],
                f"{key} moved -- this change must not alter any total",
            )


class FiscalAnchorTests(VirtualCloseCase):
    """The boundary follows the company's own setting, not a hardcoded month."""

    def test_january_is_the_default_when_unset(self):
        self.assertEqual(fiscal_start_month(self.company), 1)
        self.assertEqual(
            fiscal_year_start(self.company, date(2026, 8, 13)), date(2026, 1, 1)
        )

    def test_an_october_anchor_moves_the_boundary_back_a_year(self):
        CompanySetting.objects.update_or_create(
            company=self.company,
            defaults={"preffered_first_financial_month": "OCTOBER"},
        )
        # August 2026 sits inside the fiscal year that opened October 2025.
        self.assertEqual(
            fiscal_year_start(self.company, date(2026, 8, 13)), date(2025, 10, 1)
        )
        # November 2026 is already in the next one.
        self.assertEqual(
            fiscal_year_start(self.company, date(2026, 11, 2)), date(2026, 10, 1)
        )

    def test_the_anchor_changes_which_side_of_the_split_a_line_falls(self):
        self.post(date(2025, 11, 15), "300.00", self.income)
        self.post(date(2026, 5, 1), "800.00", self.income)

        _, _, prior_january = self.rows_as_of(date(2026, 8, 1))
        self.assertEqual(prior_january, Decimal("300.00"))

        CompanySetting.objects.update_or_create(
            company=self.company,
            defaults={"preffered_first_financial_month": "OCTOBER"},
        )
        rows, cumulative, prior_october = self.rows_as_of(date(2026, 8, 1))

        self.assertEqual(
            prior_october, Decimal("0.00"),
            "under an October anchor the Nov-2025 line is CURRENT year",
        )
        # And the invariant survives the anchor change.
        self.assertEqual(
            self.value(rows, "equity.retained_earnings_prior")
            + self.value(rows, "equity.net_income"),
            Decimal(cumulative).quantize(Decimal("0.01")),
        )

    def test_an_unrecognised_setting_falls_back_rather_than_raising(self):
        """A settings row must never be able to take the balance sheet down."""
        CompanySetting.objects.update_or_create(
            company=self.company,
            defaults={"preffered_first_financial_month": "not-a-month"},
        )
        self.assertEqual(fiscal_start_month(self.company), 1)

    def test_a_blank_setting_reads_as_january(self):
        """53 of 60 production companies hold NULL and 6 hold empty string."""
        CompanySetting.objects.update_or_create(
            company=self.company,
            defaults={"preffered_first_financial_month": ""},
        )
        self.assertEqual(fiscal_start_month(self.company), 1)

    def test_no_settings_row_at_all_reads_as_january(self):
        CompanySetting.objects.filter(company=self.company).delete()
        self.assertEqual(fiscal_start_month(self.company), 1)


class BackwardCompatibilityTests(VirtualCloseCase):
    """A caller that has not been taught the split still gets today's numbers."""

    def test_omitting_the_new_argument_leaves_net_income_whole(self):
        self.post(date(2025, 6, 1), "700.00", self.income)
        self.post(date(2026, 3, 1), "1000.00", self.income)

        as_of = date(2026, 8, 1)
        balances, accounts = collect_as_of(self.company, as_of)
        cumulative = net_income_from_journal(self.company, as_of)

        rows = {
            r["key"]: r for r in build_comparison_rows(
                ["current"], {"current": balances}, accounts,
                net_income_by_column={"current": cumulative},
            )
        }

        self.assertEqual(
            Decimal(rows["equity.net_income"]["values"]["current"]),
            Decimal(cumulative).quantize(Decimal("0.01")),
        )
        self.assertEqual(
            Decimal(rows["equity.retained_earnings_prior"]["values"]["current"]),
            Decimal("0.00"),
        )


class TheCreatedAtFilterIsWrongTests(VirtualCloseCase):
    """A pre-existing defect this work surfaced but deliberately does not fix.

    Both readers behind the balance sheet filter on `created_at` -- the row's
    INSERT timestamp -- rather than on the accounting `date` that
    `JournalEntry` and `JournalEntryConnector` both carry:

        balance_sheet_engine.collect_as_of      `created_at__date__lte=as_of`
        net_income.net_income_from_journal      `created_at__date__lte=as_of`

    ...which meant a transaction dated last year but entered today was absent
    from a balance sheet as of last December and appeared in one as of today. An
    accountant backdating an adjustment into a prior period could not see it
    land there — and worse, amending a March sale in September deleted its legs
    and reposted them with a September `created_at`, so March's revenue silently
    left the March P&L and never came back. **A prior period changed after the
    fact, with no lock involved.**

    **Fixed 2026-09-02: all three now filter the leg's own `date`.** The choice
    is header-authoritative — `JournalEntry.date` is the truth and every leg
    inherits it, which `create_journal_entry_connector` has always done by
    default and which nothing ever wrote against. `"date"` has also been dropped
    from `EDITABLE_JOURNAL_LINE_FIELDS`, closing the one path that could give a
    leg a date of its own.

    Why header rather than leg: double-entry balances *within a period*. A
    document whose legs sit in two periods leaves each of them individually
    unbalanced, so no period-scoped balance sheet could ever tie out. The
    expressiveness that seems to buy — a prepayment spread over twelve months —
    is twelve balanced entries in real accounting, not one entry with twelve
    dates.

    This restates history, which is why it was deferred until somebody decided
    it. The cost was measured first: 691 of 691 production entries carried
    `date == created_at::date`, and only eleven documents disagreed.
    """

    def test_a_backdated_entry_is_filed_by_its_own_date(self):
        """The inversion the previous version of this test asked for."""
        entry = self.post(date(2026, 5, 1), "500.00", self.income)
        # Typed in August, dated May. It belongs to May.
        JournalEntryConnector.objects.filter(journal=entry).update(
            created_at=datetime(2026, 8, 13, 12, 0, tzinfo=dt_timezone.utc)
        )

        as_of_after_the_accounting_date = net_income_from_journal(
            self.company, date(2026, 6, 1)
        )

        self.assertEqual(
            Decimal(as_of_after_the_accounting_date), Decimal("500"),
            "a June-as-of net income must include a May transaction, whenever "
            "it was typed",
        )

    def test_it_is_absent_before_its_own_date(self):
        """The other half: it must not appear in a period it predates."""
        entry = self.post(date(2026, 5, 1), "500.00", self.income)
        JournalEntryConnector.objects.filter(journal=entry).update(
            created_at=datetime(2026, 8, 13, 12, 0, tzinfo=dt_timezone.utc)
        )

        self.assertEqual(
            Decimal(net_income_from_journal(self.company, date(2026, 4, 1))),
            Decimal("0"),
            "an April-as-of net income must not include a May transaction",
        )

    def test_the_split_survives_the_defect(self):
        """Whatever set the predicate returns, the two halves partition it."""
        self.post(date(2025, 6, 1), "700.00", self.income)
        entry = self.post(date(2026, 3, 1), "1000.00", self.income)
        JournalEntryConnector.objects.filter(journal=entry).update(
            created_at=datetime(2026, 8, 13, 12, 0, tzinfo=dt_timezone.utc)
        )

        rows, cumulative, _prior = self.rows_as_of(date(2026, 8, 20))

        self.assertEqual(
            self.value(rows, "equity.retained_earnings_prior")
            + self.value(rows, "equity.net_income"),
            Decimal(cumulative).quantize(Decimal("0.01")),
        )
