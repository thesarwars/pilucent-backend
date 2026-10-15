"""Employee documents and withholding deadlines (doc §7.6, §9, §10).

The prototype's Actions menu toasted "Service book generated" and generated
nothing, so the "service book not generated" risk could never clear; and its
legal documents carried amounts in words for exactly two amounts.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from common import clock
from companyio.models import CompanyDesignation
from employeeio.models import EmployeeDocument
from employeeio.services.compliance import evaluate
from employeeio.services.withholding import deposit_due, late_deposit_charge, next_quarterly_return
from employeeio.test_support import (
    AS_OF,
    ApiMixin,
    FrozenClockMixin,
    give_structure,
    make_company,
    make_employee,
    give_salary_permissions,
    make_user,
    seed_rules,
    url,
)
from rulebookio.book import rule_book


class DocumentTests(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.user = make_user(cls.company, "hr@rahman.example")
        give_salary_permissions(cls.user, cls.company, "view_salary_figures")
        cls.designation = CompanyDesignation.objects.create(company=cls.company, title="Sewing Operator")

    def setUp(self):
        super().setUp()
        self.api = self.client_for(self.user)
        self.employee = make_employee(self.company, "EMP-0142", name_en="Md. Rafiqul Islam", doj=date(2019, 3, 11))
        give_structure(self.employee, 22000)

    def issue(self, kind):
        return self.api.post(url("EMP-0142", f"/documents/{kind}"), {}, format="json")

    def complete(self, **fields):
        defaults = dict(father_name="Abdul Karim", mother_name="Rahima Khatun", nid="19907812345678901",
                        permanent_address="Village Char Kalia, Sirajganj", designation=self.designation,
                        photo="employees/photos/emp-0142.jpg")
        for key, value in {**defaults, **fields}.items():
            setattr(self.employee, key, value)
        self.employee.save()

    def test_a_document_is_refused_with_the_fields_it_needs(self):
        response = self.issue("service-book")
        self.assertEqual(response.status_code, 400)
        fields = [e["field"] for e in response.json()["errors"]]
        self.assertEqual(fields, ["f-fatherName", "f-motherName", "f-nid", "f-permAddr"])
        listing = self.api.get(url("EMP-0142", "/documents")).json()
        service_book = next(k for k in listing["kinds"] if k["kind"] == "SERVICE_BOOK")
        self.assertEqual((service_book["issued"], service_book["ready"]), (False, False))
        self.assertEqual(self.api.post(url("EMP-0142", "/documents/payslip"), {}, format="json").status_code, 404)

    def test_the_service_book_clears_its_risk_and_states_amounts_in_both_languages(self):
        self.assertIn("employment.serviceBook", [f.key for f in evaluate(self.employee).risks])
        self.complete()
        response = self.issue("service-book")
        self.assertEqual(response.status_code, 201, response.content)
        content = response.json()["content"]
        self.assertEqual(content["wage"]["gross"]["words"],
                         {"en": "Twenty two thousand taka only", "bn": "বাইশ হাজার টাকা মাত্র"})
        self.assertEqual(content["wage"]["gross"]["display"]["bn"], "৳ ২২,০০০")
        basic = content["wage"]["components"][0]
        self.assertEqual((basic["code"], basic["basis"]), ("BASIC", "60% of gross"))
        self.assertEqual(content["employee"]["fatherName"], "Abdul Karim")
        self.assertEqual(content["citation"], "Bangladesh Labour Act 2006, s.6, s.7")
        self.assertNotIn("employment.serviceBook", [f.key for f in evaluate(self.employee).risks])

    def test_the_appointment_letter_and_id_card_set_their_flags(self):
        self.complete()
        self.assertIn("employment.noAppointmentLetter", [f.key for f in evaluate(self.employee).risks])
        self.assertEqual(self.issue("appointment-letter").status_code, 201)
        card = self.issue("id-card").json()
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.appointment_letter)
        self.assertEqual((self.employee.id_card, self.employee.id_card_date), (True, AS_OF))
        self.assertNotIn("employment.noAppointmentLetter", [f.key for f in evaluate(self.employee).risks])
        self.assertEqual(card["content"]["employee"]["photo"], "/media/employees/photos/emp-0142.jpg")

    def test_a_reissue_is_a_new_version_and_the_old_one_stays(self):
        self.complete()
        first = self.issue("service-book").json()
        second = self.issue("service-book").json()
        self.assertEqual((first["version"], second["version"]), (1, 2))
        self.assertEqual(EmployeeDocument.objects.filter(employee=self.employee).count(), 2)
        with self.assertRaises(Exception):
            EmployeeDocument.objects.get(uid=first["uid"]).delete()
        listing = self.api.get(url("EMP-0142", "/documents")).json()
        service_book = next(k for k in listing["kinds"] if k["kind"] == "SERVICE_BOOK")
        self.assertEqual(service_book["latest"]["version"], 2)

    def test_the_id_card_needs_a_photograph(self):
        self.complete(photo="")
        response = self.issue("id-card")
        self.assertEqual([e["field"] for e in response.json()["errors"]], ["f-photo"])


class WithholdingTests(FrozenClockMixin, TestCase):
    """§7.6."""

    @classmethod
    def setUpTestData(cls):
        seed_rules()

    def setUp(self):
        super().setUp()
        self.book = rule_book(AS_OF)

    def test_deposit_within_two_weeks_and_june_the_same_day(self):
        self.assertEqual(deposit_due(date(2027, 2, 1), self.book), date(2027, 3, 14))
        self.assertEqual(deposit_due(date(2027, 6, 1), rule_book(date(2027, 6, 30))), date(2027, 6, 30))

    def test_late_deposit_is_two_percent_a_month_capped_at_twenty_four(self):
        due = date(2027, 3, 14)
        self.assertEqual(late_deposit_charge(Decimal("10000"), due, due, self.book).value, 0)
        # Two whole months and six days: a started month counts.
        self.assertEqual(late_deposit_charge(Decimal("10000"), due, date(2027, 5, 20), self.book).value, 600)
        self.assertEqual(late_deposit_charge(Decimal("10000"), due, date(2031, 1, 1), self.book).value, 4800)

    def test_the_next_quarterly_return(self):
        self.assertEqual(next_quarterly_return(AS_OF, self.book)["due"], "2027-04-25")
        self.assertEqual(next_quarterly_return(AS_OF, self.book)["quarterEnds"], "2027-03-31")
        late = next_quarterly_return(date(2026, 10, 26), self.book)
        self.assertEqual((late["quarterEnds"], late["due"]), ("2026-12-31", "2027-01-25"))


class ProjectionDeadlineTests(ApiMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()
        cls.company = make_company("Rahman Garments")
        cls.user = make_user(cls.company, "hr@rahman.example")
        give_salary_permissions(cls.user, cls.company, "view_salary_figures")

    def test_the_projection_says_when_the_deduction_is_due(self):
        give_structure(make_employee(self.company, "EMP-0102", classification="NON_WORKER"), 100000)
        body = self.client_for(self.user).get(url("EMP-0102", "/tax-projection")).json()
        withholding = body["withholding"]
        self.assertTrue(withholding["available"])
        self.assertEqual(withholding["depositDue"]["value"], "2027-04-14")  # March 2027
        self.assertEqual(withholding["depositDue"]["confidence"], "VERIFIED")
        self.assertEqual(withholding["quarterlyReturn"]["due"], "2027-04-25")

    def test_a_tax_year_with_no_rule_set_says_so_instead_of_failing(self):
        make_employee(self.company, "EMP-0103")
        with clock.frozen(date(2027, 7, 15)):  # rules.js has no 2027-28 set
            response = self.client_for(self.user).get(url("EMP-0103", "/tax-projection"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["withholding"]["available"])
