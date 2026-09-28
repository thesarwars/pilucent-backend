from django.db import models

from .choices import JournalEntryStatusChoices


class JournalEntryQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=JournalEntryStatusChoices.REMOVED)

    def get_status_published(self):
        return self.filter(status=JournalEntryStatusChoices.PUBLISHED)

    def get_status_unpublished(self):
        return self.filter(status=JournalEntryStatusChoices.UN_PUBLISHED)

    def get_status_draft(self):
        return self.filter(status=JournalEntryStatusChoices.DRAFT)
