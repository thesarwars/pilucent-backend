"""Tests for statutory PayrollTaxConfig storage, assembly, and seeding."""

import unittest

from django.core.management import call_command
from django.test import TestCase

from payrollio.choicess import PayrollTaxConfigStatusChoices
from payrollio.models import PayrollTaxConfig
from payrollio.django_rest.helpers.tax_config import (
    assemble_tax_config,
    normalize_jurisdiction,
    parse_states_param,
    resolve_year,
)


class TaxConfigHelperTests(unittest.TestCase):
    def test_normalize_jurisdiction(self):
        self.assertEqual(normalize_jurisdiction("federal"), "FEDERAL")
        self.assertEqual(normalize_jurisdiction("FEDERAL"), "FEDERAL")
        self.assertEqual(normalize_jurisdiction("ca"), "CA")
        self.assertEqual(normalize_jurisdiction("California"), "CA")
        self.assertIsNone(normalize_jurisdiction("XX"))
        self.assertIsNone(normalize_jurisdiction(None))

    def test_parse_states_param(self):
        self.assertEqual(parse_states_param("CA,NY"), {"CA", "NY"})
        self.assertEqual(parse_states_param("ca, New York "), {"CA", "NY"})
        # garbage dropped, dupes collapsed, FEDERAL never leaks in
        self.assertEqual(parse_states_param("CA,XX,ca,FEDERAL"), {"CA"})
        self.assertEqual(parse_states_param(""), set())
        self.assertEqual(parse_states_param(None), set())

    def test_resolve_year(self):
        self.assertEqual(resolve_year("2026"), 2026)
        self.assertEqual(resolve_year(2027), 2027)
        # 'current'/None resolve to a real year (don't pin the value here)
        self.assertIsInstance(resolve_year("current"), int)
        self.assertIsInstance(resolve_year(None), int)


class AssembleTaxConfigTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def row(jur, status=PayrollTaxConfigStatusChoices.PUBLISHED, ver=1, year=2026):
            return PayrollTaxConfig.objects.create(
                year=year,
                jurisdiction=jur,
                status=status,
                version=ver,
                data={"marker": jur},
            )

        row("FEDERAL", ver=3)
        row("NY", ver=2)
        row("MN")
        row("CA", status=PayrollTaxConfigStatusChoices.DRAFT)  # not published

    def test_returns_only_requested_states_plus_federal(self):
        result = assemble_tax_config(2026, {"NY"})
        self.assertEqual(sorted(result["data"].keys()), ["federal", "ny", "year"])
        # MN was not requested -> absent even though it is published
        self.assertNotIn("mn", result["data"])
        self.assertEqual(result["data"]["ny"], {"marker": "NY"})
        self.assertEqual(result["versions"], {"FEDERAL": 3, "NY": 2})
        self.assertEqual(result["unavailable"], [])

    def test_federal_always_included_even_with_no_states(self):
        result = assemble_tax_config(2026, set())
        self.assertEqual(sorted(result["data"].keys()), ["federal", "year"])
        self.assertEqual(result["versions"], {"FEDERAL": 3})

    def test_unpublished_state_reported_unavailable(self):
        result = assemble_tax_config(2026, {"CA"})
        self.assertNotIn("ca", result["data"])  # CA is DRAFT
        self.assertEqual(result["unavailable"], ["CA"])
        self.assertIn("federal", result["data"])

    def test_missing_year_reports_all_unavailable(self):
        result = assemble_tax_config(2030, {"NY"})
        self.assertEqual(result["data"], {"year": 2030})
        self.assertEqual(sorted(result["unavailable"]), ["FEDERAL", "NY"])

    def test_multiple_states_one_assembly(self):
        result = assemble_tax_config(2026, {"NY", "MN"})
        self.assertEqual(sorted(result["data"].keys()), ["federal", "mn", "ny", "year"])


class SeedCommandTests(TestCase):
    def test_seed_creates_and_is_idempotent(self):
        call_command("seed_payroll_tax_config", "--year", "2026", "--publish")
        jurisdictions = set(
            PayrollTaxConfig.objects.filter(year=2026).values_list(
                "jurisdiction", flat=True
            )
        )
        self.assertEqual(jurisdictions, {"FEDERAL", "NY", "MN"})
        federal = PayrollTaxConfig.objects.get(year=2026, jurisdiction="FEDERAL")
        self.assertEqual(federal.status, PayrollTaxConfigStatusChoices.PUBLISHED)
        self.assertEqual(federal.version, 1)
        self.assertEqual(federal.data["ssRate"], 0.062)
        # open bracket bound stored as null (not Infinity)
        self.assertIsNone(federal.data["brackets"]["single"][-1][1])

        # Re-run: unchanged data must not bump the version.
        call_command("seed_payroll_tax_config", "--year", "2026", "--publish")
        federal.refresh_from_db()
        self.assertEqual(federal.version, 1)

    def test_seeded_config_assembles_for_requested_state(self):
        call_command("seed_payroll_tax_config", "--year", "2026", "--publish")
        result = assemble_tax_config(2026, {"NY"})
        self.assertEqual(result["data"]["ny"]["uiWageBase"], 17600)
        self.assertEqual(result["data"]["federal"]["ssWageBase"], 184500)
        self.assertNotIn("mn", result["data"])  # not requested
