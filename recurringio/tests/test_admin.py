"""The admin list pages must not degrade into per-row queries.

These models carry 25 FKs between them, so an unjoined changelist costs a query
per row per column -- the difference measured here is 1 query versus 51.
"""

from datetime import date

from django.contrib.admin.sites import AdminSite
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.test import TestCase

from accounts.models import ChartOfAccount
from companyio.models import Company
from customerio.models import Customer
from supplierio.models import Supplier

from recurringio.admin import (
    RecurringOccurrenceAdmin,
    RecurringTemplateAdmin,
    RecurringTemplateLineAdmin,
)
from recurringio.models import (
    RecurringOccurrence,
    RecurringTemplate,
    RecurringTemplateLine,
)

ROWS = 25


class AdminQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        supplier = Supplier.objects.create(
            first_name="V", display_name="VendCo", company=cls.company
        )
        customer = Customer.objects.create(
            first_name="C", display_name="CustCo", company=cls.company
        )
        account = ChartOfAccount.objects.create(
            code="6000", title="Rent", company=cls.company
        )
        for i in range(ROWS):
            template = RecurringTemplate.objects.create(
                name=f"Template {i}", txn_type="BILL", company=cls.company,
                supplier=supplier, customer=customer, frequency="MONTHLY",
                start_date=date(2026, 1, 1), next_run_date=date(2026, 2, 1),
            )
            for position in range(3):
                RecurringTemplateLine.objects.create(
                    template=template, company=cls.company, line_type="CATEGORY",
                    charter_account=account, amount="10", position=position,
                )
            RecurringOccurrence.objects.create(
                template=template, company=cls.company,
                occurrence_date=date(2026, 1, 1), status="GENERATED",
            )

    def test_template_list_does_not_scale_with_row_count(self):
        # An upper bound rather than an exact count: the invariant is "no query
        # per row" (which would be 26 here), and an exact assertion is brittle
        # to ambient savepoints when the whole suite runs.
        admin = RecurringTemplateAdmin(RecurringTemplate, AdminSite())
        with CaptureQueriesContext(connection) as ctx:
            for row in admin.get_queryset(None):
                admin.party(row)       # supplier/customer must be joined
                admin.line_count(row)  # must come from the annotation
        self.assertLess(len(ctx), ROWS, f"{len(ctx)} queries for {ROWS} rows")

    def test_occurrence_list_does_not_scale_with_row_count(self):
        admin = RecurringOccurrenceAdmin(RecurringOccurrence, AdminSite())
        with CaptureQueriesContext(connection) as ctx:
            for row in admin.get_queryset(None):
                admin.txn_type(row)
                admin.generated_document(row)
        self.assertLess(len(ctx), ROWS, f"{len(ctx)} queries for {ROWS} rows")

    def test_line_list_does_not_scale_with_row_count(self):
        admin = RecurringTemplateLineAdmin(RecurringTemplateLine, AdminSite())
        with CaptureQueriesContext(connection) as ctx:
            for row in admin.get_queryset(None):
                _ = row.template.name, row.charter_account.title
        self.assertLess(len(ctx), ROWS, f"{len(ctx)} queries for {ROWS} rows")

    def test_occurrence_ledger_is_not_hand_editable(self):
        # It is the idempotency guard: a hand-made or edited row would let a
        # date fire twice, or never.
        admin = RecurringOccurrenceAdmin(RecurringOccurrence, AdminSite())
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))

    def test_every_foreign_key_is_a_raw_id(self):
        """No change form may render a full-table dropdown.

        A missed FK here means one unbounded query (every customer, product,
        account…) on every page load.
        """
        for admin_class, model in (
            (RecurringTemplateAdmin, RecurringTemplate),
            (RecurringTemplateLineAdmin, RecurringTemplateLine),
            (RecurringOccurrenceAdmin, RecurringOccurrence),
        ):
            admin = admin_class(model, AdminSite())
            fks = {
                f.name for f in model._meta.get_fields()
                if getattr(f, "many_to_one", False)
            }
            missing = fks - set(admin.raw_id_fields)
            self.assertEqual(missing, set(), f"{model.__name__}: {missing}")
