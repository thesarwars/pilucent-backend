"""The maternity lifecycle and benefit, the s.50 separation block, quarterly
statements, and the §9 events with their notifications. The clock is frozen
on 2027-03-08, a Monday; the 2027 calendar has Friday weekly and Eid on
10-11 March."""

from datetime import date
from decimal import Decimal


from common import clock
from employeeio.services import gated
from employeeio.test_support import give_structure, make_company_admin, make_user
from notificationio.models import Notification

from .models import LeaveEvent, LedgerEntry, MaternityEvent
from .services import maternity, ops, statements
from .services.core import LeaveRefused, position
from .tests_leave import Base


class MaternityLifecycleTests(Base):
    def setUp(self):
        super().setUp()
        give_structure(self.emp, 30000, effective_from=date(2026, 7, 1))

    def open(self, basis=None, children=1):
        return maternity.open_case(self.company, self.emp, notice_date="2027-02-01", notice_method="WRITTEN",
                                   expected_delivery="2027-06-01", surviving_children=children, basis=basis)

    def test_the_benefit_on_the_act_basis_is_wages_over_days(self):
        case = self.open()
        # Nov, Dec, Jan at 30,000; attendance not settled, so 30 + 31 + 31 calendar days.
        self.assertEqual((case.total_wage, case.total_days), (Decimal("90000"), Decimal("92")))
        self.assertEqual(case.average_daily_wage, Decimal("978.26"))
        self.assertEqual(case.benefit_amount, Decimal("117391.20"))
        self.assertEqual(case.first_instalment_amount + case.second_instalment_amount, case.benefit_amount)
        self.assertIn("calendar days", case.reference_lines[0]["daysSource"])

    def test_the_rules_basis_is_one_month_over_26_and_both_are_shown(self):
        preview = maternity.benefit_preview(self.company, self.emp, "2027-02-01", figures=True)
        amounts = {b["key"]: b["benefit"] for b in preview["bases"]}
        self.assertEqual(amounts, {"ACT_S48": "117391.20", "RULES_2022": "138462.00"})
        case = self.open(basis="RULES_2022")
        out = maternity.case_out(case, figures=True)
        self.assertEqual((out["benefit"]["amount"], out["benefit"]["other"]["benefit"]), ("138462.00", "117391.20"))
        masked = maternity.case_out(case, figures=False)
        self.assertIsNone(masked["benefit"]["amount"])

    def test_events_follow_the_statute_and_a_late_payment_is_named(self):
        case = self.open()
        with self.assertRaises(LeaveRefused):
            maternity.record_event(self.company, case.reference, "PAY_FIRST", on="2027-02-03")
        maternity.record_event(self.company, case.reference, "PROOF_OF_PREGNANCY", on="2027-02-02")
        sch = maternity.schedule(case.__class__.objects.get(pk=case.pk), maternity.Book().rules(case.notice_date))
        self.assertEqual(sch["firstInstalmentDue"], date(2027, 2, 6))  # Wed, Thu, (Fri off), Sat
        case = maternity.record_event(self.company, case.reference, "PAY_FIRST", on="2027-02-08")
        self.assertEqual(case.status, "ON_LEAVE_PRE")
        self.assertIn("offence under s.47", case.events.get(event="PAY_FIRST").note)
        with self.assertRaises(LeaveRefused):
            maternity.record_event(self.company, case.reference, "PROOF_OF_BIRTH", on="2027-03-01")

    def test_the_register_never_shows_the_expected_delivery(self):
        out = maternity.case_out(self.open(), figures=True)
        flat = repr(out)
        self.assertNotIn("2027-06-01", flat)
        self.assertNotIn("2027-05-31", flat)  # the pre-natal end, one day before it
        self.assertEqual((out["next"]["label"], out["next"]["due"]), ("Awaiting proof of pregnancy", None))

    def test_the_employment_ban_refuses_an_early_return(self):
        case = self.open()
        clock.freeze(date(2027, 6, 10))
        maternity.record_event(self.company, case.reference, "DELIVERY", date_="2027-06-01", on="2027-06-02")
        with self.assertRaises(LeaveRefused) as caught:
            maternity.record_event(self.company, case.reference, "RETURN", on="2027-06-10")
        self.assertIn("prohibited", str(caught.exception))

    def test_a_cancelled_case_releases_the_leave_not_yet_taken(self):
        case = self.open()
        case = maternity.record_event(self.company, case.reference, "CANCEL", note="Notice withdrawn by the worker")
        self.assertEqual((case.status, case.request.status), ("CANCELLED", "CANCELLED"))
        self.assertEqual(position(self.emp, case.request.leave_type, date(2027, 4, 2), cycle=case.request.cycle).balance,
                         Decimal("0"))
        self.assertEqual(MaternityEvent.objects.filter(case=case).count(), 2)

    def test_separation_inside_the_protection_needs_an_override(self):
        self.open()
        with self.assertRaises(gated.GatedRefused) as caught:
            gated.separate(self.emp, separation_type="TERMINATION", on=TODAY_SEP, reason="Restructuring the line")
        self.assertEqual(caught.exception.status, 409)
        out = gated.separate(self.emp, separation_type="TERMINATION", on=TODAY_SEP, reason="Restructuring the line",
                             maternity_override=True)
        self.assertIn("Maternity protection", out["history"].reason)


