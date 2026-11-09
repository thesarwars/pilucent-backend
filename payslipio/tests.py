"""Payslip and compliance (docs/backend/payslip-compliance-done.md §10): the
golden vectors P1-P22, the properties and the API.

Every rule starts signed off, so a test names the one rule it moves. The
Postgres triggers are mirrored by the model guards exercised here.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from employeeio.test_support import ApiMixin, make_user
from paylibio.models import PayComponent
from paylibio.services.library import ensure_components
from payrunio.models import RunEvent
from payrunio.services import ops as R
from payrunio.services.ops import RunRefused
from payrunio.tests import PERIOD, RunCase
from rulebookio.test_support import verify_every_rule

from .choices import LOCKED
from .models import PayslipAudit, PayslipDelivery, PayslipDocument, PayslipFinding, WagesRegister
from .services import build as B
from .services import ops as P

BASE = "/api/v1/we"


class SlipCase(RunCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        verify_every_rule()

    def set_rule(self, run, family, path, **changes):
        rs = run.rule_set if family == "LABOUR" else run.tax_card
        rs.refresh_from_db()
        node = rs.data
        for part in path.split("."):
            node = node[part]
        node.update(changes)
        rs.save(update_fields=["data"])

    def approved(self, month=PERIOD):
        self.lock(month)
        return R.approve(self.computed(month), user=self.manager)

    def paid(self, run):
        run.refresh_from_db()
        R.set_corporate_account(self.company, "BP-CITY-CSV", "1402-3399-8871", user=self.manager)
        methods = set(run.lines.filter(included=True).values_list("payment_method", flat=True))
        if "BANK_TRANSFER" in methods:
            R.instruct(run, "BP-CITY-CSV", idempotency_key=f"bank-{run.period}", user=self.manager)
        if "CASH" in methods:
            R.instruct(run, "CASH-SHEET", idempotency_key=f"cash-{run.period}", user=self.manager)
        run.refresh_from_db()
        R.mark_paid(run, list(run.lines.filter(included=True)), user=self.manager)
        run.refresh_from_db()
        self.assertEqual(run.state, "PAID")
        return run

    def slip(self, run, employee):
        return PayslipDocument.objects.get(run=run, employee=employee)

    def findings(self, doc):
        return {f.code: f for f in doc.findings.all()}

    def generated(self, *workers, **kw):
        run = self.approved()
        P.generate(run, user=self.officer)
        return run

    def released(self, *workers):
        run = self.paid(self.approved())
        P.generate(run, user=self.officer)
        P.release(run, user=self.manager)
        run.refresh_from_db()
        return run


class GoldenVectors(SlipCase):
    def test_p1_full_month_compliant(self):
        e = self.worker("W-0001")
        run = self.generated()
        doc = self.slip(run, e)
        self.assertEqual(doc.state, "ISSUABLE")
        self.assertFalse([f for f in doc.findings.all() if f.severity == "BLOCK"])
        self.assertTrue(doc.document_no.startswith("PS-2027-02-"))

    def test_p2_basic_below_the_floor_names_the_penalty(self):
        e = self.worker("W-0002")
        run = self.approved()
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=15000)
        P.generate(run, user=self.officer)
        doc = self.slip(run, e)
        f = self.findings(doc)["MIN_WAGE_BASIC"]
        self.assertEqual((doc.state, f.severity), ("BLOCKED", "BLOCK"))
        self.assertIn("s.289(1)", f.citation)
        self.assertIn("50,000", f.message)

    def test_p3_joined_on_the_20th_rate_above_the_floor(self):
        e = self.worker("W-0003", doj=date(2027, 2, 20))
        run = self.generated()
        doc = self.slip(run, e)
        self.assertLess(doc.gross, Decimal(6700))  # a part month, below any floor
        codes = self.findings(doc)
        self.assertNotIn("MIN_WAGE_BASIC", codes)
        self.assertNotIn("MIN_WAGE_TOTAL", codes)
        self.assertEqual(codes["PRORATED"].severity, "INFO")

    def test_p4_joined_on_the_20th_rate_below_the_floor(self):
        e = self.worker("W-0004", doj=date(2027, 2, 20))
        run = self.approved()
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=15000)
        P.generate(run, user=self.officer)
        self.assertIn("MIN_WAGE_BASIC", self.findings(self.slip(run, e)))

    def test_p5_a_dependency_rule_drafted_blocks_every_slip(self):
        a, b = self.worker("W-0005"), self.worker("W-0006", gross=30000)
        run = self.approved()
        self.set_rule(run, "TAX", "slabs", confidence="DRAFTED")
        P.generate(run, user=self.officer)
        for e in (a, b):
            f = self.findings(self.slip(run, e))["UNVERIFIED_RULE"]
            self.assertEqual(f.severity, "BLOCK")
            self.assertIn("slabs (drafted)", f.message)

    def test_p5b_the_gate_reads_what_the_computation_read(self):
        """§11 question 2: a dependency outside the old list of four is gated."""
        e = self.worker("W-0007")
        run = self.approved()
        self.set_rule(run, "LABOUR", "festivalBonusesPerYear", confidence="CORROBORATED")
        P.generate(run, user=self.officer)
        self.assertIn("festivalBonusesPerYear (corroborated)", self.findings(self.slip(run, e))["UNVERIFIED_RULE"].message)

    def test_p6_ceiling_is_on_wages_not_gross(self):
        ensure_components(self.company)
        PayComponent.objects.filter(company=self.company, code="MED").update(in_wages_base=False)
        e = self.worker("W-0008", gross=100000)
        run = self.approved()
        self.set_rule(run, "LABOUR", "aggregateDeductionCapPercent", value=1)
        P.generate(run, user=self.officer)
        doc = self.slip(run, e)
        self.assertEqual(doc.deduction_ceiling, (doc.wages_base / 100).quantize(B.FOUR))
        self.assertLess(doc.wages_base, doc.gross)
        self.assertEqual(self.findings(doc)["DEDUCTION_CEILING"].severity, "BLOCK")

    def test_p7_notional_perquisite_is_not_wages(self):
        e = self.worker("W-0009", gross=100000)
        e.tax_profile.vehicle = "UPTO_2500"
        e.tax_profile.save()
        run = self.generated()
        doc = self.slip(run, e)
        self.assertGreater(doc.non_cash_earnings, 0)
        self.assertLess(doc.wages_base, doc.gross + doc.non_cash_earnings)

    def test_p8_perquisite_at_80_percent_warns_with_employer_wording(self):
        e = self.worker("W-0010", gross=100000)
        e.tax_profile.vehicle = "UPTO_2500"
        e.tax_profile.save()
        run = self.approved()
        line = self.line(run, e)
        ctx = P.Context(run)
        annual = B.bases(line, ctx.flags)[2] + B.notional_perquisites(line.tax_derivation_json)
        self.set_rule(run, "TAX", "perquisiteCeilingPerEmployee", value=str((annual / Decimal("0.85")).quantize(B.FOUR)))
        P.generate(run, user=self.officer)
        doc = self.slip(run, e)
        f = self.findings(doc)["PERQUISITE_80PCT"]
        self.assertEqual(f.severity, "WARN")
        self.assertIn("disallowed to the employer", f.message)
        self.assertIn("tax is unaffected", f.message)
        self.assertEqual(doc.state, "ISSUABLE")
        self.assertEqual(doc.deductions_json[0]["amount"], line.deductions_json[0]["amount"])

    def test_p9_cash_warns_and_is_still_issuable(self):
        e = self.worker("W-0011", method="CASH")
        run = self.generated()
        doc = self.slip(run, e)
        f = self.findings(doc)["CASH_PAYMENT"]
        self.assertEqual((f.severity, doc.state), ("WARN", "ISSUABLE"))
        self.assertIn("s.55", f.citation)

    def test_p10_amount_in_words_in_bangla(self):
        e = self.worker("W-0012")
        doc = self.slip(self.generated(), e)
        self.assertIn("টাকা", doc.net_in_words_bn)
        self.assertIn("বিশ হাজার", doc.net_in_words_bn)
        self.assertIn("taka", doc.net_in_words.lower())

    def test_p11_release_with_one_blocked_is_refused_and_lists_them(self):
        low, high = self.worker("W-0013"), self.worker("W-0014", gross=30000)
        run = self.paid(self.approved())
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=15000)
        P.generate(run, user=self.officer)
        with self.assertRaises(RunRefused) as caught:
            P.release(run, user=self.manager)
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual([b["employee"] for b in caught.exception.detail["blocked"]], [low.code])
        self.assertFalse(PayslipDocument.objects.filter(run=run, state__in=LOCKED).exists())
        self.assertFalse(WagesRegister.objects.filter(run=run).exists())
        run.refresh_from_db()
        self.assertEqual(run.state, "PAID")
        self.assertEqual(self.slip(run, high).state, "ISSUABLE")

    def test_p12_issued_slip_edited(self):
        e = self.worker("W-0015")
        doc = self.slip(self.released(), e)
        doc.net_pay += 1
        with self.assertRaises(ValidationError):
            doc.save()
        with self.assertRaises(ValidationError):
            PayslipDocument.objects.filter(pk=doc.pk).update(gross=1)

    def test_p13_issued_slip_deleted_cites_retention(self):
        e = self.worker("W-0016")
        doc = self.slip(self.released(), e)
        with self.assertRaises(ValidationError) as caught:
            doc.delete()
        self.assertIn(str(doc.retention_until), str(caught.exception))
        with self.assertRaises(ValidationError):
            PayslipDocument.objects.filter(pk=doc.pk).delete()

    def test_p14_regenerate_after_issue_touches_nothing(self):
        e = self.worker("W-0017")
        run = self.released()
        before = self.slip(run, e)
        self.assertEqual(P._rebuild(run, self.officer), [])
        after = self.slip(run, e)
        self.assertEqual((after.pk, after.document_hash, after.updated_at),
                         (before.pk, before.document_hash, before.updated_at))
        with self.assertRaises(RunRefused) as caught:
            P.generate(run, user=self.officer)
        self.assertEqual(caught.exception.status, 409)

    def test_p15_a_register_that_disagrees_is_refused(self):
        self.worker("W-0018")
        run = self.generated()
        with self.assertRaises(ValidationError):
            WagesRegister(company=run.company, site=run.site, run=run, period=run.period, row_count=1,
                          total_gross=1, total_deductions=0, total_net=1, register_hash="x", generated_by=self.manager,
                          retention_until=date(2032, 1, 1)).save()

    def test_p16_correction_is_a_new_document_and_both_stay(self):
        e = self.worker("W-0019")
        old = self.slip(self.released(), e)
        march = date(2027, 3, 1)
        self.lock(march)
        adj = self.open_run(march)
        type(adj).objects.filter(pk=adj.pk).update(run_type="ADJUSTMENT")
        adj.refresh_from_db()
        adj, _ = R.compute(adj, user=self.officer)
        adj = R.approve(adj, user=self.manager)
        new = P.supersede(old, new_run=adj, reason="Overtime corrected against the register", user=self.manager)
        old.refresh_from_db()
        self.assertEqual((old.state, old.superseded_by), ("SUPERSEDED", new))
        self.assertEqual(new.state, "ISSUED")
        self.assertNotEqual(new.document_no, old.document_no)
        self.assertTrue(new.document_hash)
        self.assertEqual(PayslipDocument.objects.filter(employee=e).count(), 2)
        self.assertTrue(PayslipAudit.objects.filter(payslip_uid=old.uid, action="SUPERSEDED").exists())

    def test_p16b_only_an_adjustment_run_corrects(self):
        e = self.worker("W-0020")
        old = self.slip(self.released(), e)
        with self.assertRaises(RunRefused):
            P.supersede(old, new_run=old.run, reason="Wrong kind of run entirely", user=self.manager)

    def test_p17_a_block_cannot_be_accepted(self):
        e = self.worker("W-0021")
        run = self.approved()
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=15000)
        P.generate(run, user=self.officer)
        doc = self.slip(run, e)
        f = self.findings(doc)["MIN_WAGE_BASIC"]
        with self.assertRaises(RunRefused) as caught:
            P.resolve(doc, f.uid, resolution="ACCEPTED", reason="Management agrees to this", user=self.manager)
        self.assertEqual(caught.exception.status, 422)

    def test_p18_gaps_are_preserved(self):
        e = self.worker("W-0022", gross=100000)
        stages = [s["stage"] for s in self.slip(self.generated(), e).derivation_json]
        self.assertEqual(stages, [1, 2, 2, 3, 4, 5, 6, 8, 10, 10])

    def test_p18b_minimum_tax_and_deducted_to_date_fill_the_gaps(self):
        d = {k: {"value": v, "basis": ""} for k, v in {
            "employmentIncome": "1", "exemption": "1", "taxable": "1", "threshold": "1", "slabTax": "1", "rebate": "0",
            "afterRebate": "1", "liability": "5000", "ytdDeducted": "100", "remainingPeriods": 3,
            "periodDeduction": "1"}.items()}
        self.assertEqual([s["stage"] for s in B.derivation({**d, "available": True})],
                         [1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10])

    def test_p19_a_stage_with_a_result_numbers_once(self):
        e = self.worker("W-0023", gross=100000)
        steps = self.slip(self.generated(), e).derivation_json
        two = [s for s in steps if s["stage"] == 2]
        self.assertEqual([bool(s.get("isResult")) for s in two], [False, True])
        self.assertEqual(two[1]["label"], "Taxable income")

    def test_p20_reproducing_gives_the_hash(self):
        e = self.worker("W-0024", gross=100000)
        doc = PayslipDocument.objects.select_related("rule_set", "tax_card").get(pk=self.slip(self.released(), e).pk)
        self.assertEqual(B.document_hash(doc), doc.document_hash)

    def test_p21_retention_is_never_shortened(self):
        e = self.worker("W-0025")
        run = self.released()
        doc = self.slip(run, e)
        self.assertEqual(doc.retention_until.year, doc.issued_at.year + 5)
        doc.retention_until = doc.retention_until + timedelta(days=30)
        doc.save()  # a dispute extends it
        doc.retention_until = doc.retention_until - timedelta(days=60)
        with self.assertRaises(ValidationError):
            doc.save()
        reg = run.wages_register
        reg.retention_until = reg.retention_until - timedelta(days=1)
        with self.assertRaises(ValidationError):
            reg.save()

    def test_p22_every_slip_reconciles(self):
        for n, gross in enumerate((20000, 55000, 100000, 300000)):
            self.worker(f"W-010{n}", gross=gross, doj=date(2027, 2, 10) if n == 1 else date(2020, 1, 1))
        run = self.generated()
        docs = PayslipDocument.objects.filter(run=run)
        self.assertEqual(docs.count(), 4)
        for d in docs:
            self.assertEqual(B._sum(d.earnings_json) - B._sum(d.deductions_json), d.net_pay)


class Properties(SlipCase):
    def test_release_writes_the_register_from_the_slips_and_closes_the_run(self):
        a, b = self.worker("W-0201"), self.worker("W-0202", gross=30000)
        run = self.released()
        self.assertEqual(run.state, "CLOSED")
        reg = run.wages_register
        docs = PayslipDocument.objects.filter(run=run)
        self.assertEqual(reg.row_count, 2)
        self.assertEqual(reg.total_net, sum(d.net_pay for d in docs))
        self.assertEqual(reg.total_net, run.total_net)
        self.assertEqual(reg.register_hash, B.register_hash(docs))
        ev = RunEvent.objects.get(run=run, name="PayslipsReleased")
        self.assertEqual(Decimal(ev.payload["totalTax"]), run.total_tax)
        self.assertTrue(RunEvent.objects.filter(run=run, name="WagesRegisterGenerated").exists())

    def test_release_rechecks_the_gate(self):
        e = self.worker("W-0203")
        run = self.paid(self.approved())
        P.generate(run, user=self.officer)
        self.assertEqual(self.slip(run, e).state, "ISSUABLE")
        self.set_rule(run, "TAX", "minimumTax", confidence="DISPUTED")
        with self.assertRaises(RunRefused):
            P.release(run, user=self.manager)

    def test_regeneration_keeps_number_and_id_and_an_accepted_warning(self):
        e = self.worker("W-0204", method="CASH")
        run = self.generated()
        doc = self.slip(run, e)
        P.resolve(doc, self.findings(doc)["CASH_PAYMENT"].uid, resolution="ACCEPTED",
                  reason="Cash is agreed for this worker", user=self.manager)
        P.generate(run, user=self.officer)
        again = self.slip(run, e)
        self.assertEqual((again.uid, again.document_no), (doc.uid, doc.document_no))
        self.assertTrue(self.findings(again)["CASH_PAYMENT"].resolved)

    def test_fixed_upstream_regenerates_and_refuses_if_it_still_stands(self):
        e = self.worker("W-0205")
        run = self.approved()
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=15000)
        P.generate(run, user=self.officer)
        doc = self.slip(run, e)
        f = self.findings(doc)["MIN_WAGE_BASIC"]
        with self.assertRaises(RunRefused):
            P.resolve(doc, f.uid, resolution="FIXED_UPSTREAM", reason="Structure was revised", user=self.manager)
        self.assertEqual(self.slip(run, e).state, "BLOCKED")
        self.set_rule(run, "LABOUR", "gradeWageFloorDefault", value=6700)
        P.resolve(doc, f.uid, resolution="FIXED_UPSTREAM", reason="Floor corrected in the rule book", user=self.manager)
        self.assertEqual(self.slip(run, e).state, "ISSUABLE")

    def test_generate_before_approval_is_refused(self):
        self.worker("W-0206")
        self.lock()
        with self.assertRaises(RunRefused) as caught:
            P.generate(self.computed(), user=self.officer)
        self.assertEqual(caught.exception.status, 409)

    def test_every_finding_needs_a_citation(self):
        e = self.worker("W-0207")
        doc = self.slip(self.generated(), e)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayslipFinding.objects.create(company=doc.company, payslip=doc, severity="WARN", code="X", message="m",
                                          citation="   ")

    def test_issued_without_an_issuer_cannot_exist(self):
        e = self.worker("W-0208")
        doc = self.slip(self.generated(), e)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayslipDocument.objects.filter(pk=doc.pk).update(state="ISSUED")

    def test_audit_is_append_only(self):
        a = PayslipAudit.objects.create(company=self.company, action="VIEWED")
        a.reason = "x"
        with self.assertRaises(ValidationError):
            a.save()
        with self.assertRaises(ValidationError):
            a.delete()

    def test_delivery_moves_issued_to_delivered_and_masks(self):
        e = self.worker("W-0209")
        doc = self.slip(self.released(), e)
        P.deliver(doc, channel="EMAIL", destination="worker@rahman.test", user=self.manager)
        doc.refresh_from_db()
        self.assertEqual(doc.state, "DELIVERED")
        self.assertEqual(PayslipDelivery.objects.get(payslip=doc).destination, "w***@rahman.test")
        P.deliver(doc, channel="HANDED", destination="", user=self.manager)
        self.assertEqual(doc.deliveries.count(), 2)


class Api(ApiMixin, SlipCase):
    def setUp(self):
        super().setUp()
        self.b = self.client_for(self.manager)

    def test_the_whole_way(self):
        e = self.worker("W-0301")
        run = self.paid(self.approved())
        u = str(run.uid)
        r = self.b.post(f"{BASE}/payroll-runs/{u}/payslips/generate")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["issuable"], 1)

        roster = self.b.get(f"{BASE}/payslips", {"run": u}).json()
        self.assertEqual(roster["run"]["uid"], u)
        self.assertEqual(roster["rows"][0]["code"], e.code)
        slip = roster["rows"][0]["uid"]

        d = self.b.get(f"{BASE}/payslips/{slip}").json()
        self.assertEqual(d["derivation"][0]["stage"], 1)
        self.assertTrue(PayslipAudit.objects.filter(payslip_uid=slip, action="VIEWED").exists())

        preview = self.b.get(f"{BASE}/wages-registers/{u}").json()
        self.assertFalse(preview["issued"])

        r = self.b.post(f"{BASE}/payroll-runs/{u}/payslips/release")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["state"], "CLOSED")

        reg = self.b.get(f"{BASE}/wages-registers/{u}").json()
        self.assertTrue(reg["issued"])
        self.assertTrue(reg["reconciled"]["ok"])
        self.b.get(f"{BASE}/wages-registers/{u}")
        self.assertEqual(PayslipAudit.objects.filter(run_uid=u, action="REGISTER_GENERATED").count(), 1)

        d = self.b.get(f"{BASE}/payslips/{slip}").json()
        self.assertEqual(d["state"], "ISSUED")
        self.assertTrue(d["hashVerified"])

        pdf = self.b.get(f"{BASE}/payslips/{slip}", {"format": "pdf", "lang": "bn"})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_the_run_close_goes_through_the_gate(self):
        self.worker("W-0302")
        run = self.paid(self.approved())
        self.set_rule(run, "TAX", "slabs", confidence="DRAFTED")
        r = self.b.post(f"{BASE}/payroll-runs/{run.uid}/release")
        self.assertEqual(r.status_code, 422, r.content)
        self.assertEqual(r.json()["detail"]["blocked"][0]["employee"], "W-0302")
        run.refresh_from_db()
        self.assertEqual(run.state, "PAID")

    def test_release_before_paid_is_409(self):
        self.worker("W-0303")
        run = self.approved()
        self.assertEqual(self.b.post(f"{BASE}/payroll-runs/{run.uid}/payslips/release").status_code, 409)

    def test_an_employee_reads_only_their_own_issued_slip(self):
        mine, other = self.worker("W-0304"), self.worker("W-0305")
        person = make_user(self.company, "w304@rahman.test")
        type(mine).objects.filter(pk=mine.pk).update(user=person)
        c = self.client_for(person)
        run = self.paid(self.approved())
        P.generate(run, user=self.officer)
        draft = self.slip(run, mine)
        self.assertEqual(c.get(f"{BASE}/payslips/{draft.uid}").status_code, 403)
        P.release(run, user=self.manager)
        self.assertEqual(c.get(f"{BASE}/payslips/{draft.uid}").status_code, 200)
        self.assertEqual(c.get(f"{BASE}/payslips/{self.slip(run, other).uid}").status_code, 403)
        rows = c.get(f"{BASE}/payslips").json()["rows"]
        self.assertEqual([r["code"] for r in rows], [mine.code])
        self.assertEqual(c.get(f"{BASE}/wages-registers/{run.uid}").status_code, 403)
        self.assertEqual(c.post(f"{BASE}/payroll-runs/{run.uid}/payslips/generate").status_code, 403)

    def test_another_company_sees_nothing(self):
        from employeeio.test_support import make_company, make_company_admin

        e = self.worker("W-0306")
        run = self.generated()
        other = make_company("Other")
        user = make_user(other, "x@other.test")
        make_company_admin(user, other)
        c = self.client_for(user)
        self.assertEqual(c.get(f"{BASE}/payslips/{self.slip(run, e).uid}").status_code, 404)
        self.assertEqual(c.get(f"{BASE}/payslips").json()["rows"], [])
