from django.db import models

from .choices import ProductStatusChoices, ProductBundleStatusChoices


class ProductQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=ProductStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=ProductStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=ProductStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=ProductStatusChoices.DRAFT)

class ProductBundleQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=ProductBundleStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=ProductBundleStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=ProductBundleStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=ProductBundleStatusChoices.DRAFT)