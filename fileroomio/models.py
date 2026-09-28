from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    FileItemKindChoices,
    FileItemStatusChoices,
    FileItemConnectorModelKindChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_fileitem_slug,
    get_fileitem_connector_slug,
)
from .django_rest.helpers.media_path import get_fileitem_path_prefix
from .managers import FileItemStatusChoicesQuerySet


class FileItem(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_fileitem_slug, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=get_fileitem_path_prefix)
    status = models.CharField(
        max_length=50,
        choices=FileItemStatusChoices.choices,
        default=FileItemStatusChoices.DRAFT,
    )
    kind = models.CharField(max_length=50, choices=FileItemKindChoices.choices)
    link = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_report = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, blank=True, null=True
    )

    objects = FileItemStatusChoicesQuerySet.as_manager()

    def __str__(self):
        return self.title


class FileItemConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_fileitem_connector_slug, unique=True, db_index=True
    )
    model_kind = models.CharField(
        max_length=50, choices=FileItemConnectorModelKindChoices.choices
    )
    file_item = models.ForeignKey(
        FileItem, on_delete=models.CASCADE, blank=True, null=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.SET_NULL, null=True, blank=True
    )
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.SET_NULL, null=True, blank=True
    )
    attachment = models.ForeignKey(
        "attachmentio.Attachment", on_delete=models.SET_NULL, null=True, blank=True
    )
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.SET_NULL, null=True, blank=True
    )
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.SET_NULL, null=True, blank=True
    )
    thread = models.ForeignKey(
        "messageio.Thread", on_delete=models.SET_NULL, null=True, blank=True
    )
    journal_entry = models.ForeignKey(
        "journalio.JournalEntry", on_delete=models.CASCADE, blank=True, null=True
    )
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )
    sale_payment_receive = models.ForeignKey(
        "salesio.SalePaymentReceive", on_delete=models.CASCADE, blank=True, null=True
    )
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    pay_bill = models.ForeignKey(
        "purchaseio.PayBill", on_delete=models.CASCADE, blank=True, null=True
    )
    recurring_template = models.ForeignKey(
        "recurringio.RecurringTemplate",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    bank_deposit = models.ForeignKey(
        "transactionio.BankDeposit", on_delete=models.CASCADE, blank=True, null=True
    )
    employee = models.ForeignKey(
        "employeeio.Employee", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID :{self.id},  {self.model_kind}"
