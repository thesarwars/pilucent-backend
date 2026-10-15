"""Leave (backend spec §10.1 golden vectors L1-L20) and the API: permissions,
masking, tenancy, and compensatory credits arriving from attendance.

The clock is frozen on 2027-03-08, a Monday."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import TestCase

from common import clock
from employeeio.services.sites import default_site
from employeeio.test_support import (
    ApiMixin,
    FrozenClockMixin,
    give_salary_permissions,
    give_structure,
    make_company,
    make_company_admin,
    make_employee,
    make_user,
    seed_rules,
)
from timekeepingio.test_support import assign, day_shift, publish, worked_day

from .models import Encashment, LeaveAudit, LedgerEntry, LeaveHold, LeaveRequest
from .services import ops, reads
from .services.core import (
    Book,
    LeaveRefused,
    cycle_for,
    d4,
    day_breakdown,
    ensure_types,
    expire_credits,
    position,
    reverse_entry,
    sync_credits,
)

TODAY = date(2027, 3, 8)
EID = [(date(2027, 3, 10), "Eid-ul-Fitr", "FESTIVAL_HOLIDAY"), (date(2027, 3, 11), "Eid-ul-Fitr", "FESTIVAL_HOLIDAY")]
API = "/api/v1/we/leave"


def give_leave_permissions(user, company, *codenames):
    from adminio.models import CompanyRole
    from companyio.models import CompanyUser

    role, _ = CompanyRole.objects.get_or_create(company=company, name="Leave " + "-".join(codenames))
    role.permission.add(*Permission.objects.filter(content_type__app_label="leaveledgerio", codename__in=codenames))
    CompanyUser.objects.get(user=user, company=company).roles.add(role)


class Base(FrozenClockMixin, TestCase):
    frozen_on = TODAY

    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.site = default_site(cls.company)
        publish(cls.company, 2027, days=EID)
        publish(cls.company, 2026)
        worker = dict(classification="WORKER", establishment="FACTORY", doj=date(2025, 3, 8))
        cls.emp = make_employee(cls.company, "EMP-0001", "Rahima Begum", gender="FEMALE", **worker)
        cls.types = ensure_types(cls.company)

    def t(self, code):
        return self.types[code]

    def pos(self, code, employee=None, as_of=TODAY):
        return position(employee or self.emp, self.t(code), as_of)

    def earned(self, days, employee=None, effective=TODAY):
        return ops.grant(self.company, employee or self.emp, "EARNED", days, reason="Opening balance migrated",
                         effective=effective)


class AccrualTests(Base):
    def accrue(self, employee=None, days=364, commit=True):
        employee = employee or self.emp
        return ops.accrual_run(self.company, [employee], TODAY, days_worked={employee.code: days}, commit=commit)

    def test_l1_364_days_over_18_floors_to_20_exactly(self):
        out = self.accrue()
        row = out["rows"][0]
        self.assertEqual((row["outcome"], row["granted"], row["raw"]), ("OK", "20", "20.2222"))
        self.assertIn("364 days worked ÷ 18, floored = 20; capped at 40 for a factory, so 20 granted", row["basis"])
        self.assertEqual(self.pos("EARNED").balance, Decimal("20.0000"))

    def test_l2_a_second_run_is_refused_and_changes_nothing(self):
        self.accrue()
        again = self.accrue()["rows"][0]
        self.assertEqual(again["outcome"], "ALREADY_POSTED")
        self.assertEqual(self.pos("EARNED").balance, Decimal("20.0000"))
        target = cycle_for(self.emp, self.t("EARNED"), TODAY, Book())
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.create(company=self.company, employee=self.emp, leave_type=self.t("EARNED"),
                                       cycle=target, effective_date=TODAY, days=1, reason="ACCRUAL", basis="again",
                                       rule_set=target.rule_set)

    def test_l3_the_cap_bites(self):
        self.earned(38)
        row = self.accrue()["rows"][0]
        self.assertEqual((row["outcome"], row["granted"], row["capped"]), ("CAPPED", "2", True))
        self.assertEqual(self.pos("EARNED").balance, Decimal("40.0000"))

    def test_l4_at_the_cap_a_zero_day_marker_is_posted(self):
        self.earned(40)
        self.accrue()
        marker = LedgerEntry.objects.get(employee=self.emp, reason="ACCRUAL_CAPPED")
        self.assertEqual(marker.days, Decimal("0"))
        self.assertIn("so 0 granted", marker.basis)

    def test_l15_factory_and_commercial_cap_differently(self):
        shop = make_employee(self.company, "EMP-0002", "Karim", classification="WORKER",
                             establishment="COMMERCIAL_ESTABLISHMENT", doj=date(2025, 3, 8))
        for e in (self.emp, shop):
            self.earned(35, e)
        out = ops.accrual_run(self.company, [self.emp, shop], TODAY, days_worked={"EMP-0001": 364, "EMP-0002": 364},
                              commit=True)
        self.assertEqual([r["granted"] for r in out["rows"]], ["5", "20"])

    def test_the_first_service_year_is_not_eligible(self):
        newer = make_employee(self.company, "EMP-0003", "Nasima", classification="WORKER", establishment="FACTORY",
                              doj=date(2026, 9, 1))
        self.assertEqual(self.accrue(newer)["rows"][0]["outcome"], "NOT_ELIGIBLE")

    def test_without_a_figure_attendance_must_cover_the_year(self):
        row = ops.accrual_run(self.company, [self.emp], TODAY, commit=False)["rows"][0]
        self.assertEqual(row["outcome"], "NEEDS_DAYS")

    def test_days_worked_come_from_attendance_when_it_covers_the_year(self):
        shift = day_shift(self.company)
        assign(self.emp, shift, date(2026, 3, 8))
        d = date(2026, 3, 8)
        while d <= date(2027, 3, 7):
            if d.isoweekday() != 5 and d not in (date(2027, 3, 10),):
                worked_day(self.emp, d.isoformat())
            d += timedelta(days=1)
        row = ops.accrual_run(self.company, [self.emp], TODAY, commit=False)["rows"][0]
        self.assertEqual((row["outcome"], row["source"]), ("OK", "attendance"))
        self.assertEqual(row["granted"], str(int(Decimal(row["worked"]) // 18)))


class RequestTests(Base):
    def submit(self, code, start, end, employee=None, **kw):
        return ops.submit_request(self.company, employee or self.emp, code, start, end, **kw)

    def test_l5_holds_stop_the_fourth_request_at_submission(self):
        reqs = [self.submit("CASUAL", f"2027-03-{d}", f"2027-03-{d + 2}") for d in (15, 22, 29)]
        self.assertEqual(self.pos("CASUAL").held, Decimal("9.0000"))
        with self.assertRaises(LeaveRefused) as caught:
            self.submit("CASUAL", "2027-04-05", "2027-04-07")
        self.assertIn("has 1 casual leave and asked for 3", str(caught.exception))
        for r in reqs:
            ops.approve_request(self.company, r.reference)
        p = self.pos("CASUAL")
        self.assertEqual((p.balance, p.held, p.committed, p.spendable),
                         (Decimal("10"), Decimal("0"), Decimal("9"), Decimal("1")))

    def test_l6_a_balance_that_moved_is_refused_at_approval(self):
        req = self.submit("CASUAL", "2027-03-15", "2027-03-18")  # 4 days
        grant = LedgerEntry.objects.get(employee=self.emp, leave_type=self.t("CASUAL"), reason="ACCRUAL")
        reverse_entry(grant, reason="Joined mid-year: prorated", replacement_days=3)
        with self.assertRaises(LeaveRefused) as caught:
            ops.approve_request(self.company, req.reference)
        self.assertIn("The balance moved", str(caught.exception))

    def test_l7_nobody_approves_their_own_leave(self):
        user = make_user(self.company, "rahima@rahman.test")
        self.emp.user = user
        self.emp.save()
        req = self.submit("CASUAL", "2027-03-15", "2027-03-16")
        with self.assertRaises(LeaveRefused) as caught:
            ops.approve_request(self.company, req.reference, user=user)
        self.assertEqual(caught.exception.status, 403)

    def test_l8_earned_leave_over_eid_consumes_the_holidays(self):
        b = day_breakdown(self.emp, self.t("EARNED"), date(2027, 3, 9), date(2027, 3, 15))
        self.assertEqual(b["consumed"], "7")
        self.assertIn("counts the holidays inside it", b["sentence"])

    def test_l9_casual_leave_over_eid_excludes_them_and_says_so(self):
        b = day_breakdown(self.emp, self.t("CASUAL"), date(2027, 3, 9), date(2027, 3, 15))
        self.assertEqual(b["consumed"], "4")
        self.assertIn("does not count holidays", b["sentence"])
        self.assertIn("Eid-ul-Fitr on 10 Mar", b["sentence"])

    def test_l19_no_calendar_refuses(self):
        with self.assertRaises(LeaveRefused) as caught:
            day_breakdown(self.emp, self.t("CASUAL"), date(2028, 1, 3), date(2028, 1, 4))
        self.assertEqual(caught.exception.status, 409)

    def test_half_days_and_whole_day_types(self):
        b = day_breakdown(self.emp, self.t("CASUAL"), date(2027, 3, 15), date(2027, 3, 16), "SECOND_HALF", "FIRST_HALF")
        self.assertEqual(b["consumed"], "1")
        with self.assertRaises(LeaveRefused):
            day_breakdown(self.emp, self.t("SICK"), date(2027, 3, 15), date(2027, 3, 16), "SECOND_HALF")

    def test_a_request_across_the_year_end_is_split(self):
        with self.assertRaises(LeaveRefused) as caught:
            self.submit("CASUAL", "2027-12-30", "2028-01-03")
        self.assertIn("Split it", str(caught.exception))

    def test_a_non_worker_is_not_entitled_to_statutory_casual_leave(self):
        officer = make_employee(self.company, "EMP-0009", "Officer", classification="NON_WORKER", doj=date(2024, 1, 1))
        with self.assertRaises(LeaveRefused) as caught:
            self.submit("CASUAL", "2027-03-15", "2027-03-15", employee=officer)
        self.assertIn("worker's entitlement", str(caught.exception))
        self.submit("BEREAVEMENT", "2027-03-15", "2027-03-15", employee=officer)

    def test_decline_and_withdraw_release_the_hold(self):
        a = self.submit("CASUAL", "2027-03-15", "2027-03-17")
        b = self.submit("CASUAL", "2027-03-22", "2027-03-24")
        with self.assertRaises(LeaveRefused):
            ops.decline_request(self.company, a.reference, reason="short")
        ops.decline_request(self.company, a.reference, reason="Line fully booked that week")
        ops.withdraw_request(self.company, b.reference)
        self.assertFalse(LeaveHold.objects.filter(released_at__isnull=True).exists())
        self.assertEqual(self.pos("CASUAL").spendable, Decimal("10"))

    def test_cancelling_approved_leave_puts_the_days_back_beside_the_original(self):
        r = self.submit("CASUAL", "2027-03-15", "2027-03-17")
        ops.approve_request(self.company, r.reference)
        ops.cancel_request(self.company, r.reference, reason="Shipment moved; worker stays")
        self.assertEqual(self.pos("CASUAL").spendable, Decimal("10"))
        self.assertEqual(sorted(LedgerEntry.objects.filter(employee=self.emp, leave_type=self.t("CASUAL"))
                                .values_list("reason", flat=True)), ["ACCRUAL", "CANCELLED", "TAKEN"])

    def test_an_advance_takes_the_balance_below_zero_only_where_allowed(self):
        with self.assertRaises(LeaveRefused) as caught:
            self.submit("EARNED", "2027-03-15", "2027-03-17")
        self.assertIn("advance request", str(caught.exception))
        req = self.submit("EARNED", "2027-03-15", "2027-03-17", is_advance=True)
        ops.approve_request(self.company, req.reference)
        self.assertEqual(self.pos("EARNED", as_of=date(2027, 3, 15)).spendable, Decimal("-3"))


class LedgerTests(Base):
    def test_l11_a_correction_is_a_reversal_and_a_replacement(self):
        entry = self.earned(20)
        reversal, replacement = reverse_entry(entry, reason="Days worked were 324, not 364", replacement_days=18)
        entry.refresh_from_db()
        self.assertEqual(entry.reversed_by_id, reversal.pk)
        self.assertEqual((reversal.reason, reversal.days, replacement.days), ("REVERSAL", Decimal("-20"), Decimal("18")))
        self.assertEqual(self.pos("EARNED").balance, Decimal("18"))
        self.assertEqual(LedgerEntry.objects.filter(employee=self.emp, leave_type=self.t("EARNED")).count(), 3)

    def test_l12_reversing_twice_is_refused(self):
        entry = self.earned(20)
        reverse_entry(entry, reason="Entered against the wrong employee")
        with self.assertRaises(LeaveRefused) as caught:
            reverse_entry(entry, reason="Entered against the wrong employee")
        self.assertEqual(caught.exception.status, 409)

    def test_the_ledger_is_never_edited_or_deleted(self):
        from django.core.exceptions import ValidationError

        entry = self.earned(5)
        entry.days = 50
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            LedgerEntry.objects.filter(pk=entry.pk).update(days=50)
        with self.assertRaises(ValidationError):
            LedgerEntry.objects.filter(pk=entry.pk).delete()

    def test_an_entry_pins_the_rule_set_in_force_on_its_date(self):
        old = self.earned(5, effective=date(2026, 3, 1))
        new = self.earned(5)
        self.assertEqual((old.rule_set.version, new.rule_set.version), ("2015-09-01", "2026-04-10"))

    def test_l20_no_float_drift(self):
        self.assertEqual(d4("0.1") + d4("0.2"), Decimal("0.3"))
        self.assertEqual(d4(Decimal(364) / 18), Decimal("20.2222"))

    def test_a_debit_is_tested_against_what_can_be_spent(self):
        ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-15", "2027-03-18")  # 4 days held
        with self.assertRaises(LeaveRefused) as caught:
            ops.grant(self.company, self.emp, "CASUAL", -7, reason="Unauthorised absence recovered")
        self.assertIn("6 days free to debit", str(caught.exception))

    def test_l18_year_end_carries_to_the_cap_and_forfeits_the_rest(self):
        self.earned(55, effective=date(2026, 6, 1))
        preview = ops.year_end_close(self.company, [self.emp], TODAY)
        self.assertEqual((preview["rows"][0]["carried"], preview["rows"][0]["forfeited"]), ("40", "15"))
        self.assertFalse(LedgerEntry.objects.filter(reason__in=["FORFEITURE", "OPENING"]).exists())
        with self.assertRaises(LeaveRefused):
            ops.year_end_close(self.company, [self.emp], TODAY, commit=True)
        ops.year_end_close(self.company, [self.emp], TODAY, commit=True, confirm=True)
        self.assertEqual(LedgerEntry.objects.get(reason="FORFEITURE").days, Decimal("-15"))
        self.assertEqual(self.pos("EARNED").balance, Decimal("40"))
        self.assertEqual(ops.year_end_close(self.company, [self.emp], TODAY)["rows"], [])


class EncashmentTests(Base):
    def test_l16_more_than_half_of_what_can_be_spent_is_refused(self):
        self.earned(10)
        with self.assertRaises(LeaveRefused) as caught:
            ops.request_encashment(self.company, self.emp, 6)
        self.assertIn("at most 5 encashable", str(caught.exception))

    def test_l17_once_a_cycle_and_the_days_go_at_approval(self):
        self.earned(10)
        give_structure(self.emp, 30000, effective_from=date(2026, 7, 1))
        enc = ops.request_encashment(self.company, self.emp, 4)
        self.assertEqual((enc.divisor, enc.daily_rate, enc.amount), (30, Decimal("1000"), Decimal("4000")))
        self.assertEqual(self.pos("EARNED").balance, Decimal("10"))
        with self.assertRaises(LeaveRefused) as caught:
            ops.request_encashment(self.company, self.emp, 1)
        self.assertEqual(caught.exception.status, 409)
        ops.approve_encashment(self.company, enc.reference)
        self.assertEqual(self.pos("EARNED").balance, Decimal("6"))
        paid = ops.mark_encashment_paid(self.company, enc.reference)
        self.assertEqual((paid.payroll_ref, paid.payslip_ref), ("PAYRUN-2027-03", "PS-2027-03-EMP-0001"))


class MaternityTests(Base):
    def open(self, children=1):
        return ops.open_maternity_case(self.company, self.emp, notice_date="2027-02-01", notice_method="ORAL",
                                       expected_delivery="2027-06-01", surviving_children=children)

    def test_l10_maternity_counts_every_calendar_day(self):
        case = self.open()
        self.assertEqual((case.pre_leave_from, case.post_leave_to, case.total_days_granted),
                         (date(2027, 4, 2), date(2027, 7, 30), 120))
        self.assertEqual(case.request.days_consumed, Decimal("120"))
        self.assertTrue(case.request.non_refusable)
        self.assertEqual(case.request.status, "APPROVED")

    def test_l14_three_surviving_children_lose_the_benefit_not_the_leave(self):
        case = self.open(children=3)
        self.assertFalse(case.benefit_payable)
        self.assertEqual((case.request.status, case.total_days_granted), ("APPROVED", 120))
        self.assertIn("The 120 days of leave stand either way", case.eligibility_reason)
        self.assertNotIn("3", case.eligibility_reason.split("either")[0].replace("120", ""))

    def test_l13_a_restricted_read_without_the_permission_is_refused_and_logged(self):
        case = self.open()
        with self.assertRaises(LeaveRefused) as caught:
            ops.read_restricted(self.company, case.reference, user=None, allowed=False)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(LeaveAudit.objects.filter(action="RESTRICTED_READ_REFUSED").count(), 3)
        out = ops.read_restricted(self.company, case.reference, user=None, allowed=True)
        self.assertEqual(out["survivingChildren"], 1)
        self.assertEqual(LeaveAudit.objects.filter(action="RESTRICTED_READ").count(), 3)

    def test_a_late_delivery_protects_the_post_delivery_leave(self):
        case = self.open()
        clock.freeze(date(2027, 6, 20))
        case = ops.record_delivery(self.company, case.reference, actual_delivery="2027-06-15")
        self.assertEqual(case.post_leave_to, date(2027, 8, 13))
        self.assertEqual(case.request.days_consumed, Decimal("134"))

    def test_a_man_has_no_maternity_case(self):
        man = make_employee(self.company, "EMP-0005", "Rafiq", gender="MALE", doj=date(2024, 1, 1))
        with self.assertRaises(LeaveRefused):
            ops.open_maternity_case(self.company, man, notice_date="2027-02-01", notice_method="WRITTEN",
                                    expected_delivery="2027-06-01", surviving_children=0)


class CreditTests(Base):
    def test_confirmed_holiday_work_credits_compensatory_leave_which_lapses(self):
        from timekeepingio.services import ops as attendance

        assign(self.emp, day_shift(self.company), date(2027, 1, 1))
        worked_day(self.emp, "2027-03-05")  # a Friday: the weekly holiday
        attendance.resolve(self.company, self.emp, date(2027, 3, 5), "WORKED_WEEKLY_HOLIDAY", "CONFIRM")
        entry = LedgerEntry.objects.get(employee=self.emp, reason="CREDIT_EARNED")
        self.assertEqual(entry.days, Decimal("1"))
        sync_credits(self.company)  # already posted: nothing twice
        self.assertEqual(LedgerEntry.objects.filter(reason="CREDIT_EARNED").count(), 1)
        self.assertEqual(self.pos("COMPENSATORY").spendable, Decimal("1"))
        expire_credits(self.company, date(2027, 4, 10))
        self.assertEqual(LedgerEntry.objects.get(reason="CREDIT_EXPIRED").days, Decimal("-1"))
        self.assertEqual(self.pos("COMPENSATORY", as_of=date(2027, 4, 10)).balance, Decimal("0"))


class ApiTests(ApiMixin, Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.clerk = make_user(self.company, "clerk@rahman.test")

    def test_balances_show_three_figures_per_type(self):
        ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-15", "2027-03-17")
        body = self.client_for(self.admin).get(f"{API}/balances").json()
        casual = body["rows"][0]["positions"]["CASUAL"]
        self.assertEqual((casual["balance"], casual["held"], casual["committed"], casual["spendable"]),
                         ("10", "3", "0", "7"))
        self.assertEqual(body["counts"]["CLAIMED"], 1)

    def test_applying_and_approving_need_their_permissions(self):
        body = {"employeeCode": "EMP-0001", "type": "CASUAL", "from": "2027-03-15", "to": "2027-03-16"}
        client = self.client_for(self.clerk)
        self.assertEqual(client.post(f"{API}/requests", body, format="json").status_code, 403)
        give_leave_permissions(self.clerk, self.company, "apply_leave")
        made = client.post(f"{API}/requests", body, format="json")
        self.assertEqual(made.status_code, 201)
        ref = made.json()["reference"]
        self.assertEqual(client.post(f"{API}/requests/{ref}/approve", {}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.admin).post(f"{API}/requests/{ref}/approve", {}, format="json")
                         .status_code, 200)
        self.assertTrue(LeaveAudit.objects.filter(action="REQUEST_SUBMITTED", on_behalf_of=self.emp).exists())

    def test_the_approval_card_tests_against_other_holds_only(self):
        ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-15", "2027-03-17")
        ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-22", "2027-03-24")
        rows = self.client_for(self.admin).get(f"{API}/approvals").json()["rows"]
        self.assertEqual([r["position"]["spendable"] for r in rows], ["7", "7"])
        self.assertIn("Nobody else out", rows[0]["clash"]["title"])

    def test_encashment_amounts_are_masked_without_salary_figures(self):
        self.earned(10)
        give_structure(self.emp, 30000, effective_from=date(2026, 7, 1))
        ops.request_encashment(self.company, self.emp, 4)
        masked = self.client_for(self.clerk).get(f"{API}/encashments").json()
        self.assertEqual((masked["rows"][0]["amount"], masked["masked"]), (None, True))
        give_salary_permissions(self.clerk, self.company, "view_salary_figures")
        self.assertEqual(self.client_for(self.clerk).get(f"{API}/encashments").json()["rows"][0]["amount"], "4000.00")

    def test_another_companys_employee_is_not_found(self):
        other = make_company("Other Ltd")
        make_employee(other, "EMP-7777", "Outsider")
        self.assertEqual(self.client_for(self.admin).get(f"{API}/employees/EMP-7777").status_code, 404)

    def test_the_restricted_read_logs_a_refusal(self):
        case = ops.open_maternity_case(self.company, self.emp, notice_date="2027-02-01", notice_method="WRITTEN",
                                       expected_delivery="2027-06-01", surviving_children=0)
        response = self.client_for(self.clerk).get(f"{API}/maternity/{case.reference}/restricted")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(LeaveAudit.objects.filter(action="RESTRICTED_READ_REFUSED", actor=self.clerk).exists())
        listing = self.client_for(self.clerk).get(f"{API}/maternity").json()["rows"][0]
        self.assertNotIn("survivingChildren", listing)
        self.assertNotIn("expectedDelivery", listing)

    def test_the_accrual_run_previews_before_it_posts(self):
        client = self.client_for(self.admin)
        body = {"asOf": "2027-03-08", "daysWorked": {"EMP-0001": 364}}
        preview = client.post(f"{API}/accrual-runs", body, format="json").json()
        self.assertEqual((preview["postable"], preview["rows"][0]["outcome"]), (1, "OK"))
        self.assertFalse(LedgerEntry.objects.filter(reason="ACCRUAL", leave_type=self.t("EARNED")).exists())
        posted = client.post(f"{API}/accrual-runs", {**body, "commit": True}, format="json").json()
        self.assertIn("entry", posted["rows"][0])
        again = client.post(f"{API}/accrual-runs", {**body, "commit": True}, format="json").json()
        self.assertEqual(again["rows"][0]["outcome"], "ALREADY_POSTED")

    def test_policy_reads_the_rule_book(self):
        body = self.client_for(self.admin).get(f"{API}/policy").json()
        factory = next(r for r in body["establishments"] if r["establishment"] == "FACTORY")
        self.assertEqual((factory["divisor"], factory["cap"]), (18, 40))
        casual = next(t for t in body["types"] if t["code"] == "CASUAL")
        self.assertEqual(casual["entitlement"], "10")

    def test_applications_list_derives_the_phase(self):
        r = ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-08", "2027-03-09")
        ops.approve_request(self.company, r.reference)
        rows = self.client_for(self.admin).get(f"{API}/requests").json()["rows"]
        self.assertEqual(rows[0]["phase"], "IN_PROGRESS")
        self.assertEqual(LeaveRequest.objects.get().status, "APPROVED")

    def test_encashment_and_leave_reads_use_one_position(self):
        self.earned(10)
        out = self.client_for(self.admin).get(f"{API}/employees/EMP-0001/encashment").json()
        self.assertEqual(out["ceiling"], "5")
        self.assertEqual(Encashment.objects.count(), 0)
        _ = reads  # the module the views read through
