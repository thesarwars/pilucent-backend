"""Run payroll (docs/backend/run-payroll-done.md §11): the golden vectors R1-R20,
the properties and the API.

The period is February 2027: a 28-day month, so a full month on a fixed
divisor is the case R2 pins.
"""

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from employeeio.models import EmployeeSalaryComponent, EmployeeSalaryStructure, ProcessedPayrollPeriod
from employeeio.services.sites import default_site
from employeeio.test_support import (
    ApiMixin,
    FrozenClockMixin,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)
from paysetio.models import PaySchedule
from paysetio.services.ops import create_scheme_accounts
from paysetio.test_support import constitute_pf, join, set_election
from rulebookio.models import RuleSet
from timekeepingio.models import AttendancePeriod, DaySnapshot, HolidayCalendar, HolidayCalendarDay

from .models import PaymentInstruction, PayrollException, PayrollRun, PayrollRunLine, PayrollRunTransition, RunEvent
from .services import ops as R
from .services.engine import LineInput, apply_deductions, compute_line
from .services.ops import RunRefused

PERIOD = date(2027, 2, 1)
BASE = "/api/v1/we/payroll-runs"


def publish_calendar(site, year, festivals=()):
    cal = HolidayCalendar.objects.create(company=site.company, site=site, calendar_year=year, status="PUBLISHED",
                                         weekly_pattern={"5": 1})  # Friday
    for d in festivals:
        HolidayCalendarDay.objects.create(calendar=cal, holiday_date=d, name="Festival", kind="FESTIVAL_HOLIDAY")
    return cal


