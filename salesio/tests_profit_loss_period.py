"""A date-ranged profit and loss must report the period, not a lifetime.

`PrivateWeProfitLossList.get_queryset` narrowed WHICH ACCOUNTS APPEARED to
those with a journal line in range:

    queryset = queryset.filter(has_journal_line(created_at__range=[start, end]))

`has_journal_line` is an `Exists` -- a membership test contributing no amount --
and `list()` then summed each survivor's `ChartOfAccount.opening_balance`, a
lifetime running balance with no date axis. So two adjacent months returned
identical figures for any account touched in both.

Since 2026-09-02 the engine scopes on the leg's own `date` rather than on
`created_at`, so these tests set the two to deliberately different values and
assert the period question is answered by the date the transaction belongs to.

This is wrong on a company with perfect books and zero drift, which is what
separates it from the rest of the stored-balance problem: no repair of the
stored column could ever fix it, because the column cannot answer a period
question.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector

from weapi.django_rest.helpers.reports.profit_loss_engine import INCOME, collect


class ProfitLossPeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.income = ChartOfAccount.objects.create(
            company=cls.company, title="Sales of Product Income", code="4000",
            kind=ChartOfAccountKindChoices.INCOMES,
            opening_balance=Decimal("999999"),  # deliberately wrong: the drift
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def revenue_on(self, when, amount):
        entry = JournalEntry.objects.create(
            company=self.company, kind=JournalEntryKindChoices.SALE, date=when,
        )
        row = JournalEntryConnector.objects.create(
            journal=entry, account=self.income,
            kind=JournalEntryConnectorKindChoices.CREDIT,
            debit=0, credit=Decimal(str(amount)),
            date=when,
        )
        # `created_at` is pushed somewhere ELSE on purpose. `collect` used to
        # scope on `created_at__date` -- the day the row was typed -- and now
        # scopes on the leg's own `date`. Setting the two to different values
        # makes every test in this class also assert that the engine reads the
        # date the transaction belongs to, not the day it was entered.
        JournalEntryConnector.objects.filter(pk=row.pk).update(
            created_at=datetime(2030, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        )
        return row

    def income_total(self, start, end):
        cells, accounts, _ = collect(self.company, start, end)
        return sum(
            cells.get(("total", uid), Decimal("0.00"))
            for uid, account in accounts.items()
            if account["section"] == INCOME
        )

    def test_two_adjacent_months_report_different_figures(self):
        """The defect: they used to be identical."""
        self.revenue_on(date(2026, 1, 15), "100")
        self.revenue_on(date(2026, 2, 15), "250")

        january = self.income_total("2026-01-01", "2026-01-31")
        february = self.income_total("2026-02-01", "2026-02-28")

        self.assertEqual(january, Decimal("100"))
        self.assertEqual(february, Decimal("250"))
        self.assertNotEqual(january, february)

    def test_the_parts_sum_to_the_whole(self):
        self.revenue_on(date(2026, 1, 15), "100")
        self.revenue_on(date(2026, 2, 15), "250")

        january = self.income_total("2026-01-01", "2026-01-31")
        february = self.income_total("2026-02-01", "2026-02-28")
        both = self.income_total("2026-01-01", "2026-02-28")

        self.assertEqual(january + february, both)

    def test_a_month_with_no_activity_reports_zero(self):
        """Not the account's lifetime balance, which is what it used to give."""
        self.revenue_on(date(2026, 1, 15), "100")

        self.assertEqual(self.income_total("2026-02-01", "2026-02-28"), Decimal("0"))

    def test_the_last_day_of_the_range_is_included(self):
        """`created_at` is auto_now_add, so a YYYY-MM-DD upper bound used to
        compare a date against a datetime and drop the final day."""
        self.revenue_on(date(2026, 1, 31), "100")

        self.assertEqual(self.income_total("2026-01-01", "2026-01-31"), Decimal("100"))

    def test_the_figure_ignores_the_drifted_stored_balance(self):
        """The account carries 999,999 in `opening_balance` and no journal."""
        self.revenue_on(date(2026, 1, 15), "100")

        self.assertEqual(self.income_total("2026-01-01", "2026-01-31"), Decimal("100"))
        self.income.refresh_from_db()
        self.assertEqual(
            Decimal(str(self.income.opening_balance)), Decimal("999999"),
            "the stored column is untouched -- the report simply stopped reading it",
        )


class SerializerFallbackTests(TestCase):
    """A row rendered outside the P&L view keeps its old behaviour."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.account = ChartOfAccount.objects.create(
            company=cls.company, title="Sales", code="4000",
            kind=ChartOfAccountKindChoices.INCOMES,
            opening_balance=Decimal("42"),
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def serialize(self, context):
        from weapi.django_rest.serializers.reports.profit_loss_reports import (
            PrivateWeProfitLossListSerializer,
        )

        return PrivateWeProfitLossListSerializer(self.account, context=context).data

    def test_without_a_period_map_it_reads_the_stored_column(self):
        self.assertEqual(Decimal(self.serialize({})["opening_balance"]), Decimal("42"))

    def test_with_a_period_map_it_reads_the_period(self):
        data = self.serialize(
            {"period_amounts": {str(self.account.uid): Decimal("7.50")}}
        )

        self.assertEqual(Decimal(data["opening_balance"]), Decimal("7.50"))

    def test_an_account_absent_from_the_period_map_reports_zero(self):
        data = self.serialize({"period_amounts": {}})

        self.assertEqual(Decimal(data["opening_balance"]), Decimal("0.00"))
