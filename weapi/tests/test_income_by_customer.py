"""Tests for the Income by Customer Summary report.

Assembly is checked against the reference PDF's worked example (Halo Axis,
January-December 2026), then against the cases the reference cannot show:
sub-customer nesting, unattributed activity, and the sign edges (a customer
with no costs must print `0.00`, not `-0.00`; a loss-making customer must print
a negative net income).
"""

from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from weapi.django_rest.helpers.reports.customer_tree import (
    group_by_parent,
    sort_key,
    tree_rows,
)
from weapi.django_rest.helpers.reports.income_by_customer import (
    build_income_by_customer,
)
from weapi.django_rest.helpers.reports.profit_loss_engine import (
    COGS,
    EXPENSES,
    INCOME,
    OTHER_EXPENSES,
    OTHER_INCOME,
    PAYROLL_EXPENSES,
    UNASSIGNED_KEY,
)


FRANCE, JUMATECHS, MASUD = "c-fra", "c-jum", "c-mas"

NAMES = {FRANCE: "France", JUMATECHS: "JumaTechs", MASUD: "Mr Masud Rana"}

SALES, SERVICE, COST, RENT, INTEREST, FEES = (
    "a-sales",
    "a-service",
    "a-cogs",
    "a-rent",
    "a-interest",
    "a-fees",
)

ACCOUNTS = {
    SALES: {"uid": SALES, "title": "Sales of Product Income", "section": INCOME},
    SERVICE: {"uid": SERVICE, "title": "Services", "section": INCOME},
    COST: {"uid": COST, "title": "Cost of Goods Sold", "section": COGS},
    RENT: {"uid": RENT, "title": "Rent", "section": EXPENSES},
    INTEREST: {"uid": INTEREST, "title": "Interest Earned", "section": OTHER_INCOME},
    FEES: {"uid": FEES, "title": "Bank Fees", "section": OTHER_EXPENSES},
}


def run(cells, accounts=None, labels=None, parents=None, names=None):
    """Drive the builder with a stubbed engine and customer tree."""
    accounts = accounts or ACCOUNTS
    decimal_cells = {key: Decimal(value) for key, value in cells.items()}
    names = names or NAMES
    keys = {key for key, _ in decimal_cells}
    tree = (
        parents or {key: None for key in keys if key != UNASSIGNED_KEY},
        {key: names[key] for key in keys if key in names},
    )
    with patch(
        "weapi.django_rest.helpers.reports.income_by_customer.collect",
        return_value=(decimal_cells, accounts, labels or names),
    ), patch(
        "weapi.django_rest.helpers.reports.income_by_customer.customer_tree",
        return_value=tree,
    ):
        return build_income_by_customer(object(), None, None)


def rows_by_key(report):
    return {row["key"]: row for row in report["rows"]}


# The reference dataset: income and cost of goods sold per customer.
REFERENCE = {
    (FRANCE, SALES): "65000.00",
    (FRANCE, COST): "51800.00",
    (JUMATECHS, SALES): "2600.00",
    (JUMATECHS, COST): "2400.00",
    (MASUD, SALES): "800.00",
}


class ReferenceFigureTests(TestCase):
    def setUp(self):
        self.report = run(REFERENCE)
        self.rows = rows_by_key(self.report)

    def test_columns(self):
        self.assertEqual(
            [column["key"] for column in self.report["columns"]],
            ["name", "income", "expenses", "net_income"],
        )

    def test_france(self):
        row = self.rows[FRANCE]
        self.assertEqual(row["income"], "65000.00")
        self.assertEqual(row["expenses"], "-51800.00")
        self.assertEqual(row["net_income"], "13200.00")

    def test_jumatechs(self):
        row = self.rows[JUMATECHS]
        self.assertEqual(row["income"], "2600.00")
        self.assertEqual(row["expenses"], "-2400.00")
        self.assertEqual(row["net_income"], "200.00")

    def test_a_customer_with_no_costs_prints_unsigned_zero(self):
        row = self.rows[MASUD]
        self.assertEqual(row["income"], "800.00")
        self.assertEqual(row["expenses"], "0.00")
        self.assertEqual(row["net_income"], "800.00")

    def test_total(self):
        row = self.rows["total"]
        self.assertEqual(row["income"], "68400.00")
        self.assertEqual(row["expenses"], "-54200.00")
        self.assertEqual(row["net_income"], "14200.00")

    def test_rows_are_alphabetical_with_total_last(self):
        self.assertEqual(
            [row["label"] for row in self.report["rows"]],
            ["France", "JumaTechs", "Mr Masud Rana", "TOTAL"],
        )

    def test_customer_rows_link_by_uid_and_totals_do_not(self):
        self.assertEqual(self.rows[FRANCE]["customer_uid"], FRANCE)
        self.assertFalse(self.rows[FRANCE]["is_total"])
        self.assertIsNone(self.rows["total"]["customer_uid"])
        self.assertTrue(self.rows["total"]["is_total"])


