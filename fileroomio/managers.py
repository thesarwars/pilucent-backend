from django.db import models

from .choices import FileItemStatusChoices


class FileItemStatusChoicesQuerySet(models.QuerySet):
    def get_status_all(self):
        return self.all().exclude(status=FileItemStatusChoices.REMOVED)

    def get_status_published(self):
        return self.filter(status=FileItemStatusChoices.PUBLISHED)

    def get_status_un_published(self):
        return self.filter(status=FileItemStatusChoices.UN_PUBLISHED)

    def get_status_draft(self):
        return self.filter(status=FileItemStatusChoices.DRAFT)
