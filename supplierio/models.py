from autoslug import AutoSlugField

from datetime import date

from phonenumber_field.modelfields import PhoneNumberField

from versatileimagefield.fields import VersatileImageField

from django.db.models import Sum
from django.db import models

from fileroomio.models import FileItem

from common.choices import CurrencyChoices
from common.models import BaseModelWithUID

from creditnoteio.choices import CreditNoteKindChoices

from .choices import SupplierkindChoices, SupplierStatusChoices
from .django_rest.helpers.slug_helpers import get_suplier_slug
from .django_rest.helpers.media_path import get_customer_media_path_prefix

from .managers import SupplierQuerySet


class Supplier(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_suplier_slug, unique=True, db_index=True)

    currency = models.CharField(
        max_length=3, choices=CurrencyChoices, default=CurrencyChoices.USD
    )
    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True, null=True)
    last_name = models.CharField(max_length=50, blank=True, null=True)
    suffix = models.CharField(max_length=20, blank=True, null=True)
    display_name = models.CharField(max_length=50, blank=True, null=True)
    company_name = models.CharField(max_length=100, blank=True, null=True)

    # Contact details
    email = models.EmailField(blank=True, null=True)
    telephone_number = models.CharField(max_length=20, blank=True, null=True)
    mobile_number = PhoneNumberField(blank=True, null=True)
    fax = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    business_id = models.CharField(max_length=30, blank=True, null=True)
    billing_rate = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    account_number = models.CharField(max_length=20, blank=True, null=True)
    date = models.DateField(default=date.today)
    opening_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=SupplierStatusChoices,
        default=SupplierStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50, blank=True, null=True, choices=SupplierkindChoices
    )
    description = models.TextField(blank=True, null=True)

    # FK
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="parents"
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    image = VersatileImageField(
        "Image",
        upload_to=get_customer_media_path_prefix,
        blank=True,
    )
    objects = SupplierQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.pk}, Company: {self.company_name}, Status: {self.status} "

    def get_file_items(self):
        return FileItem.objects.filter(
            id__in=self.fileitemconnector_set.values_list("file_item_id", flat=True)
        )

    def get_file_item_count(self):
        return self.get_file_items().count()

    def get_credit_count(self):
        return (
            self.creditnote_set.filter(kind=CreditNoteKindChoices.PURCHASE).aggregate(
                credit_count=Sum("total")
            )["credit_count"]
            or 0
        )
