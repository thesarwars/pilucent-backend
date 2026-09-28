from django.db import models

from .choicess import BrandStatusChoices


class BrandQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=BrandStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=BrandStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=BrandStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=BrandStatusChoices.DRAFT)
