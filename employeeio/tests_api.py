"""The BD employee API (doc §9; acceptance tests 1, 11 and 14).

Test 1 is the defect that started the rewrite: loading one employee after
another merged the second into the first, so employee A's father's name, NID,
mobile number and bank account appeared under employee B. Every sub-record is
now read fresh per employee -- replaced, never merged.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase

from common import clock
from employeeio.models import Employee, EmployeeFieldHistory, EmployeeInvestment, EmployeeNominee
from employeeio.services.compliance import evaluate
from employeeio.test_support import ApiMixin, give_structure, make_company, make_employee, make_user, seed_rules, url
from companyio.models import CompanyDesignation


class ApiTestCase(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.user = make_user(cls.company, "hr@rahman.example")

    def setUp(self):
        super().setUp()
        self.api = self.client_for(self.user)

    def error_fields(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        return {e["field"] for e in response.json()["errors"]}


class ProfileIsolationTests(ApiTestCase):
    """Acceptance test 1."""

    def test_nothing_of_a_appears_under_b(self):
        a = make_employee(self.company, "EMP-0142", name_en="Md. Rafiqul Islam", name_bn="মোঃ রফিকুল ইসলাম",
                          father_name="Abdul Karim Sarder", mother_name="Rahima Khatun", nid="19907812345678901",
                          mobile="01711223344", present_address="House 12, Road 4, Mirpur")
        a.tax_profile.etin = "412998877661"
        a.tax_profile.prior_name = "Beximco Textiles"
        a.tax_profile.save()
        a.payment.bank = "Dutch-Bangla Bank"
        a.payment.account_number = "1051234567890"
        a.payment.save()
        EmployeeNominee.objects.create(employee=a, name="Salma Begum", relation="SPOUSE", share=Decimal("100"))
        EmployeeInvestment.objects.create(employee=a, instrument="SANCHAYAPATRA", amount=Decimal("123457"), proof=True)
        EmployeeFieldHistory.objects.create(employee=a, field="grade", date=date(2026, 1, 1),
                                            from_value="G6", to_value="G5", reason="Annual review 2026")
        give_structure(a, 22000)
        b = make_employee(self.company, "EMP-0164", name_en="Rehana Sultana")

        self.assertEqual(self.api.get(url(a.code)).status_code, 200)
        body_b = self.api.get(url(b.code)).json()
        text_b = json.dumps(body_b, ensure_ascii=False)
        for value in ["Abdul Karim Sarder", "Rahima Khatun", "19907812345678901", "01711223344", "Mirpur",
                      "412998877661", "Beximco", "Dutch-Bangla", "1051234567890", "Salma Begum", "123457",
                      "Annual review", "রফিকুল"]:
            with self.subTest(value=value):
                self.assertNotIn(value, text_b)
        self.assertEqual(body_b["nominees"], [])
        self.assertEqual(body_b["investments"], [])
        self.assertEqual(body_b["history"], [])
        self.assertIsNone(body_b["salary"])
        self.assertEqual(body_b["personal"]["fatherName"], "")
        for suffix, key in (("/nominees", "nominees"), ("/investments", "investments"), ("/history", "entries")):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.api.get(url(b.code, suffix)).json()[key], [])


class RosterTests(ApiTestCase):
    def test_the_roster_count_is_the_profile_count(self):
        """Acceptance test 11: one `evaluate()`, not two implementations."""
        clean = make_employee(self.company, "EMP-0001", name_en="Clean")
        give_structure(clean, 20000)
        messy = make_employee(self.company, "EMP-0002", name_en="Messy", confirmation=date(2028, 1, 1))
        messy.payment.method = "CASH"
        messy.payment.save()
        rows = {r["code"]: r for r in self.api.get(url()).json()["results"]}
        for employee in (clean, messy):
            with self.subTest(code=employee.code):
                profile = self.api.get(url(employee.code, "/compliance")).json()
                self.assertEqual(rows[employee.code]["blockerCount"], len(profile["blocks"]))
                self.assertEqual(profile["summary"]["blockCount"], len(evaluate(employee).blocks))
        self.assertEqual(rows["EMP-0001"]["blockerCount"], 0)
        self.assertEqual(rows["EMP-0002"]["blockerCount"], 3)
        self.assertEqual(rows["EMP-0001"]["grossMonthly"], "20000.00")

    def test_filters_and_search(self):
        give_structure(make_employee(self.company, "EMP-0001", name_en="Nasrin", classification="WORKER",
                                     worker_category="PERMANENT", confirmation=date(2020, 1, 1)), 20000)
        make_employee(self.company, "EMP-0002", name_en="Kamrul", classification="NON_WORKER",
                      worker_category="PROBATIONER")
        codes = lambda q: [r["code"] for r in self.api.get(url() + q).json()["results"]]  # noqa: E731
        self.assertEqual(codes("?filter=WORKER"), ["EMP-0001"])
        self.assertEqual(codes("?filter=NON_WORKER"), ["EMP-0002"])
        self.assertEqual(codes("?filter=PROBATION"), ["EMP-0002"])
        self.assertEqual(codes("?filter=BLOCKED"), ["EMP-0002"])
        self.assertEqual(codes("?q=nasr"), ["EMP-0001"])
        self.assertEqual(self.api.get(url() + "?filter=NOPE").status_code, 400)


class CreateTests(ApiTestCase):
    def test_name_in_english_is_required(self):
        response = self.api.post(url(), {"nameEn": "  "}, format="json")
        self.assertEqual(self.error_fields(response), {"f-nameEn"})
        self.assertFalse(Employee.objects.exists())

    def test_a_minimal_create_gets_the_next_code_and_blank_sub_records(self):
        first = self.api.post(url(), {"nameEn": "Nasrin Akter"}, format="json").json()
        second = self.api.post(url(), {"nameEn": "Rashed Karim"}, format="json").json()
        self.assertEqual((first["code"], second["code"]), ("EMP-0001", "EMP-0002"))
        self.assertEqual(first["statutory"]["pfNumber"], "")
        self.assertEqual(first["taxProfile"]["category"], "GENERAL")
        self.assertEqual(first["payment"]["accountNumber"], "")

    def test_a_code_is_never_reassigned(self):
        make_employee(self.company, "EMP-0142")
        response = self.api.post(url(), {"nameEn": "X", "code": "EMP-0142"}, format="json")
        self.assertEqual(self.error_fields(response), {"f-code"})
        response = self.api.patch(url("EMP-0142", "/personal"), {"code": "EMP-9999"}, format="json")
        self.assertEqual(self.error_fields(response), {"f-code"})


class ValidationErrorTests(ApiTestCase):
    """Errors are addressed by the UI's field ids so the client can focus the input."""

    def setUp(self):
        super().setUp()
        self.employee = make_employee(self.company, "EMP-0142")

    def test_personal(self):
        response = self.api.patch(url("EMP-0142", "/personal"), {"nid": "12345", "mobile": "0212"}, format="json")
        self.assertEqual(self.error_fields(response), {"f-nid", "f-mobile"})
        ok = self.api.patch(url("EMP-0142", "/personal"), {"nid": "1234567890", "nameBn": "রফিক"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["nameBn"], "রফিক")

    def test_payment(self):
        self.assertEqual(self.error_fields(self.api.patch(
            url("EMP-0142", "/payment"), {"method": "CASH"}, format="json")), {"f-cashreason"})
        self.assertEqual(self.error_fields(self.api.patch(
            url("EMP-0142", "/payment"), {"method": "MFS", "walletNumber": "123"}, format="json")), {"f-wallet"})

    def test_provident_fund_percent_states_the_range(self):
        response = self.api.patch(url("EMP-0142", "/statutory"), {"pfEmployee": "9"}, format="json")
        self.assertEqual(self.error_fields(response), {"f-pfemp"})
        self.assertIn("between 7% and 8%", response.json()["errors"][0]["messages"][0])

    def test_money_is_a_string_not_a_float(self):
        response = self.api.patch(url("EMP-0142", "/tax-profile"), {"priorIncome": 210000.5}, format="json")
        self.assertEqual(self.error_fields(response), {"f-priorinc"})
        ok = self.api.patch(url("EMP-0142", "/tax-profile"), {"priorIncome": "210000.50"}, format="json")
        self.assertEqual(ok.json()["priorIncome"], "210000.50")

    def test_nominees_must_total_100(self):
        body = {"nominees": [{"name": "Wife", "share": "60"}, {"name": "Son", "share": "30"}]}
        response = self.api.put(url("EMP-0142", "/nominees"), body, format="json")
        self.assertEqual(self.error_fields(response), {"f-nominee"})
        self.assertIn("90%", response.json()["errors"][0]["messages"][0])

    def test_nominees_are_replaced_not_merged(self):
        first = {"nominees": [{"name": "Wife", "share": "60"}, {"name": "Son", "share": "40"}]}
        self.assertEqual(self.api.put(url("EMP-0142", "/nominees"), first, format="json").status_code, 200)
        second = {"nominees": [{"name": "Mother", "relation": "MOTHER", "share": "100"}]}
        names = [n["name"] for n in self.api.put(url("EMP-0142", "/nominees"), second, format="json").json()["nominees"]]
        self.assertEqual(names, ["Mother"])

    def test_unknown_keys_are_refused_not_dropped(self):
        response = self.api.patch(url("EMP-0142", "/personal"), {"fathersName": "Typo"}, format="json")
        self.assertEqual(self.error_fields(response), {"fathersName"})


class EmploymentHistoryTests(ApiTestCase):
    def test_a_tracked_change_writes_one_entry_and_an_empty_field_says_so(self):
        employee = make_employee(self.company, "EMP-0142")
        operator = CompanyDesignation.objects.create(company=self.company, title="Machine Operator")
        response = self.api.patch(url("EMP-0142", "/employment"), {"designation": str(operator.uid)}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        history = self.api.get(url("EMP-0142", "/history")).json()
        self.assertEqual(len(history["entries"]), 1)
        self.assertEqual(history["entries"][0] | {"uid": None}, {
            "uid": None, "field": "designation", "date": "2027-03-08", "from": "", "to": "Machine Operator",
            "by": self.user.name, "reason": ""})
        grade = self.api.get(url("EMP-0142", "/history?field=grade")).json()
        self.assertEqual((grade["entries"], grade["empty"], grade["message"]), ([], True, "No grade changes recorded."))
        self.assertEqual(EmployeeFieldHistory.objects.filter(employee=employee).count(), 1)

    def test_another_companys_designation_is_not_found(self):
        make_employee(self.company, "EMP-0142")
        other = CompanyDesignation.objects.create(company=make_company("Other Ltd"), title="Spy")
        response = self.api.patch(url("EMP-0142", "/employment"), {"designation": str(other.uid)}, format="json")
        self.assertEqual(self.error_fields(response), {"f-designation"})

    def test_changing_a_classification_is_gated(self):
        make_employee(self.company, "EMP-0142", classification="WORKER")
        response = self.api.patch(url("EMP-0142", "/employment"), {"classification": "NON_WORKER"}, format="json")
        self.assertIn("gated", json.dumps(response.json()))
        self.assertEqual(Employee.objects.get(code="EMP-0142").classification, "WORKER")

    def test_history_is_append_only(self):
        employee = make_employee(self.company, "EMP-0142")
        entry = EmployeeFieldHistory.objects.create(employee=employee, field="grade", date=date(2027, 1, 1), to_value="G5")
        entry.to_value = "G4"
        with self.assertRaises(Exception):
            entry.save()
        with self.assertRaises(Exception):
            EmployeeFieldHistory.objects.filter(pk=entry.pk).update(to_value="G4")


class SalaryAndTaxEndpointTests(ApiTestCase):
    def test_the_structure_in_force_on_a_date(self):
        employee = make_employee(self.company, "EMP-0164")
        give_structure(employee, 46000, date(2025, 7, 1), date(2026, 6, 30))
        give_structure(employee, 50000, date(2026, 7, 1))
        self.assertEqual(self.api.get(url("EMP-0164", "/salary?on=2026-06-30")).json()["structure"]["gross"], "46000.00")
        self.assertEqual(self.api.get(url("EMP-0164", "/salary")).json()["structure"]["gross"], "50000.00")
        before = self.api.get(url("EMP-0164", "/salary?on=2025-01-01")).json()
        self.assertEqual((before["structure"], before["message"]), (None, "No salary structure is in force on 2025-01-01."))

    def test_the_projection_endpoint_attributes_every_figure(self):
        give_structure(make_employee(self.company, "EMP-0102", classification="NON_WORKER"), 100000)
        body = self.api.get(url("EMP-0102", "/tax-projection")).json()
        self.assertEqual(body["liability"], {"value": "45000.00", "basis": "Tax after rebate", "citation": None,
                                             "confidence": "VERIFIED"})
        self.assertEqual(body["threshold"]["confidence"], "VERIFIED")
        self.assertEqual(body["ruleSet"], "2026-27")


class FrozenClockTests(ApiTestCase):
    """Acceptance test 14: freeze the clock and every tenure, eligibility and
    deadline figure reproduces; move it and they move with it."""

    def figures(self):
        profile = self.api.get(url("EMP-0466")).json()
        projection = self.api.get(url("EMP-0466", "/tax-projection")).json()
        compliance = self.api.get(url("EMP-0466", "/compliance")).json()
        return (profile["asOf"], profile["employment"]["service"], projection["periodsElapsed"]["value"],
                [b["key"] for b in compliance["blocks"]])

    def test_figures_reproduce_on_a_frozen_date(self):
        employee = make_employee(self.company, "EMP-0466", doj=date(2020, 8, 19), confirmation=date(2027, 6, 1))
        give_structure(employee, 12800)
        first = self.figures()
        self.assertEqual(first, self.figures())
        self.assertEqual(first[1], {"totalMonths": 78, "years": 6, "months": 6, "days": 17})
        self.assertEqual(first[2], 8)
        self.assertIn("employment.confirmationFuture", first[3])

        with clock.frozen(date(2027, 6, 1)):
            later = self.figures()
        self.assertEqual(later[1], {"totalMonths": 81, "years": 6, "months": 9, "days": 13})
        self.assertEqual(later[2], 11)
        self.assertNotIn("employment.confirmationFuture", later[3])
