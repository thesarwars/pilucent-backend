from django.db import models

from .choices import CreditNoteStatusChoices


class CreditNoteQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=CreditNoteStatusChoices.REMOVED)

    def get_status_open(self):
        return self.filter(status=CreditNoteStatusChoices.OPEN)

    def get_status_pending(self):
        return self.filter(status=CreditNoteStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=CreditNoteStatusChoices.DRAFT)

    def get_status_close(self):
        return self.filter(status=CreditNoteStatusChoices.CLOSE)