class RunCase(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.site = default_site(cls.company)
        cls.officer = make_user(cls.company, "officer@rahman.test")
        cls.manager = make_user(cls.company, "manager@rahman.test")
        for u in (cls.officer, cls.manager):
            make_company_admin(u, cls.company)
        for y in (2026, 2027):
            publish_calendar(cls.site, y)
        PaySchedule.objects.create(company=cls.company, frequency="MONTHLY", cutoff_day=25, payment_day=7,
                                   effective_from=date(2000, 1, 1))
        create_scheme_accounts(cls.company, ["GRATUITY"])

    def worker(self, code, gross=20000, doj=date(2020, 1, 1), method="BANK_TRANSFER", **fields):
        e = make_employee(self.company, code, name_en=f"Worker {code}", status="ACTIVE", doj=doj,
                          classification="WORKER", establishment="FACTORY", **fields)
        if gross is not None:
            give_structure(e, gross, effective_from=min(doj, date(2026, 7, 1)))
        p = e.payment
        p.method = method
        if method == "BANK_TRANSFER":
            p.bank, p.account_number, p.routing, p.account_name = "City Bank", f"14020{code[-4:]}88", "225261725", \
                e.name_en
        elif method == "MFS":
            p.mfs_provider, p.wallet_number = "BKASH", "01711223344"
        p.save()
        return e

    def lock(self, month=PERIOD, rows=None):
        labour = RuleSet.objects.filter(family="LABOUR", status="PUBLISHED").order_by("effective_from").first()
        period = AttendancePeriod.objects.create(company=self.company, site=self.site, period_month=month,
                                                 rule_set=labour, status="LOCKED")
        for e, spec in (rows or {}).items():
            for d in spec.get("lwp", ()):
                DaySnapshot.objects.create(company=self.company, employee=e, business_date=d, period=period,
                                           status="LEAVE_WITHOUT_PAY", worked_minutes=0, overtime_minutes=0,
                                           late_minutes=0, rule_set=labour, input_hash="x")
            if spec.get("ot"):
                DaySnapshot.objects.create(company=self.company, employee=e, business_date=month + timedelta(days=1),
                                           period=period, status="PRESENT_OT", worked_minutes=480,
                                           overtime_minutes=spec["ot"], late_minutes=0, rule_set=labour,
                                           input_hash="x")
        return period

    def open_run(self, month=PERIOD, **kw):
        run, _ = R.create_run(self.company, self.site, month, user=self.officer, **kw)
        return run

    def computed(self, month=PERIOD):
        run = self.open_run(month)
        run, _ = R.compute(run, user=self.officer)
        return run

    def line(self, run, e):
        return PayrollRunLine.objects.get(run=run, employee=e)

    def codes(self, run, e=None):
        q = PayrollException.objects.filter(run=run)
        if e is not None:
            q = q.filter(employee=e)
        return {x.code for x in q}


class GoldenVectors(RunCase):
    def test_r1_full_month(self):
        e = self.worker("W-0001")
        self.lock()
        run = self.computed()
        ln = self.line(run, e)
        self.assertEqual(ln.proration_factor, 1)
        self.assertEqual(ln.days_lost, 0)
        self.assertEqual(ln.gross, Decimal("20000"))
        self.assertNotIn("PRORATED", self.codes(run, e))
        self.assertEqual(run.state, "COMPUTED")
        self.assertEqual(run.total_net, ln.net_pay)

    def test_r2_a_28_day_february_is_not_a_part_month(self):
        set_election(self.company, "proration_method", "FIXED_30")
        e = self.worker("W-0002")
        self.lock()
        run = self.computed()
        ln = self.line(run, e)
        self.assertEqual(ln.calendar_days, 28)
        self.assertEqual(ln.days_lost, 0)
        self.assertEqual(ln.proration_factor, 1)
        self.assertNotIn("PRORATED", self.codes(run, e))

    def test_r3_joined_on_the_15th(self):
        e = self.worker("W-0003", doj=date(2027, 2, 15))
        self.lock()
        run = self.computed()
        ln = self.line(run, e)
        self.assertEqual(ln.days_lost, 14)
        self.assertEqual(ln.payable_days, 14)
        x = PayrollException.objects.get(run=run, employee=e, code="PRORATED")
        self.assertEqual(x.severity, "INFO")
        self.assertIn("joined 15/02/2027", x.message)
        self.assertEqual(ln.proration_factor, Decimal("0.5"))  # calendar days, 14 of 28

    def test_r4_lwp_is_read_from_attendance(self):
        e = self.worker("W-0004")
        self.lock(rows={e: {"lwp": [date(2027, 2, 9), date(2027, 2, 10), date(2027, 2, 11)]}})
        run = self.computed()
        ln = self.line(run, e)
        self.assertEqual(ln.lwp_days, 3)
        self.assertEqual(ln.days_lost, 3)
        self.assertIn("3 days leave without pay",
                      PayrollException.objects.get(run=run, employee=e, code="PRORATED").message)

    def test_r5_deductions_exceeding_gross_block_and_store_no_negative_net(self):
        inp = LineInput(employee_code="W", employee_name="W", classification="WORKER", period_start=PERIOD,
                        period_end=date(2027, 2, 28), calendar_days=28, payable_days=Decimal(28),
                        components=(("BASIC", "Basic", Decimal("5000")),), tax_period=Decimal("6000"))
        r = compute_line(inp)
        self.assertEqual(r.net, 0)
        x = next(x for x in r.exceptions if x["code"] == "NET_NOT_POSITIVE")
        self.assertEqual(x["severity"], "BLOCK")
        self.assertIn("৳ -1,000", x["message"])

    def test_r6_cash_warns_citing_s55_and_stays_approvable(self):
        e = self.worker("W-0006", method="CASH")
        self.lock()
        run = self.computed()
        x = PayrollException.objects.get(run=run, employee=e, code="CASH_PAYMENT")
        self.assertEqual((x.severity, x.citation), ("WARN", "Income Tax Act 2023, s.55"))
        run = R.approve(run, user=self.manager)
        self.assertEqual(run.state, "APPROVED")

    def test_r7_no_structure_blocks_and_approval_is_refused(self):
        e = self.worker("W-0007", gross=None)
        self.lock()
        run = self.computed()
        self.assertTrue(self.line(run, e).blocked)
        self.assertEqual(PayrollException.objects.get(run=run, employee=e).code, "NO_STRUCTURE")
        with self.assertRaises(RunRefused) as cm:
            R.approve(run, user=self.manager)
        self.assertEqual(cm.exception.status, 422)
        self.assertEqual(cm.exception.detail["blockers"][0]["code"], "NO_STRUCTURE")

    def test_r8_excluding_a_blocker_records_the_reason_and_permits_approval(self):
        self.worker("W-0081")
        e = self.worker("W-0082", gross=None)
        self.lock()
        run = self.computed()
        x = PayrollException.objects.get(run=run, employee=e, code="NO_STRUCTURE")
        with self.assertRaises(RunRefused):
            R.resolve_exception(run, x, resolution="EXCLUDED", reason="short", user=self.officer, can_exclude=True)
        R.resolve_exception(run, x, resolution="EXCLUDED", reason="No structure yet — pay on a supplementary run",
                            user=self.officer, can_exclude=True)
        ln = self.line(run, e)
        self.assertFalse(ln.included)
        self.assertIn("supplementary", ln.exclusion_reason)
        run = R.approve(run, user=self.manager)
        self.assertEqual((run.state, run.included_count, run.excluded_count), ("APPROVED", 1, 1))

    def test_r9_a_block_cannot_be_accepted(self):
        e = self.worker("W-0009", gross=None)
        self.lock()
        run = self.computed()
        x = PayrollException.objects.get(run=run, employee=e)
        with self.assertRaises(RunRefused):
            R.resolve_exception(run, x, resolution="ACCEPTED", reason="looks fine to me", user=self.officer)
        x.resolved, x.resolution, x.resolved_by = True, "ACCEPTED", self.officer
        with self.assertRaises(IntegrityError), transaction.atomic():
            x.save()

    def test_r10_the_creator_cannot_approve(self):
        self.worker("W-0010")
        self.lock()
        run = self.computed()
        with self.assertRaises(RunRefused) as cm:
            R.approve(run, user=self.officer)
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayrollRun.objects.filter(pk=run.pk).update(approved_by=self.officer)

    def test_r11_a_second_regular_run_for_the_period_is_refused(self):
        self.worker("W-0011")
        self.lock()
        run = self.open_run()
        with self.assertRaises(RunRefused) as cm:
            self.open_run()
        self.assertEqual(cm.exception.status, 409)
        dup = PayrollRun(company=run.company, site=run.site, schedule=run.schedule, period=run.period,
                         period_start=run.period_start, period_end=run.period_end,
                         statutory_due_date=run.statutory_due_date, payment_date=run.payment_date,
                         rule_set=run.rule_set, tax_card=run.tax_card, engine_version="x", elections_snapshot={},
                         created_by=self.officer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            dup.save()
        R.cancel(run, reason="Opened against the wrong month", user=self.officer)
        self.assertEqual(self.open_run().state, "DRAFT")  # a cancelled run frees the period

    def test_r12_a_line_cannot_be_edited_after_approval(self):
        e = self.worker("W-0012")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        ln = self.line(run, e)
        ln.net_pay = ln.net_pay + 1
        with self.assertRaises(ValidationError):
            ln.save()
        with self.assertRaises(ValidationError):
            self.line(run, e).delete()

    def test_r13_payment_status_still_advances_after_approval(self):
        e = self.worker("W-0013")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        ln = self.line(run, e)
        ln.payment_status = "INSTRUCTED"
        ln.save()
        self.assertEqual(self.line(run, e).payment_status, "INSTRUCTED")

    def test_r14_a_replayed_instruction_returns_the_original(self):
        self.worker("W-0014")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        with self.assertRaises(RunRefused) as cm:
            R.instruct(run, "BP-CITY-CSV", idempotency_key="k-1", user=self.manager)
        self.assertEqual(cm.exception.detail["code"], "NO_CORPORATE_ACCOUNT")
        R.set_corporate_account(self.company, "BP-CITY-CSV", "1402-3399-8871", user=self.manager)
        a, created = R.instruct(run, "BP-CITY-CSV", idempotency_key="k-1", user=self.manager)
        b, again = R.instruct(run, "BP-CITY-CSV", idempotency_key="k-1", user=self.manager)
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(PaymentInstruction.objects.filter(run=run).count(), 1)
        self.assertEqual(a.file_hash, hashlib.sha256(R.instruction_bytes(a)).hexdigest())
        self.assertIn("1402-3399-8871", a.content)

    def test_r15_attendance_not_locked_refuses_the_run(self):
        self.worker("W-0015")
        with self.assertRaises(RunRefused) as cm:
            self.open_run()
        self.assertEqual((cm.exception.status, cm.exception.detail["code"]), (422, "ATTENDANCE_NOT_LOCKED"))

    def test_r16_an_election_changed_mid_run_does_not_move_the_snapshot(self):
        e = self.worker("W-0016", doj=date(2027, 2, 15))
        self.lock()
        run = self.computed()
        before = (dict(run.elections_snapshot["elections"]["proration_method"]), self.line(run, e).net_pay)
        set_election(self.company, "proration_method", "FIXED_30", on=date(2027, 2, 1))
        run, _ = R.compute(run, user=self.officer)
        run.refresh_from_db()
        self.assertEqual(run.elections_snapshot["elections"]["proration_method"], before[0])
        self.assertEqual(self.line(run, e).net_pay, before[1])

    def test_r17_a_structure_revised_after_compute_is_drift_at_approval(self):
        e = self.worker("W-0017")
        self.lock()
        run = self.computed()
        c = EmployeeSalaryComponent.objects.get(structure__employee=e, code="BASIC")
        EmployeeSalaryComponent.objects.filter(pk=c.pk).update(amount=c.amount + 500)
        with self.assertRaises(RunRefused) as cm:
            R.approve(run, user=self.manager)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.detail["employees"], ["W-0017"])
        run, _ = R.compute(run, user=self.officer)
        self.assertEqual(R.approve(run, user=self.manager).state, "APPROVED")

    def test_r18_a_december_period_is_due_in_january_of_the_next_year(self):
        self.worker("W-0018")
        self.lock(date(2026, 12, 1))
        run = self.open_run(date(2026, 12, 1))
        self.assertEqual(run.payment_date, date(2027, 1, 7))
        self.assertEqual(run.statutory_due_date.year, 2027)
        self.assertGreaterEqual(run.statutory_due_date, run.payment_date)

    def test_r19_a_festival_in_the_window_extends_the_due_date(self):
        cal = HolidayCalendar.objects.get(site=self.site, calendar_year=2027)
        for d in (date(2027, 3, 1), date(2027, 3, 2), date(2027, 3, 3)):
            HolidayCalendarDay.objects.create(calendar=cal, holiday_date=d, name="Festival", kind="FESTIVAL_HOLIDAY")
        self.worker("W-0019")
        self.lock()
        run = self.open_run()
        # Friday off; 1-3 March festival: the seventh working day is 11 March.
        self.assertEqual(run.statutory_due_date, date(2027, 3, 11))
        self.assertGreater(run.statutory_due_date, run.payment_date)

    def test_r20_lines_that_do_not_reconcile_refuse_approval(self):
        self.worker("W-0020")
        self.lock()
        run = self.computed()
        PayrollRun.objects.filter(pk=run.pk).update(total_net=run.total_net + 1)
        run.refresh_from_db()
        with self.assertRaises(RunRefused) as cm:
            R.approve(run, user=self.manager)
        self.assertIn("does not reconcile", str(cm.exception))


class Figures(RunCase):
    def test_overtime_is_on_the_full_s108_base_outside_the_factor(self):
        e = self.worker("W-0101", doj=date(2027, 2, 15))
        self.lock(rows={e: {"ot": 600}})
        ln = self.line(self.computed(), e)
        self.assertEqual(ln.ot_hours, Decimal("10.00"))
        # Basic 12,000 (+ no DA) ÷ 208 = 57.6923 × 2 × 10 = 1,153.85 → ceiling to the taka.
        self.assertEqual(ln.ot_amount, Decimal("1154"))
        self.assertEqual(ln.ot_base_amount, Decimal("12000"))

    def test_an_overtime_override_records_its_actor_and_reopens_the_team(self):
        e = self.worker("W-0102")
        self.lock(rows={e: {"ot": 120}})
        run = self.computed()
        R.set_line(run, self.line(run, e), user=self.officer, ot_hours="5", can_override=True)
        run.refresh_from_db()
        ln = self.line(run, e)
        self.assertEqual((ln.ot_hours_source, ln.ot_hours_overridden_by), ("MANUAL_OVERRIDE", self.officer))
        self.assertEqual(ln.ot_hours_attendance, Decimal("2.00"))
        self.assertEqual(run.state, "TEAM_SELECTED")
        with self.assertRaises(RunRefused):
            R.approve(run, user=self.manager)

    def test_pf_both_sides_match_on_the_pf_base(self):
        constitute_pf(self.company)
        e = self.worker("W-0103")
        create_scheme_accounts(self.company, ["PF"])
        join(e, "PF")
        self.lock()
        ln = self.line(self.computed(), e)
        self.assertEqual(ln.pf_employee, Decimal("960"))  # 8% of basic 12,000
        self.assertEqual(ln.pf_employer, ln.pf_employee)
        self.assertEqual(ln.net_pay, ln.gross - ln.tax_withheld - ln.pf_employee)
        self.assertEqual([d["code"] for d in ln.deductions_json][:2], ["TAX", "PF"] if ln.tax_withheld else ["PF"])

    def test_a_missing_bank_account_blocks(self):
        e = self.worker("W-0104")
        e.payment.account_number = ""
        e.payment.save()
        self.lock()
        run = self.computed()
        self.assertEqual(PayrollException.objects.get(run=run, employee=e).code, "MISSING_BANK_DETAIL")

    def test_a_held_salary_blocks_until_excluded(self):
        e = self.worker("W-0105")
        e.payment.on_hold, e.payment.hold_reason = True, "Disciplinary enquiry"
        e.payment.save()
        self.lock()
        run = self.computed()
        self.assertIn("SALARY_ON_HOLD", self.codes(run, e))
        self.assertEqual(self.line(run, e).payment_status, "HELD")

    def test_an_unanswered_election_refuses_the_run(self):
        from paysetio.models import PayrollElection

        PayrollElection.objects.filter(company=self.company, election_key="proration_method").update(
            status="REJECTED")
        self.worker("W-0106")
        self.lock()
        with self.assertRaises(RunRefused) as cm:
            self.open_run()
        self.assertEqual((cm.exception.status, cm.exception.detail["code"]), (409, "SETTINGS"))

    def test_deferral_never_reduces_a_protected_deduction(self):
        order = {"TAX": Decimal("900"), "PF": Decimal("200"), "LOAN": Decimal("500")}
        applied, deferred, total = apply_deductions(Decimal("1000"), order)
        self.assertEqual([d["code"] for d in applied], ["TAX", "PF"])
        self.assertEqual([d["code"] for d in deferred], ["LOAN"])
        self.assertEqual(total, Decimal("1100"))


class Properties(RunCase):
    def test_recomputing_twice_gives_the_same_input_hash(self):
        e = self.worker("W-0201", doj=date(2027, 2, 10))
        self.lock(rows={e: {"ot": 90}})
        run = self.computed()
        first = self.line(run, e).input_hash
        run, _ = R.compute(run, user=self.officer)
        self.assertEqual(self.line(run, e).input_hash, first)
        self.assertEqual(len(first), 64)

    def test_net_is_never_stored_negative(self):
        e = self.worker("W-0202")
        self.lock()
        ln = self.line(self.computed(), e)
        ln.net_pay = Decimal("-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ln.save()

    def test_payable_days_never_exceed_calendar_days(self):
        e = self.worker("W-0203")
        self.lock()
        ln = self.line(self.computed(), e)
        ln.payable_days = Decimal(29)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ln.save()

    def test_the_whole_run_to_closed_and_closed_is_terminal(self):
        a, b = self.worker("W-0204"), self.worker("W-0205", method="CASH")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        R.set_corporate_account(self.company, "BP-CITY-CSV", "1402-3399-8871", user=self.manager)
        R.instruct(run, "BP-CITY-CSV", idempotency_key="bank-1", user=self.manager)
        R.instruct(run, "CASH-SHEET", idempotency_key="cash-1", user=self.manager)
        run.refresh_from_db()
        self.assertEqual(run.state, "DISBURSING")
        total = sum((i.total_amount for i in run.instructions.all()), Decimal(0))
        self.assertLessEqual(total, run.total_net)
        R.mark_paid(run, [self.line(run, a)], user=self.manager)
        run.refresh_from_db()
        self.assertEqual(run.state, "PARTIALLY_PAID")
        with self.assertRaises(RunRefused):
            R.release(run, user=self.manager)
        R.mark_paid(run, [self.line(run, b)], user=self.manager)
        run.refresh_from_db()
        self.assertEqual(run.state, "PAID")
        run = R.release(run, user=self.manager)
        self.assertEqual(run.state, "CLOSED")
        self.assertTrue(ProcessedPayrollPeriod.objects.filter(company=self.company, period=PERIOD).exists())
        self.assertTrue(RunEvent.objects.filter(run=run, name="PayslipsReleased").exists())
        self.assertEqual(AttendancePeriod.objects.get(site=self.site, period_month=PERIOD).payroll_run_ref, run.ref)
        states = list(PayrollRunTransition.objects.filter(run=run).values_list("to_state", flat=True))
        self.assertEqual(states, ["DRAFT", "TEAM_SELECTED", "COMPUTED", "APPROVED", "DISBURSING", "PARTIALLY_PAID",
                                  "PAID", "CLOSED"])
        for action in (lambda: R.compute(run, user=self.officer), lambda: R.cancel(run, reason="x" * 12, user=self.officer)):
            with self.assertRaises(RunRefused):
                action()
        with self.assertRaises(ValidationError):
            PayrollRunTransition.objects.filter(run=run).delete()

    def test_a_failed_transfer_is_paid_by_a_new_instruction(self):
        e = self.worker("W-0206")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        R.set_corporate_account(self.company, "BP-CITY-CSV", "1402-3399-8871", user=self.manager)
        R.instruct(run, "BP-CITY-CSV", idempotency_key="f-1", user=self.manager)
        R.mark_failed(run, self.line(run, e), reason="Account closed by the bank", user=self.manager)
        self.assertEqual(self.line(run, e).payment_status, "FAILED")
        ins, created = R.instruct(run, "BP-CITY-CSV", idempotency_key="f-2", user=self.manager)
        self.assertTrue(created)
        self.assertEqual(self.line(run, e).payment_status, "INSTRUCTED")

    def test_a_file_with_an_invalid_row_is_never_written(self):
        e = self.worker("W-0207", method="MFS")
        self.lock()
        run = R.approve(self.computed(), user=self.manager)
        e.payment.wallet_number = "0171122"
        e.payment.save()
        R.set_corporate_account(self.company, "MFS-BKASH", "MERCHANT-88214", user=self.manager)
        with self.assertRaises(RunRefused) as cm:
            R.instruct(run, "MFS-BKASH", idempotency_key="m-1", user=self.manager)
        self.assertEqual(cm.exception.detail["issues"][0]["check"], "Wallet")
        self.assertFalse(PaymentInstruction.objects.filter(run=run).exists())


class Api(ApiMixin, RunCase):
    def setUp(self):
        super().setUp()
        self.a = self.client_for(self.officer)
        self.b = self.client_for(self.manager)

    def test_the_five_stages_over_http(self):
        e = self.worker("W-0301")
        self.worker("W-0302", gross=None)
        self.lock()
        r = self.a.get(f"{BASE}/overview?period=2027-02")
        self.assertEqual(r.status_code, 200, r.content)
        card = r.json()["sites"][0]
        self.assertEqual((card["headcount"], card["withoutStructure"], card["dueDate"]), (2, 1, "2027-03-08"))
        self.assertTrue(card["attendance"]["locked"])

        r = self.a.post(BASE, {"site": str(self.site.uid), "period": "2027-02", "idempotencyKey": "run-1"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)
        uid = r.json()["uid"]
        self.assertEqual(self.a.post(BASE, {"period": "2027-02", "idempotencyKey": "run-1"}, format="json")
                         .json()["uid"], uid)

        r = self.a.post(f"{BASE}/{uid}/compute")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["blockers"], 1)
        blocker = next(x for x in body["exceptions"] if x["severity"] == "BLOCK")

        self.assertEqual(self.b.post(f"{BASE}/{uid}/approve").status_code, 422)
        r = self.a.post(f"{BASE}/{uid}/exceptions/{blocker['uid']}/resolve",
                        {"resolution": "EXCLUDED", "reason": "Structure pending — supplementary run"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["blockers"], 0)

        r = self.a.post(f"{BASE}/{uid}/approve")
        self.assertEqual(r.status_code, 403)
        r = self.b.post(f"{BASE}/{uid}/approve")
        self.assertEqual((r.status_code, r.json()["state"]), (200, "APPROVED"))

        self.b.put(f"{BASE}/profiles", {"profile": "BP-CITY-CSV", "account": "1402-3399-8871"}, format="json")
        r = self.b.post(f"{BASE}/{uid}/payment-instructions", {"profile": "BP-CITY-CSV", "idempotencyKey": "i-1"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ins = r.json()["instruction"]
        f = self.b.get(f"{BASE}/{uid}/payment-instructions/{ins['uid']}/file")
        self.assertEqual(hashlib.sha256(f.content).hexdigest(), ins["hash"])

        r = self.b.post(f"{BASE}/{uid}/mark-paid", {"lines": "all"}, format="json")
        self.assertEqual(r.json()["state"], "PAID")
        r = self.b.post(f"{BASE}/{uid}/release")
        self.assertEqual(r.json()["state"], "CLOSED")
        reg = self.b.get(f"{BASE}/{uid}/register").json()
        self.assertEqual([row["code"] for row in reg["rows"]], [e.code])

    def test_reading_needs_the_permission(self):
        stranger = make_user(self.company, "stranger@rahman.test")
        r = self.client_for(stranger).get(f"{BASE}/overview")
        self.assertEqual(r.status_code, 403)

    def test_another_company_cannot_see_the_run(self):
        self.worker("W-0303")
        self.lock()
        run = self.open_run()
        other = make_company("Other Ltd")
        outsider = make_user(other, "out@other.test")
        make_company_admin(outsider, other)
        self.assertEqual(self.client_for(outsider).get(f"{BASE}/{run.uid}").status_code, 404)