TODAY_SEP = date(2027, 3, 8)


class StatementTests(Base):
    def test_a_quarter_with_open_attendance_needs_acknowledging(self):
        with self.assertRaises(LeaveRefused) as caught:
            statements.generate(self.company, "2027-Q1")
        self.assertEqual(caught.exception.status, 409)
        r = ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-15", "2027-03-17")
        ops.approve_request(self.company, r.reference)
        batch = statements.generate(self.company, "2027-Q1", acknowledge_unlocked=True)
        self.assertTrue(batch.unlocked_months)
        casual = next(x for x in batch.statements.get().rows if x["type"] == "CASUAL")
        self.assertEqual({k: casual[k] for k in ("opening", "earned", "taken", "other", "closing")},
                         {"opening": "0", "earned": "10", "taken": "3", "other": "0", "closing": "7"})

    def test_issue_then_acknowledge_and_the_chase_list(self):
        statements.generate(self.company, "2027-Q1", acknowledge_unlocked=True)
        s = statements.latest(self.company, "2027-Q1").statements.get()
        with self.assertRaises(LeaveRefused):
            statements.acknowledge(self.company, s.uid)
        before = statements.summary(self.company, "2027-Q1")["batch"]
        self.assertEqual((before["outstanding"], len(before["chase"])), (1, 1))
        statements.record_issue(self.company, "2027-Q1", "PRINTED")
        statements.acknowledge(self.company, s.uid)
        after = statements.summary(self.company, "2027-Q1")["batch"]
        self.assertEqual((after["issued"], after["acknowledged"], after["byMethod"]["PRINTED"]), (1, 1, 1))

    def test_a_statement_never_opens_a_cycle(self):
        statements.generate(self.company, "2027-Q1", acknowledge_unlocked=True)
        self.assertFalse(LedgerEntry.objects.filter(employee=self.emp, effective_date__year=2026).exists())


class EventTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = make_user(self.company, "owner@rahman.test")
        make_company_admin(self.admin, self.company)
        self.worker = make_user(self.company, "rahima@rahman.test")
        self.emp.user = self.worker
        self.emp.save()

    def test_a_request_notifies_approvers_and_the_decision_notifies_the_employee(self):
        r = ops.submit_request(self.company, self.emp, "CASUAL", "2027-03-15", "2027-03-16")
        self.assertTrue(Notification.objects.filter(user=self.admin, kind="LEAVE_REQUESTED").exists())
        ops.approve_request(self.company, r.reference, user=self.admin)
        self.assertTrue(Notification.objects.filter(user=self.worker, kind="LEAVE_APPROVED").exists())
        self.assertFalse(Notification.objects.filter(user=self.admin, kind="LEAVE_APPROVED").exists())
        approved = LeaveEvent.objects.get(name="LeaveApproved")
        self.assertEqual((approved.entity_ref, approved.payload["days"]), (r.reference, "2"))

    def test_a_preview_writes_no_event(self):
        ops.bulk_grant(self.company, [self.emp], "EARNED", 2, reason="Anniversary of the factory")
        self.assertFalse(LeaveEvent.objects.exists())
        ops.bulk_grant(self.company, [self.emp], "EARNED", 2, reason="Anniversary of the factory", commit=True)
        self.assertEqual(LeaveEvent.objects.filter(name="LeaveBalanceGranted").count(), 1)
