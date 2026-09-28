from autoslug import AutoSlugField

from datetime import date

from django.db import models

from common.models import BaseModelWithUID
from common.django_rest.helpers.countries import COUNTRIES

from .django_rest.helpers.slug_helpers import (
    get_address_slug,
    get_address_connector_slug,
)
from .choices import AddressStatusChoices, AddressConnectorKindCoices


class Address(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_address_slug, unique=True, db_index=True)
    street = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    province = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    full_address = models.CharField(max_length=255, blank=True, null=True)
    is_shipping = models.BooleanField(default=False)
    shipping_by = models.CharField(max_length=100, blank=True, null=True)
    shipping_date = models.DateField(default=date.today)
    status = models.CharField(
        choices=AddressStatusChoices, default=AddressStatusChoices.DRAFT, max_length=50
    )
    country = models.CharField(
        max_length=2, choices=COUNTRIES, default="us", db_index=True
    )
    is_work_address = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.full_address}, {self.street}, {self.city}, {self.province}, {self.postal_code}"

    def get_kind(self):
        address_connector = self.addressconnector_set.first()
        return address_connector.kind


class AddressConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_address_connector_slug, unique=True, db_index=True
    )
    kind = models.CharField(choices=AddressConnectorKindCoices, max_length=50)
    employee = models.ForeignKey(
        "employeeio.Employee", on_delete=models.CASCADE, null=True, blank=True
    )
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, null=True, blank=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.CASCADE, null=True, blank=True
    )
    address = models.ForeignKey(
        "addressio.Address", on_delete=models.CASCADE, blank=True, null=True
    )
    warehouse = models.ForeignKey(
        "wirehouseio.Warehouse", on_delete=models.CASCADE, blank=True, null=True
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
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.pk}, Kind: {self.kind}"
