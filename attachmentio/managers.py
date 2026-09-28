from django.db import models

from .choices import AttachmentStatusChoices

class AttachmentQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=AttachmentStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=AttachmentStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=AttachmentStatusChoices.PENDING)

    def get_status_draft(self):
        return self.filter(status=AttachmentStatusChoices.DRAFT)
