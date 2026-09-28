"""Deleting one tax rate destroyed other tenants' documents and their ledger.

`PrivateWeAgencyTaxDetails.delete` hard-deletes an `AgencyTax`. Two things made
that catastrophic.

**The queryset had no tenant scope.** It is `AgencyTax.objects.all()`, and the
company filter was commented out, so any authenticated user could delete ANY
company's tax rate by uid.

**Four FKs pointed at it with CASCADE:** `SaleItem.tax`, `PurchaseItem.tax`,
`CreditNoteItem.tax` and `ProductAdditionalCost.tax`. And
`JournalEntryConnector.saleitem` / `.purchase_item` / `.credit_note_item` are
themselves CASCADE. So one DELETE removed every document line that had ever
referenced that tax, and every journal leg behind those lines -- across tenants.

A tax rate is reference data. The documents that used it are records of what
happened and must outlive it, so all four are SET_NULL. Every one was already
`null=True`, and the posted figures live on the connectors, so what is lost is a
pointer, not money. `ProductAdditionalCost` matters twice over: it also carries
`expense_account`, which `resolve_cogs_account` reads to post cost of sales.

The commented-out filter read `agency__company`, which cannot work -- `AgencyTax`
has no `agency` field, it holds `company` directly. Restoring it as written would
have raised FieldError, which is the likely reason it was commented out instead of
fixed.
"""

from django.db import models
from django.test import TestCase


class TaxFkOnDeleteTests(TestCase):
    """Every FK that can reach a document line from a tax must be SET_NULL."""

    def cases(self):
        from creditnoteio.models import CreditNoteItem
        from productio.models import ProductAdditionalCost
        from purchaseio.models import PurchaseItem
        from salesio.models import SaleItem

        return [SaleItem, PurchaseItem, CreditNoteItem, ProductAdditionalCost]

    def test_no_tax_fk_cascades(self):
        for model in self.cases():
            with self.subTest(model=model.__name__):
                field = model._meta.get_field("tax")
                self.assertEqual(
                    field.remote_field.on_delete,
                    models.SET_NULL,
                    f"{model.__name__}.tax must not cascade from reference data",
                )

    def test_each_is_nullable_so_set_null_is_valid(self):
        for model in self.cases():
            with self.subTest(model=model.__name__):
                self.assertTrue(model._meta.get_field("tax").null)

    def test_nothing_reachable_from_a_tax_still_cascades_into_a_document(self):
        """The authoritative check: ask Django what a tax delete would collect."""
        from agencyio.models import AgencyTax

        document_models = {
            "SaleItem",
            "PurchaseItem",
            "CreditNoteItem",
            "ProductAdditionalCost",
        }
        offenders = []
        for rel in AgencyTax._meta.related_objects:
            name = rel.related_model.__name__
            if name in document_models and rel.on_delete is models.CASCADE:
                offenders.append(f"{name}.{rel.field.name}")

        self.assertEqual(offenders, [], f"still cascading: {offenders}")

    def test_the_connector_line_fks_are_what_made_it_reach_the_ledger(self):
        """Why the tax cascade mattered: the line FKs carried it onward.

        When this was written those three were CASCADE, so cutting the tax
        cascade only removed the path *into* them. They are PROTECT now (P0.2's
        leftover), which closes the second hop as well -- so a tax deletion
        could no longer have reached the ledger even if the first hop had been
        left alone.

        Kept rather than deleted: it names the two-hop chain that made a single
        DELETE destructive, and it fails if either hop regresses.
        """
        from journalio.models import JournalEntryConnector

        for name in ("saleitem", "purchase_item", "credit_note_item"):
            with self.subTest(field=name):
                field = JournalEntryConnector._meta.get_field(name)
                self.assertEqual(field.remote_field.on_delete, models.PROTECT)


class TenantScopeTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.views import agencies

        return inspect.getsource(agencies)

    def test_the_tax_delete_is_scoped_to_the_active_company(self):
        source = self.source()

        self.assertIn(
            "company=request.user.get_active_company(),\n            uid=uid,",
            source,
        )
        self.assertNotIn("# agency__company=request.user.get_active_company()", source)

    def test_it_does_not_scope_on_a_field_that_does_not_exist(self):
        """The commented-out filter used `agency__company`; there is no `agency`."""
        from agencyio.models import AgencyTax

        field_names = {f.name for f in AgencyTax._meta.get_fields()}
        self.assertNotIn("agency", field_names)
        self.assertIn("company", field_names)

        self.assertNotIn("agency__company=", self.source())
