"""P0.2's leftover: deleting a document line could erase its journal legs.

`JournalEntryConnector.account` became PROTECT under P0.2, which stopped a deleted
account taking its ledger history with it. The same commit's notes said to
"consider PROTECT on the 36 other document FKs" and named this shape as the thing
it exists to prevent -- "parent entries survive with missing legs, permanently
unbalanced rows no reconciliation can explain". Three of those FKs were still
CASCADE:

    JournalEntryConnector.saleitem
    JournalEntryConnector.purchase_item
    JournalEntryConnector.credit_note_item

They were reachable from `Sale`, `Purchase`, `CreditNote`, `Product`,
`ChartOfAccount` and -- until 89375ff0 -- `AgencyTax`, whose delete endpoint was
not even tenant-scoped.

WHY THIS IS SAFE NOW AND WAS NOT BEFORE. PROTECT fires even when the protecting
rows sit inside the same cascade, so flipping these while any delete path still
left a leg behind would have converted silent corruption into a 500 on a working
endpoint. Two things had to land first:

  * every parent soft-deletes -- Sale voids; Purchase, CreditNote, Product,
    ChartOfAccount and Company set REMOVED
  * all three line-delete endpoints reverse their legs before removing the line:
    the sale line reposts the document, the credit-note and purchase lines go
    through `reverse_item_connectors` (33f27fb8, e29dc67a)

And `ProtectedError` is already mapped to 409 by the project exception handler, so
a path that has not reversed its legs now says so rather than quietly breaking
the books.

These tests pin the invariant, not the mechanism: the pre-flight the plan asks for
is "enumerate live delete paths, not orphans", so what matters is that no live
path can reach a connector through a cascade.
"""

from django.db import models
from django.test import TestCase


LINE_FKS = ("saleitem", "purchase_item", "credit_note_item")


class ConnectorFkTests(TestCase):
    def connector(self):
        from journalio.models import JournalEntryConnector

        return JournalEntryConnector

    def test_no_line_fk_cascades(self):
        for name in LINE_FKS:
            with self.subTest(field=name):
                field = self.connector()._meta.get_field(name)
                self.assertEqual(
                    field.remote_field.on_delete,
                    models.PROTECT,
                    f"{name} must not take journal legs with it",
                )

    def test_the_account_fk_is_still_protected(self):
        """P0.2's original half; regression guard."""
        field = self.connector()._meta.get_field("account")
        self.assertEqual(field.remote_field.on_delete, models.PROTECT)

    def cascading_fks(self):
        return sorted(
            rel.name
            for rel in self.connector()._meta.get_fields()
            if rel.is_relation
            and hasattr(rel, "attname")
            and rel.remote_field
            and rel.remote_field.on_delete is models.CASCADE
        )

    def test_only_structurally_correct_fks_still_cascade(self):
        """Ask Django, not the declarations.

        `journal` SHOULD cascade -- an entry and its legs are one unit, and
        deleting the entry deliberately takes them. `parent` is the connector's
        own self-link.

        `customer` and `supplier` should not, and are the same shape as the tax
        cascade fixed in 89375ff0: reference-ish records whose deletion would take
        journal legs with them. They are LATENT, not live -- both delete endpoints
        soft-delete (see the assertions below) -- so they are recorded here rather
        than changed in the same commit as P0.2's leftover. Widening this test is
        the follow-up.
        """
        self.assertEqual(
            self.cascading_fks(),
            ["customer", "journal", "parent", "supplier"],
            "a new CASCADE appeared on JournalEntryConnector, or one was fixed "
            "without updating this list",
        )

    def test_no_document_LINE_fk_reaches_a_connector_by_cascade(self):
        """The actual P0.2 leftover: the three line FKs."""
        cascading = set(self.cascading_fks())

        self.assertEqual(
            cascading & set(LINE_FKS),
            set(),
            "a document line can still take its journal legs with it",
        )

    def test_the_customer_and_supplier_deletes_are_soft(self):
        """Which is the only reason their CASCADE is not a live defect."""
        import importlib
        import inspect

        for module, marker in (
            ("weapi.django_rest.views.customers", "CustomerStatusChoices.REMOVED"),
            ("weapi.django_rest.views.suppliers", "SupplierStatusChoices.REMOVED"),
        ):
            with self.subTest(module=module):
                source = inspect.getsource(importlib.import_module(module))
                self.assertIn(marker, source)


class ParentDeleteSemanticsTests(TestCase):
    """PROTECT is only safe because none of these hard-deletes.

    If one of them is ever changed back to a hard delete, PROTECT turns it into a
    409 rather than silent ledger loss -- which is the intended trade -- but these
    assertions say plainly which paths the choice depends on.
    """

    def source(self, dotted):
        import importlib
        import inspect

        return inspect.getsource(importlib.import_module(dotted))

    def test_the_document_deletes_are_soft(self):
        cases = [
            ("weapi.django_rest.views.sales", "SalesStatusChoices"),
            ("weapi.django_rest.views.purchases", "PurchaseStatus.REMOVED"),
            ("weapi.django_rest.views.creditnotes", "CreditNoteStatusChoices.REMOVED"),
        ]
        for module, marker in cases:
            with self.subTest(module=module):
                self.assertIn(marker, self.source(module))

    def test_the_company_delete_is_soft(self):
        source = self.source("adminio.django_rest.views.companies")

        self.assertIn("CompanyStatusChoices.REMOVED", source)

    def test_the_chart_of_account_delete_is_soft(self):
        source = self.source("weapi.django_rest.views.chart_of_accounts")

        self.assertIn("ChartOfAccountStatusChoices.REMOVED", source)

    def test_the_product_delete_is_soft(self):
        source = self.source("weapi.django_rest.views.products")

        self.assertIn("ProductStatusChoices.REMOVED", source)


class LineDeletePathsReverseFirstTests(TestCase):
    """PROTECT also depends on each line delete clearing its own legs."""

    def source(self, dotted):
        import importlib
        import inspect

        return inspect.getsource(importlib.import_module(dotted))

    def test_the_credit_note_line_reverses_its_legs(self):
        self.assertIn(
            "reverse_item_connectors(",
            self.source("weapi.django_rest.views.creditnotes"),
        )

    def test_the_purchase_line_reverses_its_legs(self):
        self.assertIn(
            "reverse_item_connectors(",
            self.source("weapi.django_rest.views.purchases"),
        )

    def test_the_purchase_line_detaches_sale_side_legs(self):
        """Otherwise PROTECT would refuse to delete a line whose stock was sold.

        Those legs belong to the sale's entry, not this document's, so they are
        detached rather than reversed. Without that, this migration would turn a
        working endpoint into a 409 for any product that has ever been sold.
        """
        self.assertIn(
            "_detach_foreign_legs(",
            self.source("weapi.django_rest.views.purchases"),
        )

    def test_the_sale_line_reposts_the_document(self):
        self.assertIn(
            "perform_destroy", self.source("weapi.django_rest.views.sales")
        )


class ProtectedErrorHandlingTests(TestCase):
    def test_protected_error_is_mapped_to_409(self):
        from django.db.models import ProtectedError
        from rest_framework import status

        from common.django_rest import exception_handler as module

        response = module.exception_handler(
            ProtectedError("nope", set()), {}
        )
        self.assertIsNotNone(
            response, "ProtectedError must not escape as an unhandled 500"
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_the_handler_is_wired_up(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK.get("EXCEPTION_HANDLER"),
            "common.django_rest.exception_handler.exception_handler",
        )
