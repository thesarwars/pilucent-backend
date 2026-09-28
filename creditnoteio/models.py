from autoslug import AutoSlugField

from datetime import date

from django.db import models

from common.choices import TaxKindChoices
from common.django_rest.helpers.json_helpers import email_helpers
from common.models import BaseModelWithUID

from salesio.choices import (
    SalePaymentReceiveItemModelKindChoices,
    SalePaymentReceiveStatusChoices,
)

from .choices import (
    CreditNoteStatusChoices,
    CreditNoteItemStatusChoices,
    CreditNoteKindChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_credit_note_slug,
    get_credit_note_item_slug,
)

from .managers import CreditNoteQuerySet


class CreditNote(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_credit_note_slug, unique=True, db_index=True)
    date = models.DateField(default=date.today)
    credit_note_number = models.CharField(max_length=50, unique=True)
    email = models.JSONField(default=email_helpers)
    kind = models.CharField(max_length=50, choices=CreditNoteKindChoices)
    status = models.CharField(
        max_length=50,
        choices=CreditNoteStatusChoices,
        default=CreditNoteStatusChoices.DRAFT,
    )
    tax_kind = models.CharField(
        max_length=20, choices=TaxKindChoices.choices, default=TaxKindChoices.NO_TAX
    )
    description = models.TextField(blank=True, null=True)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total_tax = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    credit_note_sales_tax = models.JSONField(null=True, blank=True)

    # FK
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.CASCADE, blank=True, null=True
    )
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, blank=True, null=True
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.CASCADE, blank=True, null=True
    )
    objects = CreditNoteQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.pk}, kind: {self.kind}, Status: {self.status} "

    def get_sale_remaining_balance(self):
        """What is left of this credit, on the sale side.

        The sale side never mutates `total`, so remaining is derived: the face
        value less everything applied against it.

        A payment that has been deleted is excluded. Deleting a customer payment
        retires the document but leaves its `SalePaymentReceiveItem` rows, and
        without this filter those rows go on consuming the credit forever -- the
        payment is gone from every list and the credit it spent never comes back.
        There was no way to free a sale credit note at all before this: the
        purchase side gets its credit back because `unapply_purchase_payment_items`
        adds to the stored `total`, but the sale side has no stored figure to add
        to, so the release has to happen here, where the figure is derived.
        """
        return self.total - (
            self.salepaymentreceiveitem_set.exclude(
                sale_payment_receive__status=SalePaymentReceiveStatusChoices.REMOVED
            ).aggregate(
                total_used=models.Sum(
                    "used_total",
                    filter=models.Q(
                        model_kind=SalePaymentReceiveItemModelKindChoices.CREDIT_NOTE
                    ),
                )
            )["total_used"]
            or 0
        )

    def get_purchase_remaining_balance(self):
        """What is left of this credit, on the purchase side.

        The purchase side is NOT the mirror of the sale side, and this method
        used to assume it was. Applying a vendor credit **decrements the stored
        `total` in place** (`weapi/django_rest/serializers/purchases.py:2826`),
        so the stored figure already IS the remaining balance -- subtracting the
        applications again took it off twice. A 100 credit with 30 applied stores
        70 and this reported 40.

        `ap_aging_detail` has been working around exactly this since it was
        written: its module docstring says it reads the stored `total` "rather
        than `get_purchase_remaining_balance`, which double-counts applications
        on the purchase side". The report was right and this was wrong, so the
        two disagreed about the same credit note -- and this one is what the API
        returns as `purchase_remaining_balance`.

        No payment-status filter is needed here, unlike the sale side. Deleting
        a supplier payment already adds the credit back to the stored `total`
        (`unapply_purchase_payment_items`), so the stored figure is current;
        subtracting a removed payment's items on top would take it off again.
        """
        return self.total

    def get_is_fully_used_sale(self):
        """Check if the credit note has been fully utilized."""
        return self.get_sale_remaining_balance() <= 0

    def get_is_fully_used_purchase(self):
        """Check if the credit note has been fully utilized."""
        return self.get_purchase_remaining_balance() <= 0


class CreditNoteItem(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_credit_note_item_slug, unique=True, db_index=True
    )
    section = models.CharField(max_length=100, blank=True, null=True)
    note = models.TextField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=CreditNoteItemStatusChoices,
        default=CreditNoteItemStatusChoices.DRAFT,
    )
    description = models.TextField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    item_credit = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    total = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    # FK
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    tax = models.ForeignKey(
        "agencyio.AgencyTax",
        # See SaleItem.tax.
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    charter_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.pk}, Product: {self.product}, Status: {self.status}"
