from django.db import models

from .choicess import TermStatusChoices


class TermsQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=TermStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=TermStatusChoices.ACTIVE)

    def get_stats_inactive(self):
        return self.filter(status=TermStatusChoices.IN_ACTIVE)

    def get_status_pending(self):
        return self.filter(status=TermStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=TermStatusChoices.DRAFT)
