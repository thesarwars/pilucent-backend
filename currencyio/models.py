from autoslug import AutoSlugField

from django.db import models
from django.utils import timezone

from common.choices import CurrencyChoices
from common.models import BaseModelWithUID

from .choices import CurrencyStatusChoices, CurrencyConnectorModelKind
from .django_rest.helpers.slug_helpers import (
    get_currency_slug,
    get_currency_connector_slug,
)


class Currency(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_currency_slug, unique=True, db_index=True)
    title = models.CharField(max_length=100)
    kind = models.CharField(
        choices=CurrencyChoices, default=CurrencyChoices.USD, max_length=50
    )
    status = models.CharField(
        choices=CurrencyStatusChoices,
        default=CurrencyStatusChoices.DRAFT,
        max_length=50,
    )
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4)
    date = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, null=True)

    # FK
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.SET_NULL, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Currency: {self.kind}, To: {self.exchange_rate}"


class CurrencyConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_currency_connector_slug, unique=True, db_index=True
    )
    model_kind = models.CharField(
        choices=CurrencyConnectorModelKind, max_length=50, blank=True, null=True
    )

    # FK
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.CASCADE, blank=True, null=True
    )
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, blank=True, null=True
    )
    
    credit_note = models.ForeignKey(
        "creditnoteio.CreditNote", on_delete=models.CASCADE, blank=True, null=True
    )
    sale_payment_receive = models.ForeignKey(
        "salesio.SalePaymentReceive", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    pay_bill = models.ForeignKey(
        "purchaseio.PayBill", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Currency: {self.currency.kind}, To: {self.currency.exchange_rate}"
