from autoslug import AutoSlugField

from versatileimagefield.fields import VersatileImageField

from django.db import models

from common.models import BaseModelWithUID

from .django_rest.helpers.slug_helpers import get_atachment_slug
from .django_rest.helpers.media_path import get_atachment_media_path_prefix

from .choices import AttachmentStatusChoices
from .managers import AttachmentQuerySet

class Attachment(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_atachment_slug, unique=True, db_index=True)
    image = VersatileImageField(
        "Image",
        upload_to=get_atachment_media_path_prefix,
        blank=True,
        null=True
    )
    link = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=AttachmentStatusChoices,
        default=AttachmentStatusChoices.DRAFT,
    )
    objects = AttachmentQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}"
