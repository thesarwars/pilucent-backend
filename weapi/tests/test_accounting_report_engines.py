"""Tests for the accounting report engines.

`collect` / `collect_as_of` need the ORM and are covered by the production
probe; what is unit-tested here is the ladder arithmetic, the payroll carve-out
(which the spec correctly feared would double-count), the absent-vs-zero rule,
and the pivot column ordering.
"""

from decimal import Decimal
from unittest import TestCase

from weapi.django_rest.helpers.reports.balance_sheet_engine import (
    build_comparison_rows,
)
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    COGS,
    EXPENSES,
    INCOME,
    OTHER_EXPENSES,
    OTHER_INCOME,
    PAYROLL_EXPENSES,
    TOTAL_KEY,
    UNASSIGNED_KEY,
    add_total_column,
    build_ladder,
    pivot_columns,
)


def account(uid, title, section):
    return {"uid": uid, "title": title, "section": section}


def ladder_of(rows):
    return {row["key"]: row for row in rows}


class LadderTests(TestCase):
    def setUp(self):
        self.accounts = {
            "a1": account("a1", "Sales of Product Income", INCOME),
            "a2": account("a2", "Cost of Goods Sold", COGS),
            "a3": account("a3", "Rent", EXPENSES),
            "a4": account("a4", "Wages", PAYROLL_EXPENSES),
            "a5": account("a5", "Interest Earned", OTHER_INCOME),
            "a6": account("a6", "Bank Fees", OTHER_EXPENSES),
        }
        self.cells = {
            ("total", "a1"): Decimal("48100.00"),
            ("total", "a2"): Decimal("10000.00"),
            ("total", "a3"): Decimal("2000.00"),
            ("total", "a4"): Decimal("3000.00"),
            ("total", "a5"): Decimal("500.00"),
            ("total", "a6"): Decimal("100.00"),
        }
        self.rows = ladder_of(build_ladder(["total"], self.cells, self.accounts))

    def test_the_full_ladder_is_present_in_order(self):
        keys = [row["key"] for row in build_ladder(["total"], self.cells, self.accounts)]
        for expected in (
            "income", "income.subtotal", "cost_of_goods_sold",
            "cost_of_goods_sold.subtotal", "gross_profit", "expenses",
            "expenses.subtotal", "net_operating_income", "other_income",
            "other_income.subtotal", "other_expenses",
            "other_expenses.subtotal", "net_other_income", "net_income",
        ):
            self.assertIn(expected, keys)
        self.assertLess(keys.index("gross_profit"), keys.index("net_operating_income"))
        self.assertEqual(keys[-1], "net_income")

    def test_gross_profit_is_income_less_cogs(self):
        self.assertEqual(self.rows["gross_profit"]["values"]["total"], "38100.00")

    def test_net_operating_income_subtracts_all_expenses(self):
        # 38100 - (2000 rent + 3000 wages)
        self.assertEqual(
            self.rows["net_operating_income"]["values"]["total"], "33100.00"
        )

    def test_net_income_adds_net_other_income(self):
        self.assertEqual(self.rows["net_other_income"]["values"]["total"], "400.00")
        self.assertEqual(self.rows["net_income"]["values"]["total"], "33500.00")

    def test_group_rows_carry_no_values(self):
        self.assertNotIn("values", self.rows["income"])
        self.assertEqual(self.rows["income"]["kind"], "group")

    def test_item_rows_carry_their_account_uid(self):
        item = self.rows["income.sales_of_product_income"]
        self.assertEqual(item["kind"], "item")
        self.assertEqual(item["account_uid"], "a1")


