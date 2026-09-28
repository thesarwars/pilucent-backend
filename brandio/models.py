from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from brandio.choicess import BrandKindChoices, BrandStatusChoices

from .django_rest.helpers.slug_helpers import get_brand_slug, get_brand_connector_slug

from .managers import BrandQuerySet


class Brand(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_brand_slug, unique=True, db_index=True)
    kind = models.CharField(
        max_length=50,
        choices=BrandKindChoices.choices,
        blank=True,
        null=True,
        default=BrandKindChoices.PRODUCT,
    )
    status = models.CharField(
        max_length=50,
        choices=BrandStatusChoices.choices,
        blank=True,
        null=True,
        default=BrandStatusChoices.PENDING,
    )
    description = models.TextField(null=True, blank=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = BrandQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Kind: {self.kind}, Status: {self.status}"


class BrandConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_brand_connector_slug, unique=True, db_index=True
    )

    # FK
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "productio.Product", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}, Brand: {self.brand.title}"
