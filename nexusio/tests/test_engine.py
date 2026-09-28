"""Unit tests for the pure nexus calculation engine (no DB)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from nexusio.choices import NexusStatusChoices
from nexusio.services import engine


def rule(**overrides):
    defaults = dict(
        state_code="XX",
        sales_threshold=Decimal("100000"),
        txn_threshold=200,
        combination_logic="OR",
        includable_sales_basis="GROSS",
        measurement_period_type="CURRENT_OR_PREVIOUS_YEAR",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def agg(gross=0, taxable=0, count=0):
    return {"gross": Decimal(str(gross)), "taxable": Decimal(str(taxable)), "count": count}


class ResolveWindowTests(SimpleTestCase):
    today = date(2026, 7, 7)

    def test_current_year(self):
        self.assertEqual(
            engine.resolve_windows("CURRENT_YEAR", self.today),
            [(date(2026, 1, 1), self.today)],
        )

    def test_previous_year(self):
        self.assertEqual(
            engine.resolve_windows("PREVIOUS_YEAR", self.today),
            [(date(2025, 1, 1), date(2025, 12, 31))],
        )

    def test_current_or_previous_year_is_two_separate_windows(self):
        # Two annual windows evaluated separately then OR'd — NOT one combined span.
        self.assertEqual(
            engine.resolve_windows("CURRENT_OR_PREVIOUS_YEAR", self.today),
            [
                (date(2025, 1, 1), date(2025, 12, 31)),
                (date(2026, 1, 1), self.today),
            ],
        )

    def test_trailing_12m(self):
        self.assertEqual(
            engine.resolve_windows("TRAILING_12M", self.today),
            [(date(2025, 7, 8), self.today)],
        )


class VerdictTests(SimpleTestCase):
    def test_sales_only_boundary_is_met(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None)
        self.assertTrue(engine.evaluate(agg(gross=100000), r)["met"])  # >= boundary
        self.assertFalse(engine.evaluate(agg(gross=99999.99), r)["met"])

    def test_sales_only_uses_taxable_basis(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None, includable_sales_basis="TAXABLE")
        # gross is over but taxable is under -> not met on taxable basis
        self.assertFalse(engine.evaluate(agg(gross=200000, taxable=50000), r)["met"])
        self.assertTrue(engine.evaluate(agg(gross=200000, taxable=100000), r)["met"])

    def test_or_either_test_triggers(self):
        r = rule(combination_logic="OR")
        self.assertTrue(engine.evaluate(agg(gross=50000, count=200), r)["met"])  # txn
        self.assertTrue(engine.evaluate(agg(gross=100000, count=5), r)["met"])  # sales
        self.assertFalse(engine.evaluate(agg(gross=50000, count=100), r)["met"])

    def test_and_requires_both_new_york_sticker_guard(self):
        # NY: $500k AND 100. 5,000 tiny orders = $40k -> NO nexus (the guard).
        ny = rule(combination_logic="AND", sales_threshold=Decimal("500000"), txn_threshold=100)
        self.assertFalse(engine.evaluate(agg(gross=40000, count=5000), ny)["met"])
        self.assertTrue(engine.evaluate(agg(gross=500000, count=100), ny)["met"])
        self.assertFalse(engine.evaluate(agg(gross=500000, count=99), ny)["met"])
        self.assertFalse(engine.evaluate(agg(gross=400000, count=200), ny)["met"])

    def test_none_never_met(self):
        r = rule(combination_logic="NONE", sales_threshold=None, txn_threshold=None)
        self.assertFalse(engine.evaluate(agg(gross=999999), r)["met"])


class StatusTests(SimpleTestCase):
    def test_none_is_not_applicable(self):
        r = rule(combination_logic="NONE", sales_threshold=None, txn_threshold=None)
        ev = engine.evaluate(agg(), r)
        self.assertEqual(engine.derive_status(ev, r), NexusStatusChoices.NOT_APPLICABLE)

    def test_registered_wins(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None)
        ev = engine.evaluate(agg(gross=100000), r)
        self.assertEqual(
            engine.derive_status(ev, r, registered=True), NexusStatusChoices.REGISTERED
        )

    def test_met(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None)
        ev = engine.evaluate(agg(gross=100000), r)
        self.assertEqual(engine.derive_status(ev, r), NexusStatusChoices.MET)

    def test_approaching_on_sales(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None)
        ev = engine.evaluate(agg(gross=85000), r)  # 85% >= 80%
        self.assertEqual(engine.derive_status(ev, r), NexusStatusChoices.APPROACHING)

    def test_not_approaching(self):
        r = rule(combination_logic="SALES_ONLY", txn_threshold=None)
        ev = engine.evaluate(agg(gross=50000), r)
        self.assertEqual(engine.derive_status(ev, r), NexusStatusChoices.NOT_APPROACHING)

    def test_or_state_approaching_on_txn(self):
        r = rule(combination_logic="OR")
        ev = engine.evaluate(agg(gross=10000, count=180), r)  # 90% of 200
        self.assertEqual(engine.derive_status(ev, r), NexusStatusChoices.APPROACHING)

    def test_and_state_high_txn_pct_does_not_approach(self):
        # AND state: a high txn count alone must not raise 'approaching'.
        ny = rule(combination_logic="AND", sales_threshold=Decimal("500000"), txn_threshold=100)
        ev = engine.evaluate(agg(gross=40000, count=95), ny)  # 95% txn, 8% sales
        self.assertEqual(engine.derive_status(ev, ny), NexusStatusChoices.NOT_APPROACHING)
