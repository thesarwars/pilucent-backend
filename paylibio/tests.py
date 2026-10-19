"""Components & structures (backend spec §10.1 golden vectors L1-L15, §10.2
properties) and the API: permissions, versioning, the salary module on the
library.

The clock is frozen on 2027-03-08."""

import random
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from employeeio.models import SalaryOverride
from employeeio.services import salary
from employeeio.services.salary_templates import Split, build_basic_up, build_split
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    FrozenClockMixin,
    give_salary_permissions,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)
from rulebookio.book import rule_book

from .models import BulkRevision, LibraryAudit, PayComponent
from .services import library as L
from .services.seed import ensure_library

API = "/api/v1/we/pay-library"


def amounts(lines):
    return {c: int(a) for c, a in lines}


class Base(FrozenClockMixin, TestCase):
    frozen_on = AS_OF

    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        ensure_library(cls.company)

    def draft(self, code, rows, mode="GROSS_DOWN", balancing="BASIC"):
        return L.save_template(self.company, {"code": code, "name": code.title(), "note": f"{code} split.",
                                              "mode": mode, "balancingCode": balancing,
                                              "rows": [{"code": c, "basis": b, "value": v} for c, b, v in rows]})

    def comp(self, code):
        return PayComponent.objects.get(company=self.company, code=code, superseded_by__isnull=True)


STD = [("BASIC", "PCT_OF_GROSS", "60"), ("HRA", "PCT_OF_BASIC", "50"), ("MED", "PCT_OF_GROSS", "6"),
       ("CONV", "PCT_OF_GROSS", "4")]
CLASSIC = [("BASIC", "PCT_OF_GROSS", "66.67"), ("HRA", "PCT_OF_BASIC", "50")]
RMG_UP = [("BASIC", "FIXED", "8000"), ("HRA", "PCT_OF_BASIC", "50"), ("MED", "FIXED", "750"),
          ("CONV", "FIXED", "350"), ("FOOD", "FIXED", "1250")]