class SectionMappingTests(TestCase):
    def test_every_profit_and_loss_section_lands_in_a_column(self):
        report = run(
            {
                (FRANCE, SALES): "100.00",
                (FRANCE, INTEREST): "10.00",
                (FRANCE, COST): "40.00",
                (FRANCE, RENT): "20.00",
                (FRANCE, FEES): "5.00",
            }
        )
        row = rows_by_key(report)[FRANCE]
        # Income + Other Income; COGS + Expenses + Other Expenses.
        self.assertEqual(row["income"], "110.00")
        self.assertEqual(row["expenses"], "-65.00")
        self.assertEqual(row["net_income"], "45.00")

    def test_payroll_expenses_are_counted_once(self):
        accounts = dict(
            ACCOUNTS,
            **{"a-wages": {"uid": "a-wages", "title": "Wages",
                           "section": PAYROLL_EXPENSES}},
        )
        report = run(
            {(FRANCE, SALES): "100.00", (FRANCE, "a-wages"): "30.00"},
            accounts=accounts,
        )
        row = rows_by_key(report)[FRANCE]
        self.assertEqual(row["expenses"], "-30.00")
        self.assertEqual(row["net_income"], "70.00")


class SignTests(TestCase):
    def test_a_loss_making_customer_nets_negative(self):
        report = run({(FRANCE, SALES): "100.00", (FRANCE, COST): "250.00"})
        row = rows_by_key(report)[FRANCE]
        self.assertEqual(row["expenses"], "-250.00")
        self.assertEqual(row["net_income"], "-150.00")

    def test_a_customer_with_no_activity_at_all_prints_zeros(self):
        report = run({(FRANCE, SALES): "0.00"})
        row = rows_by_key(report)[FRANCE]
        self.assertEqual(
            (row["income"], row["expenses"], row["net_income"]),
            ("0.00", "0.00", "0.00"),
        )

    def test_negative_income_survives(self):
        # A credit note outweighing the period's sales.
        report = run({(FRANCE, SALES): "-500.00"})
        row = rows_by_key(report)[FRANCE]
        self.assertEqual(row["income"], "-500.00")
        self.assertEqual(row["net_income"], "-500.00")


class UnattributedTests(TestCase):
    def test_not_specified_sorts_last_and_carries_no_uid(self):
        report = run(
            {
                (FRANCE, SALES): "100.00",
                (UNASSIGNED_KEY, RENT): "70.00",
            }
        )
        self.assertEqual(
            [row["label"] for row in report["rows"]],
            ["France", "Not specified", "TOTAL"],
        )
        row = rows_by_key(report)[UNASSIGNED_KEY]
        self.assertIsNone(row["customer_uid"])
        self.assertEqual(row["expenses"], "-70.00")
        self.assertEqual(rows_by_key(report)["total"]["net_income"], "30.00")


class NestingTests(TestCase):
    def setUp(self):
        names = dict(NAMES, **{"c-par": "Paris"})
        self.report = run(
            {
                (FRANCE, SALES): "1000.00",
                (FRANCE, COST): "400.00",
                ("c-par", SALES): "200.00",
                ("c-par", COST): "100.00",
                (JUMATECHS, SALES): "50.00",
            },
            parents={FRANCE: None, "c-par": FRANCE, JUMATECHS: None},
            names=names,
        )
        self.rows = rows_by_key(self.report)

    def test_a_child_is_indented_under_its_parent(self):
        self.assertEqual(
            [(row["label"], row["depth"]) for row in self.report["rows"]],
            [
                ("France", 0),
                ("Paris", 1),
                ("Total for France", 0),
                ("JumaTechs", 0),
                ("TOTAL", 0),
            ],
        )

    def test_the_parent_total_adds_the_child(self):
        row = self.rows[f"{FRANCE}.total"]
        self.assertEqual(row["income"], "1200.00")
        self.assertEqual(row["expenses"], "-500.00")
        self.assertEqual(row["net_income"], "700.00")
        self.assertTrue(row["is_total"])

    def test_a_childless_customer_gets_no_restating_total_row(self):
        self.assertNotIn(f"{JUMATECHS}.total", self.rows)

    def test_the_grand_total_counts_each_customer_once(self):
        row = self.rows["total"]
        self.assertEqual(row["income"], "1250.00")
        self.assertEqual(row["expenses"], "-500.00")
        self.assertEqual(row["net_income"], "750.00")


