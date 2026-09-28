from django.db import models

from .choicess import WarehouseStatusChoices


class WareHouseQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=WarehouseStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=WarehouseStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=WarehouseStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=WarehouseStatusChoices.DRAFT)