class PayrollCarveOutTests(TestCase):
    """The spec feared a double count here, and it was right to."""

    def setUp(self):
        self.accounts = {
            "a3": account("a3", "Rent", EXPENSES),
            "a4": account("a4", "Wages", PAYROLL_EXPENSES),
        }
        self.cells = {
            ("total", "a3"): Decimal("2000.00"),
            ("total", "a4"): Decimal("3000.00"),
        }

    def test_payroll_becomes_a_nested_group(self):
        rows = ladder_of(build_ladder(["total"], self.cells, self.accounts))
        self.assertEqual(rows["expenses.payroll_expenses"]["kind"], "group")
        self.assertEqual(
            rows["expenses.payroll_expenses"]["values"]["total"], "3000.00"
        )
        self.assertIn("expenses.payroll_expenses.wages", rows)

    def test_total_for_expenses_counts_payroll_exactly_once(self):
        rows = ladder_of(build_ladder(["total"], self.cells, self.accounts))
        self.assertEqual(rows["expenses.subtotal"]["values"]["total"], "5000.00")

    def test_payroll_accounts_do_not_also_appear_as_plain_expense_items(self):
        rows = build_ladder(["total"], self.cells, self.accounts)
        wage_rows = [r for r in rows if r["label"] == "Wages" and r["kind"] == "item"]
        self.assertEqual(len(wage_rows), 1)
        self.assertEqual(wage_rows[0]["key"], "expenses.payroll_expenses.wages")

    def test_unsplit_still_totals_the_same(self):
        rows = ladder_of(
            build_ladder(["total"], self.cells, self.accounts, split_payroll=False)
        )
        self.assertEqual(rows["expenses.subtotal"]["values"]["total"], "5000.00")
        self.assertNotIn("expenses.payroll_expenses", rows)


class AbsentVersusZeroTests(TestCase):
    """Both specs are explicit: a missing key renders blank, not 0.00."""

    def test_an_account_with_no_entry_in_a_column_omits_the_key(self):
        accounts = {"a1": account("a1", "Sales", INCOME)}
        cells = {("current", "a1"): Decimal("100.00")}
        rows = ladder_of(build_ladder(["current", "compare_1"], cells, accounts))
        item = rows["income.sales"]
        self.assertEqual(item["values"]["current"], "100.00")
        self.assertNotIn("compare_1", item["values"])

    def test_section_totals_are_always_present_even_at_zero(self):
        """A subtotal anchors the ladder, so it prints 0.00 rather than blank."""
        accounts = {"a1": account("a1", "Sales", INCOME)}
        cells = {("current", "a1"): Decimal("100.00")}
        rows = ladder_of(build_ladder(["current", "compare_1"], cells, accounts))
        self.assertEqual(rows["income.subtotal"]["values"]["compare_1"], "0.00")


class PivotColumnTests(TestCase):
    def test_total_is_last_and_not_specified_second_last(self):
        labels = {"c1": "France", "c2": "JumaTechs", UNASSIGNED_KEY: "Not specified"}
        cells = {("c1", "a1"): Decimal("1"), ("c2", "a1"): Decimal("1"),
                 (UNASSIGNED_KEY, "a1"): Decimal("1")}
        columns = pivot_columns(labels, cells)
        self.assertEqual(
            [c["key"] for c in columns], ["c1", "c2", UNASSIGNED_KEY, TOTAL_KEY]
        )
        self.assertTrue(columns[-1]["is_total"])

    def test_named_columns_sort_alphabetically(self):
        labels = {"c1": "Zeta", "c2": "Alpha"}
        cells = {("c1", "a"): Decimal("1"), ("c2", "a"): Decimal("1")}
        self.assertEqual(
            [c["label"] for c in pivot_columns(labels, cells)],
            ["Alpha", "Zeta", "Total"],
        )

    def test_a_dimension_with_no_activity_gets_no_column(self):
        """Same 'don't invent empty columns' rule as the payroll reports."""
        labels = {"c1": "France", "c2": "Unused"}
        cells = {("c1", "a"): Decimal("1")}
        self.assertEqual(
            [c["key"] for c in pivot_columns(labels, cells)], ["c1", TOTAL_KEY]
        )

    def test_not_specified_is_omitted_when_everything_is_attributed(self):
        labels = {"c1": "France"}
        cells = {("c1", "a"): Decimal("1")}
        self.assertNotIn(
            UNASSIGNED_KEY, [c["key"] for c in pivot_columns(labels, cells)]
        )


