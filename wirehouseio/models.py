from autoslug import AutoSlugField

from common.models import BaseModelWithUID

from django.db import models

from .choicess import WarehouseKindChoices, WarehouseStatusChoices

from .managers import WareHouseQuerySet

from .django_rest.helpers.slug_helpers import get_warehouse_slug


class Warehouse(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_warehouse_slug, unique=True, db_index=True)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    remark = models.TextField(blank=True, null=True)
    kind = models.CharField(
        max_length=50,
        choices=WarehouseKindChoices.choices,
        default=WarehouseKindChoices.MAIN,
    )
    status = models.CharField(
        max_length=50,
        choices=WarehouseStatusChoices.choices,
        default=WarehouseStatusChoices.ACTIVE,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = WareHouseQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}, Kind: {self.kind}"

    def get_address(self):
        address_connector = self.addressconnector_set
        return address_connector.first().address if address_connector.exists() else None
