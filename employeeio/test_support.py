"""Builders for the BD employee tests. Nothing here is imported by production code.

The as-of date and the salary structure shape follow the front end's
`fixtures.js`, so a figure checked here is the figure the UI shows.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import User
from common import clock
from common.django_rest.permissions.company_subscription import HaveSubscription
from companyio.models import Company, CompanyUser
from employeeio.models import Employee, EmployeeSalaryComponent, EmployeeSalaryStructure
from rulebookio.test_support import seed_rules  # noqa: F401 -- re-exported for the employee tests

AS_OF = date(2027, 3, 8)


def make_company(name):
    return Company.objects.create(name=name)


def make_user(company, email):
    user = User.objects.create_user(name=email.split("@")[0], email=email, password="pass1234!")
    CompanyUser.objects.create(user=user, company=company)
    return user


def make_employee(company, code, name_en="Test Employee", **fields):
    return Employee.objects.create(company=company, code=code, name_en=name_en, **fields)


def _round(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def give_structure(employee, gross, effective_from=date(2026, 7, 1), effective_to=None):
    """The Standard 60/50 template: medical 6%, conveyance 4%, house rent 50% of
    a 60% basic, and basic as the balancing component so the parts sum to gross."""
    gross = Decimal(gross)
    med, conv = _round(gross * Decimal("0.06")), _round(gross * Decimal("0.04"))
    hra = _round(_round(gross * Decimal("0.6")) * Decimal("0.5"))
    basic = gross - hra - med - conv
    structure = EmployeeSalaryStructure.objects.create(
        employee=employee, effective_from=effective_from, effective_to=effective_to, template="Standard 60/50",
    )
    for position, (code, amount) in enumerate([("BASIC", basic), ("HRA", hra), ("MED", med), ("CONV", conv)]):
        EmployeeSalaryComponent.objects.create(structure=structure, code=code, amount=amount, position=position)
    return structure


class FrozenClockMixin:
    """Every test runs on the fixture date (doc §11 test 14)."""

    frozen_on = AS_OF

    def setUp(self):
        super().setUp()
        clock.freeze(self.frozen_on)
        self.addCleanup(clock.unfreeze)


class ApiMixin(FrozenClockMixin):
    """An authenticated client past the subscription gate, which these tests do
    not exercise. Tenancy is still real: `get_active_company()` resolves the
    user's own membership."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(HaveSubscription, "has_permission", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        # SECURE_SSL_REDIRECT would 301 every plain-http test request.
        no_ssl_redirect = override_settings(SECURE_SSL_REDIRECT=False)
        no_ssl_redirect.enable()
        self.addCleanup(no_ssl_redirect.disable)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


def url(code=None, suffix=""):
    base = "/api/v1/we/employees"
    return f"{base}/{code}{suffix}" if code else base