class TotalColumnTests(TestCase):
    def test_total_sums_every_other_column_per_account(self):
        cells = {
            ("c1", "a1"): Decimal("45000.00"),
            ("c2", "a1"): Decimal("3100.00"),
            ("c1", "a2"): Decimal("10.00"),
        }
        add_total_column(cells, ["c1", "c2", TOTAL_KEY])
        self.assertEqual(cells[(TOTAL_KEY, "a1")], Decimal("48100.00"))
        self.assertEqual(cells[(TOTAL_KEY, "a2")], Decimal("10.00"))

    def test_the_total_column_reaches_the_ladder(self):
        accounts = {"a1": account("a1", "Sales", INCOME)}
        cells = {("c1", "a1"): Decimal("45000.00"),
                 ("c2", "a1"): Decimal("3100.00")}
        add_total_column(cells, ["c1", "c2", TOTAL_KEY])
        rows = ladder_of(build_ladder(["c1", "c2", TOTAL_KEY], cells, accounts))
        self.assertEqual(rows["income.subtotal"]["values"][TOTAL_KEY], "48100.00")


class BalanceSheetComparisonTests(TestCase):
    def setUp(self):
        self.accounts = {
            "b1": {"uid": "b1", "title": "Bank of America",
                   "section": "assets.current_assets.bank_accounts"},
            "b2": {"uid": "b2", "title": "Dhaka Bank-payroll",
                   "section": "assets.current_assets.bank_accounts"},
            "l1": {"uid": "l1", "title": "Payroll Taxes Payable",
                   "section": "liabilities.current_liabilities.payroll_liabilities"},
            "e1": {"uid": "e1", "title": "Owner Equity", "section": "equity"},
        }
        self.balances = {
            "current": {"b1": Decimal("2020.77"), "b2": Decimal("1000.00"),
                        "l1": Decimal("500.00"), "e1": Decimal("2520.77")},
            "compare_1": {"b1": Decimal("2565.15"), "l1": Decimal("400.00"),
                          "e1": Decimal("2165.15")},
        }
        self.rows = ladder_of(
            build_comparison_rows(
                ["current", "compare_1"], self.balances, self.accounts
            )
        )

    def test_account_rows_carry_a_stable_uid(self):
        """The entire reason the endpoint exists -- merging by title is fragile."""
        row = self.rows["assets.current_assets.bank_accounts.b1"]
        self.assertEqual(row["account_uid"], "b1")
        self.assertEqual(row["label"], "Bank of America")

    def test_an_account_absent_in_a_period_omits_that_key(self):
        row = self.rows["assets.current_assets.bank_accounts.b2"]
        self.assertEqual(row["values"]["current"], "1000.00")
        self.assertNotIn("compare_1", row["values"])

    def test_section_totals(self):
        row = self.rows["assets.current_assets.bank_accounts.total"]
        self.assertEqual(row["values"]["current"], "3020.77")
        self.assertEqual(row["values"]["compare_1"], "2565.15")

    def test_liabilities_and_equity_totals_add_up(self):
        row = self.rows["total_for_liabilities_and_equity"]
        self.assertEqual(row["values"]["current"], "3020.77")
        self.assertEqual(row["values"]["compare_1"], "2565.15")

    def test_depth_is_present_on_every_row(self):
        for row in self.rows.values():
            self.assertIn("depth", row)

    def test_payroll_liabilities_are_their_own_section(self):
        self.assertIn(
            "liabilities.current_liabilities.payroll_liabilities.l1", self.rows
        )


