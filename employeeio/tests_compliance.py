"""The compliance engine (doc §3, acceptance tests 2, 4, 5, 6 and 10).

Blocks keep a person out of a payroll run; risks leave the record incomplete.
The prototype reported both as "blocks payroll" -- all sixteen records were
flagged and nobody learned anything -- and let the e-TIN item vanish whenever
the tax projection came back NaN, because NaN is neither `> 0` nor `<= 0`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from employeeio.models import EmployeeNominee
from employeeio.services.compliance import TABS, evaluate, plural
from employeeio.test_support import FrozenClockMixin, give_structure, make_company, make_employee, seed_rules
from rulebookio.models import RuleSet
from employeeio.ui import FIELD_IDS

# Every input id the Employee Profile BD front end renders.
UI_FIELDS = set(FIELD_IDS.values())


def keys(findings):
    return [f.key for f in findings]


class ComplianceTests(FrozenClockMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")

    def employee(self, code="EMP-0142", gross=None, **fields):
        employee = make_employee(self.company, code, **fields)
        if gross:
            give_structure(employee, gross)
        return employee

    def pay(self, employee, **fields):
        for k, v in fields.items():
            setattr(employee.payment, k, v)
        employee.payment.save()

    # ------------------------------------------------------------ blocks

    def test_no_structure_is_exactly_one_hard_block(self):
        """Acceptance test 2, structure half. The missing e-TIN is a risk here:
        with no pay there is nothing to withhold."""
        result = evaluate(self.employee())
        self.assertEqual(keys(result.blocks), ["salary.none"])
        self.assertIn("tax.noEtin", keys(result.risks))

    def test_e_tin_is_a_risk_while_liability_is_nil_and_a_block_once_it_is_not(self):
        """Acceptance test 4."""
        employee = self.employee(gross=30000)
        result = evaluate(employee)
        self.assertNotIn("tax.etinRequired", keys(result.blocks))
        self.assertIn("tax.noEtin", keys(result.risks))

        employee.salary_structures.get().components.filter(code="BASIC").update(amount=Decimal("200000"))
        result = evaluate(employee)
        self.assertIn("tax.etinRequired", keys(result.blocks))
        self.assertNotIn("tax.noEtin", keys(result.risks))

        employee.tax_profile.etin = "123456789012"
        employee.tax_profile.save()
        result = evaluate(employee)
        self.assertNotIn("tax.etinRequired", keys(result.blocks))
        self.assertNotIn("tax.noEtin", keys(result.risks))

    def test_unknown_liability_never_reads_as_nil(self):
        """With no tax rule set in force the item stays a block, not silence."""
        employee = self.employee(gross=30000)
        RuleSet.objects.filter(family="TAX").delete()
        result = evaluate(employee)
        self.assertIn("tax.liabilityUndetermined", keys(result.blocks))
        self.assertNotIn("tax.noEtin", keys(result.risks))

    def test_cash_with_a_reason_is_a_risk_with_the_disallowance_and_without_is_a_block(self):
        """Acceptance test 5. Cash wages are lawful; unexplained cash is not."""
        employee = self.employee(gross=20000)
        self.pay(employee, method="CASH", cash_reason="No bank branch within reach of the site")
        result = evaluate(employee)
        self.assertNotIn("payment.cashReasonMissing", keys(result.blocks))
        cash = next(f for f in result.risks if f.key == "payment.cash")
        self.assertIn("disallowed", cash.fix)
        self.assertIn("s.55", cash.fix)

        self.pay(employee, cash_reason="   ")
        result = evaluate(employee)
        self.assertIn("payment.cashReasonMissing", keys(result.blocks))
        self.assertNotIn("payment.cash", keys(result.risks))

    def test_an_invalid_wallet_blocks_an_mfs_payment(self):
        employee = self.employee(gross=20000)
        self.pay(employee, method="MFS", wallet_number="0171234")
        self.assertIn("payment.walletMissing", keys(evaluate(employee).blocks))
        self.pay(employee, wallet_number="01712345678")
        self.assertNotIn("payment.walletMissing", keys(evaluate(employee).blocks))

    def test_a_future_confirmation_date_blocks(self):
        employee = self.employee(gross=20000, confirmation=date(2027, 3, 9))
        self.assertIn("employment.confirmationFuture", keys(evaluate(employee).blocks))
        employee.confirmation = date(2027, 3, 8)
        employee.save()
        self.assertNotIn("employment.confirmationFuture", keys(evaluate(employee).blocks))

    def test_separated_with_settlement_outstanding_blocks(self):
        employee = self.employee(gross=20000, separated_on=date(2027, 2, 28), separation_type="TERMINATION")
        block = next(f for f in evaluate(employee).blocks if f.key == "salary.settlementOutstanding")
        self.assertEqual(block.label, "Separated 2027-02-28 (termination) — final settlement outstanding")
        employee.final_settlement_on = date(2027, 3, 5)
        employee.save()
        self.assertNotIn("salary.settlementOutstanding", keys(evaluate(employee).blocks))

    # ------------------------------------------------------------- risks

    def test_nominee_shares_state_the_actual_total(self):
        """Acceptance test 6."""
        employee = self.employee(gross=20000)
        EmployeeNominee.objects.create(employee=employee, name="Wife", share=Decimal("60"))
        EmployeeNominee.objects.create(employee=employee, name="Son", share=Decimal("30"))
        risk = next(f for f in evaluate(employee).risks if f.key == "personal.nomineeShares")
        self.assertEqual(risk.label, "Nominee shares do not total 100%")
        self.assertIn("Currently 90%", risk.fix)

        EmployeeNominee.objects.create(employee=employee, name="Daughter", share=Decimal("10"))
        self.assertNotIn("personal.nomineeShares", keys(evaluate(employee).risks))

    def test_no_nominee_is_a_risk_not_a_block(self):
        result = evaluate(self.employee(gross=20000))
        self.assertIn("personal.noNominee", keys(result.risks))
        self.assertNotIn("personal.noNominee", keys(result.blocks))

    def test_a_mid_year_joiner_without_prior_income_is_a_risk(self):
        employee = self.employee(gross=20000, doj=date(2026, 9, 1))
        self.assertIn("tax.priorEmployer", keys(evaluate(employee).risks))
        employee.tax_profile.prior_employer = True
        employee.tax_profile.save()
        self.assertNotIn("tax.priorEmployer", keys(evaluate(employee).risks))
        self.assertNotIn("tax.priorEmployer", keys(evaluate(self.employee("EMP-0009", gross=1, doj=date(2017, 2, 6))).risks))

    # ------------------------------------------------------------ routes

    def test_every_finding_routes_to_a_real_tab_and_field(self):
        """Acceptance test 10. `field` is None only where the UI's route is the
        tab itself: the salary structure wizard and the Actions menu."""
        employee = self.employee(confirmation=date(2027, 12, 1), separated_on=date(2027, 2, 1),
                                 separation_type="DEATH", doj=date(2026, 8, 1), nid="12")
        self.pay(employee, method="CASH", cash_reason="")
        EmployeeNominee.objects.create(employee=employee, name="A", share=Decimal("50"))
        result = evaluate(employee)
        findings = result.blocks + result.risks
        self.assertGreaterEqual(len(findings), 10)
        for finding in findings:
            with self.subTest(key=finding.key):
                self.assertIn(finding.tab, TABS)
                if finding.field is None:
                    self.assertIn(finding.key, {"salary.none", "salary.settlementOutstanding", "employment.serviceBook"})
                else:
                    self.assertIn(finding.field, UI_FIELDS)
                self.assertTrue(finding.label and finding.fix)

    # -------------------------------------------------------- tab states

    def test_tab_states(self):
        employee = self.employee(nid="1234567890", name_bn="রফিক", father_name="Karim", appointment_letter=True)
        states = evaluate(employee).tab_states
        self.assertEqual(states["salary"], "blocked")
        self.assertEqual(states["personal"], "complete")
        self.assertEqual(states["employment"], "complete")
        self.assertEqual((states["tax"], states["documents"]), ("partial", "partial"))

        give_structure(employee, 20000)
        states = evaluate(employee).tab_states
        self.assertEqual(states["salary"], "complete")

    def test_blocked_wins_over_complete(self):
        employee = self.employee(gross=20000)
        self.pay(employee, method="MFS", wallet_number="")
        self.assertEqual(evaluate(employee).tab_states["payment"], "blocked")

    def test_one_helper_agrees_singular_and_plural(self):
        self.assertEqual(plural(1, "item", "items"), "1 item")
        self.assertEqual(plural(3, "item", "items"), "3 items")
        self.assertEqual(plural(0, "item", "items"), "0 items")
        summary = evaluate(self.employee()).as_dict()["summary"]
        self.assertEqual(summary["blocks"], "1 hard block")
