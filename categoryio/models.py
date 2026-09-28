from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choicess import CategoryKindChoices, CategoryStatusChoices

from .managers import CategoryQuerySet

from .django_rest.helpers.slug_helpers import (
    get_category_slug,
    get_category_connector_slug,
)


class Category(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_category_slug, unique=True, db_index=True)
    kind = models.CharField(
        max_length=50,
        choices=CategoryKindChoices.choices,
        blank=True,
        null=True,
        default=CategoryKindChoices.PRODUCT,
    )
    status = models.CharField(
        max_length=50,
        choices=CategoryStatusChoices.choices,
        blank=True,
        null=True,
        default=CategoryStatusChoices.PENDING,
    )
    description = models.TextField(null=True, blank=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="parents"
    )
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, blank=True, null=True
    )
    objects = CategoryQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Kind: {self.kind}, Status: {self.status}, Title: {self.title}"

    def get_childrens(self):
        return self.parents.all()


class CategoryConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_category_connector_slug, unique=True, db_index=True
    )

    # FK
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )
    brand = models.ForeignKey(
        "brandio.Brand", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_item = models.ForeignKey(
        "purchaseio.PurchaseItem", on_delete=models.CASCADE, blank=True, null=True
    )
    credit_note_item = models.ForeignKey(
        "creditnoteio.CreditNoteItem", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Category: {self.category.title}"
