from django.db import models

from .choices import SupplierStatusChoices

class SupplierQuerySet(models.QuerySet):
    def selectable(self):
        """Suppliers a user may choose when building a new document.

        The mirror of `CustomerQuerySet.selectable()`, and it exists for the
        reason that docstring records: nine supplier pickers filtered
        `status=ACTIVE`, which reads as the same thing and is not. `status`
        defaults to DRAFT on the model and only the bulk importer sets ACTIVE
        explicitly, so once `6d5736bd` made `status` read-only -- correctly, it
        was a client-writable guard -- every supplier created through the API
        landed as DRAFT and vanished from the bill, expense and pay-bills
        pickers at once. The same shape the accounts version hit, and 73 tests
        found there.

        Wider than `ACTIVE`, narrower than `all()`: REMOVED is withheld from
        data entry and keeps its balance, its history and its place on the
        ageing report. There is no INACTIVE state on Supplier yet; when
        `SUPPLIER_GAPS.md` G1 adds one, it is added here and nowhere else,
        which is the point of routing every picker through one method.
        """
        return self.exclude(status=SupplierStatusChoices.REMOVED)

    def get_status_all(self):
        return self.all().exclude(status=SupplierStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=SupplierStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=SupplierStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=SupplierStatusChoices.DRAFT)
