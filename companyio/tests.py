"""Shift uniqueness must be per-company and ignore soft-deleted shifts."""

from types import SimpleNamespace

from django.test import TestCase

from accounts.models import User
from companyio.choices import (
    CompanyDepartmentStatusChoices,
    CompanyDesignationStatusChoices,
    CompanyShiftStatusChoices,
)
from companyio.models import (
    Company,
    CompanyDepartment,
    CompanyDesignation,
    CompanyShift,
    CompanyUser,
)

from weapi.django_rest.serializers.company_shifts import (
    PrivateWeCompanyShiftListSerializer,
)
from weapi.django_rest.serializers.company_departments import (
    PrivateWeCompanyDepartmenListSerializer,
)
from weapi.django_rest.serializers.company_designations import (
    PrivateWeCompanyDesignationDetailsSerializer,
    PrivateWeCompanyDesignationListSerializer,
)


def _payload(title="Morning"):
    return {
        "title": title, "status": "ACTIVE", "code": "1101", "kind": "DAY",
        "in_time": "09:00", "out_time": "17:00",
    }


class ShiftUniquenessTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="A")
        self.company_b = Company.objects.create(name="B")
        self.user_a = User.objects.create(email="a@x.test", password="x")
        CompanyUser.objects.create(company=self.company_a, user=self.user_a)

    def _serializer(self, title="Morning"):
        request = SimpleNamespace(user=self.user_a)
        return PrivateWeCompanyShiftListSerializer(
            data=_payload(title), context={"request": request}
        )

    def _shift(self, company, title="Morning", status=CompanyShiftStatusChoices.ACTIVE):
        return CompanyShift.objects.create(
            company=company, title=title, code="1", status=status,
            in_time="09:00", out_time="17:00",
        )

    def test_same_title_in_another_company_is_allowed(self):
        self._shift(self.company_b)  # another tenant has "Morning"
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)

    def test_duplicate_active_title_in_same_company_is_blocked(self):
        self._shift(self.company_a, status=CompanyShiftStatusChoices.ACTIVE)
        s = self._serializer()
        self.assertFalse(s.is_valid())
        self.assertIn("Shift already exists.", str(s.errors))

    def test_non_active_same_title_does_not_block(self):
        # Only ACTIVE shifts reserve a title; removed/inactive/draft don't.
        self._shift(self.company_a, status=CompanyShiftStatusChoices.REMOVED)
        self._shift(self.company_a, status=CompanyShiftStatusChoices.IN_ACTIVE)
        self._shift(self.company_a, status=CompanyShiftStatusChoices.DRAFT)
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)


class DepartmentUniquenessTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="A")
        self.company_b = Company.objects.create(name="B")
        self.user_a = User.objects.create(email="d@x.test", password="x")
        CompanyUser.objects.create(company=self.company_a, user=self.user_a)

    def _serializer(self):
        request = SimpleNamespace(user=self.user_a)
        return PrivateWeCompanyDepartmenListSerializer(
            data={"title": "Sales", "code": "D1"}, context={"request": request}
        )

    def test_same_title_in_another_company_is_allowed(self):
        CompanyDepartment.objects.create(company=self.company_b, title="Sales", code="9")
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)

    def test_duplicate_active_title_in_same_company_is_blocked(self):
        CompanyDepartment.objects.create(company=self.company_a, title="Sales", code="9")
        s = self._serializer()
        self.assertFalse(s.is_valid())
        self.assertIn("Department already exists.", str(s.errors))

    def test_non_active_same_title_is_reusable(self):
        CompanyDepartment.objects.create(
            company=self.company_a, title="Sales", code="9",
            status=CompanyDepartmentStatusChoices.REMOVED,
        )
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)


class DesignationUniquenessTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="A")
        self.company_b = Company.objects.create(name="B")
        self.user_a = User.objects.create(email="g@x.test", password="x")
        CompanyUser.objects.create(company=self.company_a, user=self.user_a)

    def _ctx(self):
        return {"request": SimpleNamespace(user=self.user_a)}

    def test_same_title_in_another_company_is_allowed(self):
        CompanyDesignation.objects.create(company=self.company_b, title="Manager")
        s = PrivateWeCompanyDesignationListSerializer(
            data={"title": "Manager", "code": "M1"}, context=self._ctx()
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_update_with_unchanged_title_does_not_self_collide(self):
        designation = CompanyDesignation.objects.create(
            company=self.company_a, title="Manager"
        )
        s = PrivateWeCompanyDesignationDetailsSerializer(
            instance=designation, data={"title": "Manager"},
            partial=True, context=self._ctx(),
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_update_to_another_existing_title_is_blocked(self):
        CompanyDesignation.objects.create(company=self.company_a, title="Manager")
        lead = CompanyDesignation.objects.create(company=self.company_a, title="Lead")
        s = PrivateWeCompanyDesignationDetailsSerializer(
            instance=lead, data={"title": "Manager"},
            partial=True, context=self._ctx(),
        )
        self.assertFalse(s.is_valid())

    def test_non_active_same_title_is_reusable(self):
        CompanyDesignation.objects.create(
            company=self.company_a, title="Manager",
            status=CompanyDesignationStatusChoices.REMOVED,
        )
        s = PrivateWeCompanyDesignationListSerializer(
            data={"title": "Manager", "code": "M1"}, context=self._ctx()
        )
        self.assertTrue(s.is_valid(), s.errors)
