"""Payroll settings (docs/backend/payroll-settings-done.md §9): the golden
vectors, the resolution properties and the API.

S1 and S2 (proration) are in employeeio.tests_statutory, next to the
function they pin.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from employeeio.models import ProcessedPayrollPeriod, Site
from employeeio.services.sites import default_site
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    FrozenClockMixin,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)
from rulebookio.book import rule_book
from timekeepingio.models import HolidayCalendar, HolidayCalendarDay

from .models import PayrollElection, SettingsAudit, SettingsEvent, StatutoryScheme
from .services import ops as S
from .services.calendar import Calendar, statutory_deadline
from .services.consequence import preview
from .services.resolve import (
    ElectionUnanswered,
    Hypothetical,
    election,
    elections_for,
    gratuity_base,
    month_hours,
    overtime_base,
    round_line,
)
from .test_support import answer_elections, constitute_pf, join, set_election

BASE = "/api/v1/we/payroll-settings"


def publish_calendar(site, year, weekly=("5",), festivals=()):
    cal = HolidayCalendar.objects.create(company=site.company, site=site, calendar_year=year, status="PUBLISHED",
                                         weekly_pattern={d: 1 for d in weekly})
    for d in festivals:
        HolidayCalendarDay.objects.create(calendar=cal, holiday_date=d, name="Festival", kind="FESTIVAL_HOLIDAY")
    return cal


class SettingsCase(FrozenClockMixin, TestCase):
    elections = True

    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments", elections=cls.elections)
        cls.site = default_site(cls.company)
        cls.alice = make_user(cls.company, "alice@rahman.test")
        cls.bob = make_user(cls.company, "bob@rahman.test")
        for u in (cls.alice, cls.bob):
            make_company_admin(u, cls.company)

    def setUp(self):
        super().setUp()
        self.book = rule_book(AS_OF)

    def worker(self, code, gross, doj=date(2020, 1, 1), **fields):
        e = make_employee(self.company, code, status="ACTIVE", doj=doj, classification="WORKER",
                          establishment="FACTORY", **fields)
        give_structure(e, gross, effective_from=doj)
        return e


# ================================================================ golden vectors


class OvertimeVectors(SettingsCase):
    def setUp(self):
        super().setUp()
        self.e = self.worker("W-1", 50000)
        self.s = self.e.salary_structures.first() if hasattr(self.e, "salary_structures") else None
        from employeeio.services.salary import structure_in_force

        self.s = structure_in_force(self.e, AS_OF)

    def test_s3_basic_plus_da_with_no_da_is_basic(self):
        base, codes, _ = overtime_base(self.s, Hypothetical("overtime_base", "BASIC_PLUS_DA", {}))
        self.assertEqual(base, self.s.basic)
        self.assertNotIn("DA", codes)

    def test_s4_gross_is_about_two_thirds_above_basic(self):
        basic, _, _ = overtime_base(self.s, Hypothetical("overtime_base", "BASIC_PLUS_DA", {}))
        gross, _, _ = overtime_base(self.s, Hypothetical("overtime_base", "GROSS", {}))
        self.assertEqual(gross, Decimal("50000"))
        self.assertAlmostEqual(float(gross / basic - 1), 0.667, places=2)

    def test_s5_240_hours_is_13_percent_lower_than_208(self):
        h208 = month_hours(Hypothetical("overtime_base", "GROSS", {}), self.book)
        h240 = month_hours(Hypothetical("overtime_base", "GROSS", {}, 240), self.book)
        self.assertEqual(h208, 208)
        self.assertAlmostEqual(float(1 - h208 / h240), 0.133, places=3)

    def test_custom_base_sums_the_named_components(self):
        base, codes, _ = overtime_base(self.s, Hypothetical("overtime_base", "CUSTOM", {"components": ["BASIC", "HRA"]}))
        self.assertEqual(base, self.s.basic + self.s.component_amount("HRA"))

    def test_unanswered_overtime_base_refuses(self):
        set_election(self.company, "overtime_base", "GROSS", on=date(2030, 1, 1))
        PayrollElection.objects.filter(company=self.company, election_key="overtime_base").update(status="REJECTED")
        with self.assertRaises(ElectionUnanswered) as ctx:
            overtime_base(self.s, election(self.company, "overtime_base", AS_OF))
        self.assertIn("s.108", ctx.exception.message)


class GratuityVectors(SettingsCase):
    def test_s6_days_per_year_step_up_past_the_breakpoint(self):
        from employeeio.services.statutory import gratuity_days

        # The rule book: exactly ten years still attracts 30 days; above it, 45.
        self.assertEqual((gratuity_days(9, self.book), gratuity_days(10, self.book), gratuity_days(11, self.book)),
                         (30, 30, 45))

    def test_gratuity_basis_is_the_election(self):
        from employeeio.services.salary import structure_in_force

        e = self.worker("W-2", 50000)
        s = structure_in_force(e, AS_OF)
        self.assertEqual(gratuity_base(s, election(self.company, "gratuity_basis", AS_OF))[0], s.basic)
        set_election(self.company, "gratuity_basis", "GROSS", on=date(2027, 1, 1))
        self.assertEqual(gratuity_base(s, election(self.company, "gratuity_basis", AS_OF))[0], Decimal("50000"))
        # The period before the change keeps resolving under the old basis.
        self.assertEqual(gratuity_base(s, election(self.company, "gratuity_basis", date(2026, 12, 31)))[0], s.basic)


class LeaveVector(SettingsCase):
    def test_s7_counting_weekly_holidays_adds_52_days(self):
        publish_calendar(self.site, 2026)  # 52 Fridays in 2026
        for i in range(3):
            self.worker(f"W-{i}", 15000)
        out = preview(self.company, "days_worked_basis", None, {"weekly": True}, on=date(2026, 10, 1))
        weekly = next(r for r in out["options"] if r["flag"] == "weekly")
        self.assertEqual(weekly["numeratorDays"], 52)
        # About three more leave days a year per worker at the factory ratio of 1 in 18.
        self.assertEqual(weekly["companyLeaveDays"], 3 * 3)
        self.assertEqual(out["proposed"]["numerator"] - out["current"]["numerator"], 52)


class BandVectors(SettingsCase):
    def test_s8_a_gap_at_month_six_is_refused(self):
        bands = [{"fromMonths": 0, "toMonths": 5, "pct": 0}, {"fromMonths": 7, "toMonths": 11, "pct": 50}]
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.validate_bands(bands)
        self.assertIn("month 7", str(ctx.exception))

    def test_s9_bands_must_reach_eleven(self):
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.validate_bands([{"fromMonths": 0, "toMonths": 9, "pct": 50}])
        self.assertIn("ends at 9", str(ctx.exception))

    def test_good_bands_are_stored_as_strings(self):
        from .choices import DEFAULT_BANDS

        self.assertEqual([b["pct"] for b in S.validate_bands(DEFAULT_BANDS)], ["0", "25", "50", "75"])


class RoundingVector(TestCase):
    def test_s10_never_below_the_paisa_figure(self):
        for x in ("1234.00", "1234.004", "1234.5", "1235.01", "9.99", "0.004", "100000.40"):
            exact = round_line(x, "PAISA")
            for mode in ("TAKA", "TEN_TAKA"):
                with self.subTest(x=x, mode=mode):
                    self.assertGreaterEqual(round_line(x, mode), exact)
        self.assertEqual(round_line("1234", "TEN_TAKA"), 1240)
        self.assertEqual(round_line("1230", "TEN_TAKA"), 1230)
        self.assertEqual(round_line("1234.20", "TAKA"), 1235)
        self.assertEqual(round_line("1234.005", "PAISA"), Decimal("1234.01"))


class ReadinessVectors(SettingsCase):
    elections = False

    def test_s11_unanswered_gratuity_basis_refuses_the_run_with_the_citation(self):
        S.ensure_settings(self.company)
        out = S.readiness(self.company, period=date(2027, 3, 1))
        self.assertFalse(out["runnable"])
        g = next(b for b in out["blockers"] if b.get("key") == "gratuity_basis")
        self.assertEqual(g["citation"], "Bangladesh Labour Act 2006, s.2(10)")
        unanswered = {b["key"] for b in out["blockers"] if b["kind"] == "UNANSWERED_ELECTION"}
        self.assertEqual(unanswered, {"overtime_base", "proration_method", "gratuity_basis", "festival_bonus_policy"})
        with self.assertRaises(S.SettingsRefused):
            S.assert_runnable(self.company, period=date(2027, 3, 1))
        self.assertTrue(SettingsEvent.objects.filter(company=self.company, name="SettingsBlockedRun").exists())

    def test_the_three_presets_are_answered_from_the_start(self):
        r = elections_for(self.company, None, AS_OF)
        self.assertEqual(r["rounding_mode"].value, "TAKA")
        self.assertEqual(r["balancing_component"].value, "BASIC")
        self.assertTrue(r["days_worked_basis"].data["present"])
        self.assertEqual(r["rounding_mode"].row.source, "SEEDED")
        self.assertFalse(r["proration_method"].answered)

    def test_s12_an_applying_scheme_without_an_expense_account_blocks_the_journal(self):
        S.ensure_settings(self.company)
        S.update_scheme(self.company, "WPPF", {"applies": True, "reason": "Profit above the threshold this year"})
        out = S.readiness(self.company)
        self.assertIn("WPPF", [b.get("scheme") for b in out["blockers"] if b["kind"] == "UNMAPPED_SCHEME"])
        S.create_scheme_accounts(self.company, ["WPPF"])
        out = S.readiness(self.company)
        self.assertNotIn("WPPF", [b.get("scheme") for b in out["blockers"] if b["kind"] == "UNMAPPED_SCHEME"])


class SupersedeVectors(SettingsCase):
    elections = False

    def setUp(self):
        super().setUp()
        self.first = S.elect(self.company, "proration_method", {"value": "CALENDAR_DAYS",
                                                                "effectiveFrom": "2026-07-01"}, user=self.alice)

    def test_a_first_election_is_in_force_at_once(self):
        self.assertEqual(self.first.status, "ACTIVE")
        self.assertEqual(self.first.statutory_citation, "Bangladesh Labour Rules 2015, Rule 111 · company service rules")
        self.assertEqual(election(self.company, "proration_method", AS_OF).value, "CALENDAR_DAYS")

    def test_s13_superseding_without_a_reason_is_refused(self):
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.elect(self.company, "proration_method", {"value": "FIXED_30", "effectiveFrom": "2027-04-01"},
                    user=self.alice)
        self.assertIn("reason", ctx.exception.errors)

    def test_s14_the_proposer_cannot_approve(self):
        p = S.elect(self.company, "proration_method", {"value": "FIXED_30", "effectiveFrom": "2027-04-01",
                                                       "reason": "Align with the group service rules"}, user=self.alice)
        self.assertEqual(p.status, "DRAFT")
        self.assertIsNotNone(p.impact_json)
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.approve(self.company, p, user=self.alice)
        self.assertEqual(ctx.exception.status, 403)
        S.approve(self.company, p, user=self.bob)
        self.first.refresh_from_db()
        self.assertEqual((self.first.status, self.first.effective_to), ("SUPERSEDED", date(2027, 3, 31)))
        self.assertEqual(election(self.company, "proration_method", date(2027, 3, 31)).value, "CALENDAR_DAYS")
        self.assertEqual(election(self.company, "proration_method", date(2027, 4, 1)).value, "FIXED_30")
        audit = SettingsAudit.objects.get(company=self.company, action="SUPERSEDED")
        self.assertEqual((audit.decided_by, audit.approved_by), (self.alice, self.bob))
        self.assertIsNotNone(audit.impact_json)

    def test_a_second_proposal_waits_for_the_first(self):
        S.elect(self.company, "proration_method", {"value": "FIXED_30", "effectiveFrom": "2027-04-01",
                                                   "reason": "Align with the group service rules"}, user=self.alice)
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.elect(self.company, "proration_method", {"value": "WORKING_DAYS_26", "effectiveFrom": "2027-05-01",
                                                       "reason": "Second thoughts on the method"}, user=self.bob)
        self.assertEqual(ctx.exception.status, 409)

    def test_an_election_cannot_start_inside_the_one_in_force(self):
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.elect(self.company, "proration_method", {"value": "FIXED_30", "effectiveFrom": "2026-07-01",
                                                       "reason": "Same day as the current one"}, user=self.alice)
        self.assertEqual(ctx.exception.status, 409)

    def test_s15_backdating_into_a_processed_period_computes_the_restatement(self):
        for m in (1, 2, 3):
            ProcessedPayrollPeriod.objects.create(company=self.company, period=date(2027, m, 1),
                                                  processed_on=date(2027, m, 28))
        p = S.elect(self.company, "proration_method", {"value": "FIXED_30", "effectiveFrom": "2027-02-01",
                                                       "reason": "Correction: the rules said fixed 30"},
                    user=self.alice)
        S.approve(self.company, p, user=self.bob)
        ev = SettingsEvent.objects.get(company=self.company, name="ElectionBackdated")
        self.assertEqual(ev.payload["restate"], ["2027-02", "2027-03"])
        self.assertIn("citation", ev.payload)
        self.assertIn("ruleSetId", ev.payload)

    def test_an_election_is_never_updated_in_place(self):
        self.first.value_text = "FIXED_30"
        with self.assertRaises(ValidationError):
            self.first.save()
        with self.assertRaises(ValidationError):
            self.first.delete()

    def test_replacing_a_preset_needs_no_second_person(self):
        row = S.elect(self.company, "rounding_mode", {"value": "PAISA", "effectiveFrom": "2027-03-08"},
                      user=self.alice)
        self.assertEqual(row.status, "ACTIVE")
        again = S.elect(self.company, "rounding_mode", {"value": "TEN_TAKA", "effectiveFrom": "2027-04-01",
                                                        "reason": "Cash payments in ten-taka notes"},
                        user=self.alice)
        self.assertEqual(again.status, "DRAFT")

    def test_stable_for_a_fixed_date_whatever_comes_later(self):
        before = election(self.company, "proration_method", date(2026, 9, 1)).value
        for i, v in enumerate(("FIXED_30", "WORKING_DAYS_26", "ACTUAL_WORKING_DAYS")):
            p = S.elect(self.company, "proration_method", {"value": v, "effectiveFrom": f"2027-0{i + 4}-01",
                                                           "reason": "Trying each method in turn"}, user=self.alice)
            S.approve(self.company, p, user=self.bob)
            self.assertEqual(election(self.company, "proration_method", date(2026, 9, 1)).value, before)
        governing = PayrollElection.objects.filter(company=self.company, election_key="proration_method",
                                                   status__in=("ACTIVE", "SUPERSEDED")).order_by("effective_from")
        rows = list(governing)
        for a, b in zip(rows, rows[1:]):
            self.assertLess(a.effective_to, b.effective_from)  # never overlapping
        self.assertTrue(all(r.statutory_citation for r in rows))


class DeadlineVectors(SettingsCase):
    def test_s16_a_single_weekly_holiday_moves_the_s123_deadline(self):
        factory = default_site(self.company)
        office = Site.objects.create(company=self.company, code="HO", name="Head office")
        publish_calendar(factory, 2026, weekly=("5",))
        publish_calendar(office, 2026, weekly=("5", "6"))
        end = date(2026, 10, 31)  # a Saturday
        self.assertEqual(statutory_deadline(Calendar(factory), end), date(2026, 11, 8))
        self.assertEqual(statutory_deadline(Calendar(office), end), date(2026, 11, 9))

    def test_festival_holidays_are_not_working_days(self):
        publish_calendar(self.site, 2026, weekly=("5",), festivals=(date(2026, 11, 2),))
        self.assertEqual(statutory_deadline(Calendar(self.site), date(2026, 10, 31)), date(2026, 11, 9))

    def test_a_payment_day_after_the_deadline_is_refused_with_the_deadline(self):
        publish_calendar(self.site, 2027, weekly=("5", "6"))
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.set_schedule(self.company, {"frequency": "MONTHLY", "cutoffDay": 25, "paymentDay": 12,
                                          "effectiveFrom": "2027-03-01"})
        self.assertIn("s.123 deadline", str(ctx.exception))
        s, check = S.set_schedule(self.company, {"frequency": "MONTHLY", "cutoffDay": 25, "paymentDay": 7,
                                                 "effectiveFrom": "2027-03-01"})
        self.assertEqual(s.payment_day, 7)
        self.assertTrue(check["checked"])
        self.assertIn("2028-01", check["unchecked"])

    def test_no_published_calendar_refuses(self):
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.set_schedule(self.company, {"frequency": "MONTHLY", "cutoffDay": 25, "paymentDay": 7})
        self.assertEqual(ctx.exception.status, 409)


class PrecedenceVector(SettingsCase):
    def test_s17_a_site_election_overrides_the_company(self):
        office = Site.objects.create(company=self.company, code="HO", name="Head office")
        set_election(self.company, "overtime_base", "GROSS", site=office, on=date(2027, 1, 1))
        self.assertEqual(election(self.company, "overtime_base", AS_OF, office).value, "GROSS")
        self.assertEqual(election(self.company, "overtime_base", AS_OF, office).scope, "SITE")
        self.assertEqual(election(self.company, "overtime_base", AS_OF, self.site).value, "BASIC_PLUS_DA")
        self.assertEqual(election(self.company, "overtime_base", date(2026, 12, 1), office).value, "BASIC_PLUS_DA")


# ===================================================================== schemes


class SchemeTests(SettingsCase):
    def test_a_rate_change_supersedes_and_does_not_restate(self):
        constitute_pf(self.company)
        S.update_scheme(self.company, "PF", {"config": {"employerRatePct": "10"}, "effectiveFrom": "2027-04-01",
                                             "reason": "Board raised the employer share"})
        self.assertEqual(S.scheme_config(self.company, "PF", date(2027, 3, 31))["employerRatePct"], "8.0000")
        self.assertEqual(S.scheme_config(self.company, "PF", date(2027, 4, 1))["employerRatePct"], "10.0000")
        a = SettingsAudit.objects.get(company=self.company, action="RATE_CHANGED")
        self.assertEqual((a.from_value["config"]["employerRatePct"], a.to_value["config"]["employerRatePct"]),
                         ("8.0000", "10.0000"))
        self.assertTrue(SettingsEvent.objects.filter(company=self.company, name="SchemeRateChanged").exists())

    def test_insurance_has_no_liability_account(self):
        from accounts.models import ChartOfAccount

        acc = ChartOfAccount.objects.create(company=self.company, title="Insurance payable", code="2399",
                                            kind="LIABILITY", status="ACTIVE", currency="BDT")
        with self.assertRaises(S.SettingsRefused):
            S.map_scheme_gl(self.company, "GROUP_INSURANCE", liability=acc, fields=("liability",))

    def test_a_constituted_fund_needs_its_date(self):
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.update_scheme(self.company, "PF", {"applies": True, "config": {"constituted": True},
                                                 "reason": "Trust deed signed"})
        self.assertIn("constitutionDate", ctx.exception.errors)

    def test_participation_is_per_employee_and_follows_eligibility(self):
        constitute_pf(self.company, eligibility="ON_CONFIRMATION")
        probationer = self.worker("W-P", 15000, doj=date(2027, 1, 1), worker_category="PROBATIONER",
                                  probation_end=date(2027, 7, 1))
        with self.assertRaises(S.SettingsRefused) as ctx:
            S.enrol(self.company, probationer, "PF")
        self.assertIn("01/07/2027", str(ctx.exception))
        confirmed = self.worker("W-C", 15000, worker_category="PERMANENT")
        p = S.enrol(self.company, confirmed, "PF", on=date(2027, 1, 1))
        self.assertTrue(confirmed.statutory.pf_member)
        self.assertEqual(confirmed.statutory.pf_employer, Decimal("8.0000"))
        with self.assertRaises(S.SettingsRefused):
            S.opt_out(self.company, confirmed, "PF", reason="  ")
        S.opt_out(self.company, confirmed, "PF", reason="Moved to the group scheme abroad")
        p.refresh_from_db()
        self.assertEqual(p.opted_out_on, AS_OF)
        self.assertFalse(S.participation_in_force(confirmed, "PF", AS_OF))  # out from the opt-out day
        self.assertTrue(S.participation_in_force(confirmed, "PF", date(2027, 3, 7)))

    def test_auto_enrol_takes_only_the_eligible(self):
        constitute_pf(self.company, eligibility="AFTER_MONTHS", eligibilityMonths=6)
        self.worker("W-OLD", 15000, doj=date(2025, 1, 1))
        self.worker("W-NEW", 15000, doj=date(2027, 1, 1))
        out = S.auto_enrol(self.company)
        self.assertEqual([e["code"] for e in out["eligible"]], ["W-OLD"])
        S.auto_enrol(self.company, apply=True)
        self.assertEqual(S.auto_enrol(self.company)["eligible"], [])


# ===================================================================== preview


class PreviewTests(SettingsCase):
    def test_the_overtime_preview_is_the_roster_summed(self):
        for i in range(4):
            self.worker(f"W-{i}", 20000)
        out = preview(self.company, "overtime_base", "GROSS", {}, on=AS_OF, params={"assumedHours": 20})
        by = {o["value"]: Decimal(o["monthlyCost"]) for o in out["options"]}
        # 4 workers × 20 h × 2 × base ÷ 208
        self.assertEqual(by["GROSS"], Decimal(round(4 * 20 * 2 * 20000 / 208)))
        self.assertEqual(out["affectedEmployees"], 4)
        self.assertLessEqual(abs(Decimal(out["deltaAnnual"]) - (by["GROSS"] - by["BASIC_PLUS_DA"]) * 12), 12)
        self.assertEqual(out["org"]["headcount"], 4)
        self.assertTrue(any("assumed" in n for n in out["notes"]))

    def test_the_festival_preview_sits_on_the_under_one_year(self):
        self.worker("W-OLD", 20000, doj=date(2024, 1, 1))
        self.worker("W-NEW", 20000, doj=date(2026, 9, 8))  # six completed months
        out = preview(self.company, "festival_bonus_policy", "PRO_RATA", {}, on=AS_OF)
        self.assertEqual(out["affectedEmployees"], 1)
        by = {o["value"]: o["annualCost"] for o in out["options"]}
        self.assertEqual(by["NONE"], "0.00")
        self.assertEqual(Decimal(by["PRO_RATA"]) * 2, Decimal(by["FULL"]))

    def test_a_proposal_stores_the_preview_the_approver_sees(self):
        self.worker("W-1", 20000)
        p = S.elect(self.company, "overtime_base", {"value": "GROSS", "effectiveFrom": "2027-04-01",
                                                    "reason": "Union agreement 2027"}, user=self.alice)
        self.assertEqual(p.impact_json["electionKey"], "overtime_base")
        self.assertIn("monthlyCost", p.impact_json["proposed"])


# ========================================================================= API


class ApiTests(ApiMixin, SettingsCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.client_for(self.alice), self.client_for(self.bob)

    def test_summary(self):
        r = self.a.get(f"{BASE}/summary")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["answered"], body["total"]), (7, 7))
        self.assertEqual([e["key"] for e in body["elections"]][:2], ["overtime_base", "proration_method"])
        self.assertIn("headcount", body["org"])
        self.assertEqual(len(body["schemes"]), 4)

    def test_propose_then_approve_by_someone_else(self):
        r = self.a.post(f"{BASE}/elections/overtime_base", {"value": "GROSS", "effectiveFrom": "2027-04-01",
                                                            "reason": "Union agreement 2027"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "DRAFT")
        uid = r.json()["uid"]
        self.assertEqual(self.a.post(f"{BASE}/proposals/{uid}/approve", {}, format="json").status_code, 403)
        r = self.b.post(f"{BASE}/proposals/{uid}/approve", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["approvedBy"].lower(), "bob")
        log = self.a.get(f"{BASE}/changelog?key=overtime_base").json()["changelog"]
        self.assertEqual([x["action"] for x in log], ["SUPERSEDED", "PROPOSED"])

    def test_reject_needs_a_reason(self):
        uid = self.a.post(f"{BASE}/elections/rounding_mode", {"value": "PAISA", "effectiveFrom": "2027-04-01",
                                                              "reason": "Exact payslips"}, format="json").json()["uid"]
        self.assertEqual(self.b.post(f"{BASE}/proposals/{uid}/reject", {}, format="json").status_code, 422)
        r = self.b.post(f"{BASE}/proposals/{uid}/reject", {"reason": "Bank cannot pay paisa"}, format="json")
        self.assertEqual(r.json()["status"], "REJECTED")

    def test_preview_endpoint(self):
        self.worker("W-1", 20000)
        r = self.a.post(f"{BASE}/elections/proration_method/preview", {"value": "FIXED_30"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["example"]["daysInMonth"], 31)

    def test_bad_value_is_422(self):
        r = self.a.post(f"{BASE}/elections/overtime_base", {"value": "NET", "reason": "whatever it is"}, format="json")
        self.assertEqual(r.status_code, 422)

    def test_readiness_and_gl(self):
        r = self.a.get(f"{BASE}/readiness?period=2027-03")
        self.assertEqual(r.status_code, 200)
        kinds = {b["kind"] for b in r.json()["blockers"]}
        self.assertIn("UNMAPPED_SCHEME", kinds)  # gratuity applies, unmapped
        self.assertNotIn("UNANSWERED_ELECTION", kinds)
        r = self.a.post(f"{BASE}/schemes/accounts", {"codes": ["GRATUITY"]}, format="json")
        self.assertIn("5220 · Gratuity provision", r.json()["created"])
        self.assertNotIn("UNMAPPED_SCHEME", {b["kind"] for b in r.json()["readiness"]["blockers"]})

    def test_attendance_no_longer_writes_elections(self):
        r = self.a.patch("/api/v1/we/attendance/elections", {"overtimeBase": "GROSS"}, format="json")
        self.assertEqual(r.status_code, 410)

    def test_the_profile_toggle_opts_out_with_a_reason(self):
        e = self.worker("W-9", 15000)
        join(e, "GRATUITY", on=date(2020, 1, 1))
        url = f"/api/v1/we/employees/{e.code}/statutory"
        r = self.a.patch(url, {"gratuityEligible": False}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = self.a.patch(url, {"gratuityEligible": False, "optOutReason": "Contract worker, outside s.2(10)"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["gratuityEligible"])
        self.assertEqual(r.json()["gratuityBasis"], "BASIC")

    def test_permission_is_needed(self):
        carol = make_user(self.company, "carol@rahman.test")
        r = self.client_for(carol).get(f"{BASE}/summary")
        self.assertEqual(r.status_code, 403)

    def test_tenancy(self):
        other = make_company("Other Ltd")
        row = PayrollElection.objects.filter(company=other).first()
        r = self.b.post(f"{BASE}/proposals/{row.uid}/approve", {}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(StatutoryScheme.objects.filter(company=other, expense_account__isnull=False).exists())
