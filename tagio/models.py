from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choices import TagKindChoices, TagStatusChoices

from .django_rest.helpers.slug_helpers import get_tag_slug, get_tag_connector_slug


class Tag(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_tag_slug, unique=True, db_index=True)
    kind = models.CharField(
        max_length=50,
        choices=TagKindChoices.choices,
        blank=True,
        null=True,
        default=TagKindChoices.PRODUCT,
    )
    status = models.CharField(
        max_length=50,
        choices=TagStatusChoices.choices,
        blank=True,
        null=True,
        default=TagStatusChoices.DRAFT,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}, Kind: {self.kind}, Status: {self.status}"


class TagConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_tag_connector_slug, unique=True, db_index=True
    )

    # FK
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    brand = models.ForeignKey(
        "brandio.Brand", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, blank=True, null=True
    )
    journal_entry = models.ForeignKey(
        "journalio.JournalEntry", on_delete=models.CASCADE, blank=True, null=True
    )
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    pay_bill = models.ForeignKey(
        "purchaseio.PayBill", on_delete=models.CASCADE, blank=True, null=True
    )
    bank_deposit = models.ForeignKey(
        "transactionio.BankDeposit", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Tag: {self.tag.title}"
