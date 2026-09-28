from django.db import models

from .choices import AgencyStatusChoices


class AgencyQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=AgencyStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=AgencyStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=AgencyStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=AgencyStatusChoices.DRAFT)