class DeepNestingTests(TestCase):
    """A sub-customer of a sub-customer must not vanish.

    The first version of the walk rendered only roots and their direct
    children, so a three-level chain silently dropped the grandchild from its
    row *and* from every total above it -- money disappearing from a financial
    report with no indication.
    """

    def setUp(self):
        names = {"c-a": "Alpha", "c-b": "Beta", "c-g": "Gamma"}
        self.report = run(
            {
                ("c-a", SALES): "1000.00",
                ("c-b", SALES): "500.00",
                ("c-g", SALES): "250.00",
            },
            parents={"c-a": None, "c-b": "c-a", "c-g": "c-b"},
            names=names,
        )
        self.rows = rows_by_key(self.report)

    def test_the_grandchild_is_rendered_at_depth_two(self):
        self.assertEqual(
            [(row["label"], row["depth"]) for row in self.report["rows"]],
            [
                ("Alpha", 0),
                ("Beta", 1),
                ("Gamma", 2),
                ("Total for Beta", 1),
                ("Total for Alpha", 0),
                ("TOTAL", 0),
            ],
        )

    def test_totals_nest_and_include_every_descendant(self):
        self.assertEqual(self.rows["c-b.total"]["income"], "750.00")
        self.assertEqual(self.rows["c-a.total"]["income"], "1750.00")

    def test_the_grand_total_includes_the_grandchild(self):
        self.assertEqual(self.rows["total"]["income"], "1750.00")


class MalformedHierarchyTests(TestCase):
    """`Customer.parent` has no self-reference or cycle guard at any layer, so
    the report must degrade rather than lose figures."""

    def test_a_self_parented_customer_still_appears_and_counts(self):
        report = run(
            {("c-a", SALES): "500.00", ("c-b", SALES): "100.00"},
            parents={"c-a": "c-a", "c-b": None},
            names={"c-a": "Alpha", "c-b": "Beta"},
        )
        self.assertEqual(
            [row["label"] for row in report["rows"]], ["Alpha", "Beta", "TOTAL"]
        )
        self.assertEqual(rows_by_key(report)["total"]["income"], "600.00")

    def test_a_parent_cycle_does_not_empty_the_report(self):
        report = run(
            {("c-a", SALES): "1000.00", ("c-b", SALES): "500.00"},
            parents={"c-a": "c-b", "c-b": "c-a"},
            names={"c-a": "Alpha", "c-b": "Beta"},
        )
        labels = [row["label"] for row in report["rows"]]
        self.assertIn("Alpha", labels)
        self.assertIn("Beta", labels)
        self.assertEqual(rows_by_key(report)["total"]["income"], "1500.00")

    def test_a_child_whose_parent_has_no_activity_stays_a_root(self):
        # Otherwise the child would vanish: it would be filed under a parent
        # that never gets rendered.
        roots, children = group_by_parent({"kid"}, {"kid": "absent-parent"})
        self.assertEqual(roots, ["kid"])
        self.assertEqual(children, {})


class CustomerTreeTests(TestCase):
    def test_sort_puts_not_specified_last_case_insensitively(self):
        names = {"a": "zebra", "b": "Apple", UNASSIGNED_KEY: "Not specified"}
        self.assertEqual(
            sorted(names, key=lambda key: sort_key(key, names)),
            ["b", "a", UNASSIGNED_KEY],
        )

    def test_tree_rows_walks_an_arbitrary_depth(self):
        names = {"a": "A", "b": "B", "c": "C", "d": "D"}
        parents = {"a": None, "b": "a", "c": "b", "d": "c"}
        walked = list(tree_rows(set(names), parents, names))
        depths = [(key, depth) for key, depth, sub in walked if sub is None]
        self.assertEqual(depths, [("a", 0), ("b", 1), ("c", 2), ("d", 3)])
        # Every node but the leaf gets a nested total covering its subtree.
        totals = {key: set(sub) for key, _, sub in walked if sub is not None}
        self.assertEqual(totals["a"], {"a", "b", "c", "d"})
        self.assertEqual(totals["c"], {"c", "d"})
        self.assertNotIn("d", totals)
