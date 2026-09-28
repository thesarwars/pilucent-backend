from django.db import models

from .choicess import CategoryStatusChoices


class CategoryQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CategoryStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=CategoryStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=CategoryStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=CategoryStatusChoices.DRAFT)