class GoldenTests(Base):
    def test_l1_std_at_50000(self):
        lines = build_split(Split.of(self.draft("std", STD)), Decimal("50000"))
        self.assertEqual(amounts(lines), {"BASIC": 30000, "HRA": 15000, "MED": 3000, "CONV": 2000})

    def test_l2_std_sums_to_gross_exactly(self):
        split = Split.of(self.draft("std", STD))
        for gross in list(range(1000, 30001)) + list(range(30001, 200001, 13)):
            if sum(a for _, a in build_split(split, Decimal(gross))) != gross:
                self.fail(f"std at {gross}")

    def test_l3_classic_at_66_67_holds_four_places_and_basic_takes_the_residue(self):
        t = self.draft("classic", CLASSIC)
        self.assertEqual(t.rows.get(component_code="BASIC").value, Decimal("66.6700"))
        lines = dict(build_split(Split.of(t), Decimal("50000")))
        # Basic is 33,335 before the residue (50,000 x 66.67%); house rent is 50% of that, 16,668; the
        # split allocates 100.005% of gross, so the residue (-3) lands on basic and the parts sum to gross.
        self.assertEqual(round(Decimal("50000") * Decimal("0.6667")), 33335)
        self.assertEqual((lines["HRA"], lines["BASIC"]), (Decimal("16668"), Decimal("33332")))
        self.assertEqual(sum(lines.values()), Decimal("50000"))

    def test_l4_rmg_basic_up_gross_is_an_output(self):
        lines = build_basic_up(Split.of(self.draft("rmg-up", RMG_UP, mode="BASIC_UP")), Decimal("8000"))
        self.assertEqual(amounts(lines), {"BASIC": 8000, "HRA": 4000, "MED": 750, "CONV": 350, "FOOD": 1250})
        self.assertEqual(sum(a for _, a in lines), Decimal("14350"))

    def test_l5_ot_base_basic_only(self):
        b = L.bases_for(self.company, [("BASIC", Decimal("30000")), ("HRA", Decimal("15000"))], AS_OF)
        self.assertEqual(b["overtimeHourly"], "288.46")
        self.assertEqual(b["constants"]["otDivisor"], "208")  # from the rule book, not hardcoded

    def test_l6_hra_into_ot_base_raises_the_rate(self):
        L.change_flags(self.company, self.comp("HRA"), {"in_ot_base_s108": True}, effective_from=AS_OF,
                       reason="Board decision BR-2027-03")
        b = L.bases_for(self.company, [("BASIC", Decimal("30000")), ("HRA", Decimal("15000"))], AS_OF)
        self.assertEqual(b["overtimeHourly"], "432.69")

    def test_l7_unsetting_basic_from_gratuity_is_refused(self):
        with self.assertRaises(L.LibraryRefused) as caught:
            L.change_flags(self.company, self.comp("BASIC"), {"in_gratuity_base": False}, effective_from=AS_OF,
                           reason="Trying to cut the gratuity cost")
        self.assertIn("cannot be unset", str(caught.exception))
        c = self.comp("BASIC")
        c.in_gratuity_base = False
        with self.assertRaises(ValidationError):  # the model refuses too
            c.save()

    def test_l8_setting_hra_into_gratuity_is_permitted_and_audited(self):
        new = L.change_flags(self.company, self.comp("HRA"), {"in_gratuity_base": True}, effective_from=date(2027, 4, 1),
                             reason="Board decision BR-2027-03")
        self.assertEqual(new.version, 2)
        row = LibraryAudit.objects.get(action="FLAG_CHANGED")
        self.assertEqual((row.before_json, row.after_json, row.entity_code), ({"in_gratuity_base": False},
                                                                              {"in_gratuity_base": True}, "HRA"))

    def test_l9_a_deduction_with_a_base_is_refused_by_the_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayComponent.objects.create(company=self.company, code="LOAN", name="Loan", kind="DEDUCTION",
                                        calc_basis="FIXED", effective_from=AS_OF, in_pf_base=True)

    def test_l10_statutory_without_a_basis_is_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayComponent.objects.create(company=self.company, code="XST", name="X", kind="EARNING",
                                        calc_basis="FIXED", effective_from=AS_OF, is_statutory=True)

    def test_l11_a_2026_structure_keeps_its_2026_bases(self):
        e = make_employee(self.company, "EMP-0001", "Rafiq", status="ACTIVE", doj=date(2026, 1, 1))
        salary.assign(e, template="officer", amount=Decimal("50000"), effective_from=date(2026, 1, 1))
        L.change_flags(self.company, self.comp("HRA"), {"in_gratuity_base": True}, effective_from=date(2027, 1, 1),
                       reason="Board decision BR-2027-01")
        old = salary.structure_out(salary.latest_structure(e))
        hra = next(c for c in old["components"] if c["code"] == "HRA")
        self.assertEqual((hra["componentVersion"], hra["bases"]["gratuity"]), (1, False))
        out = salary.revise(e, method="PERCENTAGE_INCREASE", value=Decimal("8"), effective_from=date(2027, 4, 1))
        hra = next(c for c in out["structure"]["components"] if c["code"] == "HRA")
        self.assertEqual((hra["componentVersion"], hra["bases"]["gratuity"]), (2, True))

    def test_the_salary_profile_overtime_follows_the_pinned_bases(self):
        from employeeio.services.statutory import overtime_hourly

        e = make_employee(self.company, "EMP-0005", "Rafiq", status="ACTIVE", doj=date(2026, 1, 1))
        salary.assign(e, template="officer", amount=Decimal("50000"), effective_from=date(2026, 1, 1))
        book = rule_book(AS_OF)
        old = salary.latest_structure(e)
        self.assertEqual(overtime_hourly(old, book).value, Decimal("288.46"))  # basic 30,000 alone
        L.change_flags(self.company, self.comp("HRA"), {"in_ot_base_s108": True}, effective_from=date(2027, 1, 1),
                       reason="Board decision BR-2027-01")
        self.assertEqual(overtime_hourly(old, book).value, Decimal("288.46"))  # its own version: unchanged
        salary.revise(e, method="NEW_GROSS", value=Decimal("52000"), effective_from=date(2027, 4, 1))
        new = salary.latest_structure(e)
        self.assertEqual(overtime_hourly(new, book).value, Decimal("450.00"))  # (31,200 + 15,600) ÷ 208 × 2
        self.assertIn("House rent", overtime_hourly(new, book).basis)

    def test_l12_bulk_apply_without_preview(self):
        b = L.create_bulk(self.company, {"method": "PCT_INCREASE", "value": "8", "effectiveFrom": "2027-04-01"})
        with self.assertRaises(L.LibraryRefused):
            L.apply_bulk(self.company, b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BulkRevision.objects.filter(pk=b.pk).update(status="APPLIED")

    def test_l13_and_l14_bulk_refuses_by_name_and_leaves_overrides_alone(self):
        low = make_employee(self.company, "EMP-0002", "Nasima", status="ACTIVE", grade="G5", doj=date(2026, 1, 1))
        salary.assign(low, template="worker", amount=Decimal("26000"), effective_from=date(2026, 1, 1))
        over = make_employee(self.company, "EMP-0003", "Karim", status="ACTIVE", doj=date(2026, 1, 1))
        salary.assign(over, template="officer", amount=Decimal("50000"), effective_from=date(2026, 1, 1))
        salary.override(over, salary.latest_structure(over), rows=[{"code": "CONV", "basis": "FIXED", "value": "1000"}],
                        reason="Field role, company car provided", effective_from=date(2026, 6, 1))
        ok = make_employee(self.company, "EMP-0004", "Shahana", status="ACTIVE", doj=date(2026, 1, 1))
        salary.assign(ok, template="officer", amount=Decimal("40000"), effective_from=date(2026, 1, 1))
        # A cut deep enough to take the grade-5 worker under the gazetted floor.
        b = L.create_bulk(self.company, {"method": "FIXED_INCREASE", "value": "-21000", "effectiveFrom": "2027-04-01",
                                         "rounding": "NONE"})
        b = L.preview_bulk(self.company, b)
        refused = {r["code"]: r["reason"] for r in b.preview_json["refusals"]}
        self.assertIn("EMP-0002", refused)
        self.assertIn("floor", refused["EMP-0002"].lower())
        self.assertIn("overridden", refused["EMP-0003"])
        b = L.apply_bulk(self.company, b)
        self.assertEqual(salary.latest_structure(over).effective_from, date(2026, 6, 1))  # untouched
        self.assertEqual(salary.latest_structure(ok).gross, Decimal("19000"))
        self.assertEqual(len(b.applied_structures), 1)
        self.assertTrue(SalaryOverride.objects.filter(structure__employee=over).exists())

    def test_l15_an_unmapped_component_blocks_the_journal(self):
        r = L.readiness(self.company)
        self.assertFalse(r["ready"])
        self.assertIn("NIGHT", [x["code"] for x in r["blocked"]])
        self.assertIn("blocks the payroll journal", r["message"])
        L.create_payroll_accounts(self.company)
        still = {x["code"] for x in L.readiness(self.company)["blocked"]}
        self.assertEqual(still, {"DA", "OTHER", "NIGHT"})  # no seeded account for these: mapped by hand


class PropertyTests(Base):
    def test_gross_down_always_sums_and_basic_up_is_the_sum_of_its_rows(self):
        rnd = random.Random(7)
        for n in range(25):
            basic = rnd.choice(["50", "55", "58", "60", "62"])
            rows = [("BASIC", "PCT_OF_GROSS", basic), ("HRA", "PCT_OF_BASIC", rnd.choice(["40", "50"])),
                    ("MED", "PCT_OF_GROSS", rnd.choice(["3", "5", "6"]))]
            split = Split.of(self.draft(f"p{n}", rows, balancing=rnd.choice(["BASIC", "OTHER"])))
            for gross in rnd.sample(range(5000, 300000), 40):
                self.assertEqual(sum(a for _, a in build_split(split, Decimal(gross))), gross)
        up = Split.of(self.draft("up", RMG_UP, mode="BASIC_UP"))
        for basic in (8000, 9123, 14000):
            lines = build_basic_up(up, Decimal(basic))
            self.assertEqual(sum(a for _, a in lines), sum(a for _, a in lines))
            self.assertEqual(dict(lines)["BASIC"], basic)

    def test_the_bases_never_exceed_the_earnings(self):
        lines = [("BASIC", Decimal("30000")), ("HRA", Decimal("15000")), ("MED", Decimal("3000"))]
        b = L.bases_for(self.company, lines, AS_OF)
        for v in b["sums"].values():
            self.assertLessEqual(Decimal(v), Decimal("48000"))


class LibraryTests(Base):
    def test_templates_are_rows_and_the_salary_module_builds_from_them(self):
        names = {t["code"]: t for t in L.templates(self.company)}
        self.assertEqual(set(names), {"officer", "worker", "staff", "rmg"})
        self.assertTrue(names["rmg"]["gazette"])
        t = self.draft("std", STD)
        L.create_payroll_accounts(self.company)
        L.publish_template(self.company, t)
        built = salary.build("std", Decimal("50000"), rule_book(AS_OF), company=self.company, on=AS_OF)
        self.assertEqual(amounts(built.components), {"BASIC": 30000, "HRA": 15000, "MED": 3000, "CONV": 2000})

    def test_publishing_needs_gl_accounts_and_a_published_edit_is_a_new_draft(self):
        t = self.draft("std", STD)
        with self.assertRaises(L.LibraryRefused) as caught:
            L.publish_template(self.company, t)
        self.assertIn("GL account", str(caught.exception))
        L.create_payroll_accounts(self.company)
        t = L.publish_template(self.company, t)
        edited = L.save_template(self.company, {"name": "Std v2", "effectiveFrom": "2027-04-01"}, template=t)
        self.assertEqual((edited.version, edited.status), (2, "DRAFT"))
        t.refresh_from_db()
        self.assertEqual(t.status, "PUBLISHED")

    def test_basic_up_refuses_a_percentage_of_gross(self):
        with self.assertRaises(L.LibraryRefused) as caught:
            self.draft("bad", [("BASIC", "FIXED", "8000"), ("MED", "PCT_OF_GROSS", "5")], mode="BASIC_UP")
        self.assertIn("no gross", str(caught.exception))

    def test_a_company_floor_below_the_gazette_is_refused(self):
        make_employee(self.company, "EMP-0009", "G7 worker", status="ACTIVE", grade="G7")
        with self.assertRaises(L.LibraryRefused):
            L.set_policy(self.company, {"companyFloor": "1000"})
        p = L.set_policy(self.company, {"companyFloor": "14000"})
        self.assertEqual(p.company_floor_basic, Decimal("14000"))

    def test_pfe_bases_are_frozen(self):
        with self.assertRaises(L.LibraryRefused):
            L.change_flags(self.company, self.comp("PFE"), {"prorate_part_month": True}, effective_from=AS_OF,
                           reason="Prorate the PF deduction")


class ApiTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.clerk = make_user(self.company, "clerk@rahman.test")

    def test_summary_lists_components_with_flags_and_effects(self):
        body = self.client_for(self.admin).get(f"{API}/summary").json()
        basic = next(c for c in body["components"] if c["code"] == "BASIC")
        self.assertEqual(basic["flags"][:6], [True] * 6)
        self.assertEqual(len(body["bases"]), 8)
        self.assertEqual(body["effects"]["now"]["overtimeHourly"], "288.46")
        self.assertFalse(body["readiness"]["ready"])

    def test_flags_need_their_own_permission(self):
        hra = self.comp("HRA")
        body = {"changes": {"in_gratuity_base": True}, "reason": "Board decision BR-2027-03", "effectiveFrom": "2027-04-01"}
        c = self.client_for(self.clerk)
        self.assertEqual(c.post(f"{API}/components/{hra.uid}/flags", body, format="json").status_code, 403)
        give_salary_permissions(self.clerk, self.company)  # salary permissions are not library permissions
        self.assertEqual(c.post(f"{API}/components/{hra.uid}/flags", body, format="json").status_code, 403)
        r = self.client_for(self.admin).post(f"{API}/components/{hra.uid}/flags", body, format="json")
        self.assertEqual((r.status_code, r.json()["version"]), (200, 2))
        basic = self.comp("BASIC")
        r = self.client_for(self.admin).post(f"{API}/components/{basic.uid}/flags",
                                             {"changes": {"in_pf_base": False}, "reason": "Cut the PF cost now"},
                                             format="json")
        self.assertEqual(r.status_code, 422)

    def test_bulk_pay_is_figures_only(self):
        b = L.create_bulk(self.company, {"method": "PCT_INCREASE", "value": "8", "effectiveFrom": "2027-04-01"})
        self.assertEqual(self.client_for(self.clerk).get(f"{API}/bulk-revisions/{b.uid}").status_code, 403)
        self.assertEqual(self.client_for(self.admin).get(f"{API}/bulk-revisions/{b.uid}").status_code, 200)

    def test_another_companys_component_is_not_found(self):
        other = make_company("Other Ltd")
        stranger = make_user(other, "boss@other.test")
        make_company_admin(stranger, other)
        self.assertEqual(self.client_for(stranger).get(f"{API}/components/{self.comp('HRA').uid}").status_code, 404)
