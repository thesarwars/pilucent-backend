"""The sale change form must not render FK dropdowns.

ChartOfAccount.__str__ dereferences self.company, so every <option> in an
account dropdown costs a query. With 3,576 accounts across two fields that was
~7,152 queries for one page load -- the reason the change page hung.
"""

from datetime import date

from django.contrib.admin.sites import site
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import RequestFactory, TestCase

from accounts.models import ChartOfAccount
from companyio.models import Company
from customerio.models import Customer
from salesio.admin import (
    SaleAdmin,
    SaleItemAdmin,
    SalePaymentReceiveAdmin,
    SalePaymentReceiveItemAdmin,
)
from salesio.models import (
    Sale,
    SaleItem,
    SalePaymentReceive,
    SalePaymentReceiveItem,
)


class SaleAdminLoadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="C", display_name="CustCo", company=cls.company
        )
        ChartOfAccount.objects.bulk_create(
            [
                ChartOfAccount(code=f"{9000 + i}", title=f"Acct {i}", company=cls.company)
                for i in range(200)
            ]
        )
        cls.sale = Sale.objects.create(
            company=cls.company, customer=cls.customer, date=date(2026, 1, 1)
        )
        SaleItem.objects.create(sale=cls.sale, quantity=1, total=10)

    def _request(self):
        request = RequestFactory().get("/")
        request.user = type(
            "U",
            (),
            {
                "is_superuser": True,
                "is_active": True,
                "is_staff": True,
                "has_perm": lambda *a, **k: True,
            },
        )()
        return request

    def test_change_form_renders_no_account_dropdowns(self):
        """The form must not scale with the number of accounts."""
        admin = SaleAdmin(Sale, site)
        request = self._request()
        html = admin.get_form(request, self.sale)(instance=self.sale).as_p()
        # 200 accounts x 2 fields would be 400+ options if these were selects.
        self.assertLess(html.count("<option"), 40)

    def test_change_form_does_not_scale_with_account_count(self):
        # 200 accounts x 2 fields would be 400+ queries as plain selects,
        # because ChartOfAccount.__str__ dereferences self.company.
        admin = SaleAdmin(Sale, site)
        request = self._request()
        with CaptureQueriesContext(connection) as ctx:
            admin.get_form(request, self.sale)(instance=self.sale).as_p()
        self.assertLess(len(ctx), 20, f"{len(ctx)} queries to render the form")

    def test_every_foreign_key_is_a_raw_id(self):
        """A missed FK reintroduces a full-table dropdown."""
        for admin_class, model in (
            (SaleAdmin, Sale),
            (SaleItemAdmin, SaleItem),
            (SalePaymentReceiveAdmin, SalePaymentReceive),
            (SalePaymentReceiveItemAdmin, SalePaymentReceiveItem),
        ):
            admin = admin_class(model, site)
            fks = {
                f.name
                for f in model._meta.get_fields()
                if getattr(f, "many_to_one", False)
            }
            missing = fks - set(admin.raw_id_fields)
            self.assertEqual(missing, set(), f"{model.__name__}: {missing}")

    def test_list_filters_are_not_foreign_keys(self):
        """A FK in list_filter renders one sidebar link per related row."""
        admin = SaleAdmin(Sale, site)
        for name in admin.list_filter:
            self.assertNotIn("__", name, f"{name} traverses a relation")