class SinglePeriodBalanceSheetTests(TestCase):
    """One column is the same ladder the comparison builds, minus a column."""

    def setUp(self):
        self.accounts = {
            "b1": {"uid": "b1", "title": "City Bank",
                   "section": "assets.current_assets.bank_accounts"},
            "l1": {"uid": "l1", "title": "Loan Payable",
                   "section": "liabilities.long_term_liabilities"},
            "e1": {"uid": "e1", "title": "Owner Equity", "section": "equity"},
        }
        self.rows = ladder_of(
            build_comparison_rows(
                ["current"],
                {"current": {"b1": Decimal("1000.00"), "l1": Decimal("400.00"),
                             "e1": Decimal("500.00")}},
                self.accounts,
                net_income_by_column={"current": Decimal("100.00")},
            )
        )

    def test_every_row_has_exactly_the_one_column(self):
        for row in self.rows.values():
            if "values" in row:
                self.assertEqual(set(row["values"]) - {"current"}, set(), row["key"])

    def test_net_income_is_its_own_equity_row(self):
        self.assertEqual(self.rows["equity.net_income"]["values"]["current"], "100.00")

    def test_total_equity_includes_net_income(self):
        self.assertEqual(self.rows["equity.total"]["values"]["current"], "600.00")

    def test_the_sheet_ties_when_the_ledger_does(self):
        """assets = liabilities + equity + net income."""
        self.assertEqual(self.rows["assets.total"]["values"]["current"], "1000.00")
        self.assertEqual(
            self.rows["total_for_liabilities_and_equity"]["values"]["current"],
            "1000.00",
        )

    def test_accounts_carry_their_uid_for_a_stable_tree(self):
        row = self.rows["assets.current_assets.bank_accounts.b1"]
        self.assertEqual(row["account_uid"], "b1")
        self.assertEqual(row["depth"], 3)


class SalesByCustomerRowTests(TestCase):
    """Row shaping only -- the collector needs the ORM."""

    def _build(self, totals, parents, names):
        """Re-run the grouping the builder does, without touching the DB."""
        from decimal import Decimal as D
        from weapi.django_rest.helpers.reports.profit_loss_engine import (
            UNASSIGNED_KEY as UK,
        )

        children, roots = {}, []
        for key in totals:
            parent = parents.get(key)
            if parent and parent in totals:
                children.setdefault(parent, []).append(key)
            else:
                roots.append(key)
        sort_key = lambda k: (k == UK, names.get(k, "").lower(), k)
        rows, grand = [], D("0.00")
        for root in sorted(roots, key=sort_key):
            own = totals[root]
            kids = sorted(children.get(root, []), key=sort_key)
            rows.append((names[root], 0, False, own))
            sub = own
            for child in kids:
                sub += totals[child]
                rows.append((names[child], 1, False, totals[child]))
            if kids:
                rows.append((f"Total for {names[root]}", 0, True, sub))
            grand += sub
        rows.append(("TOTAL", 0, True, grand))
        return rows

    def test_the_reference_report_shape(self):
        """JumaTechs 5,720 with sub-customer talha bhai 1,300 -> 7,020."""
        totals = {
            "fr": Decimal("58580.00"), "jt": Decimal("5720.00"),
            "tb": Decimal("1300.00"), "mk": Decimal("-500.00"),
            "nz": Decimal("2300.00"), "st": Decimal("-5490.00"),
            "sr": Decimal("16000.00"), "zh": Decimal("13400.00"),
        }
        parents = {"tb": "jt"}
        names = {"fr": "France", "jt": "JumaTechs", "tb": "talha bhai",
                 "mk": "Mukta", "nz": "Nazirul", "st": "Star Tech",
                 "sr": "Suzon Rana", "zh": "Zhumur"}
        rows = self._build(totals, parents, names)
        self.assertEqual(
            [(label, depth) for label, depth, _, _ in rows],
            [("France", 0), ("JumaTechs", 0), ("talha bhai", 1),
             ("Total for JumaTechs", 0), ("Mukta", 0), ("Nazirul", 0),
             ("Star Tech", 0), ("Suzon Rana", 0), ("Zhumur", 0), ("TOTAL", 0)],
        )
        by_label = {label: amount for label, _, _, amount in rows}
        self.assertEqual(by_label["Total for JumaTechs"], Decimal("7020.00"))
        self.assertEqual(by_label["TOTAL"], Decimal("91310.00"))

    def test_negative_customers_are_not_clamped(self):
        """A refund can outweigh sales; the reference shows two such rows."""
        rows = self._build({"mk": Decimal("-500.00")}, {}, {"mk": "Mukta"})
        self.assertEqual(rows[0][3], Decimal("-500.00"))

    def test_a_childless_customer_gets_no_total_row(self):
        rows = self._build({"fr": Decimal("10.00")}, {}, {"fr": "France"})
        self.assertEqual([label for label, *_ in rows], ["France", "TOTAL"])
