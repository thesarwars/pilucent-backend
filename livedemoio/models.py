from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .django_rest.helpers.slug_helpers import get_live_demo_slug

from .choices import RequestTypeChoices


class LiveDemo(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_live_demo_slug, unique=True, db_index=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    full_name = models.CharField(max_length=100, blank=True, null=True)
    work_email = models.EmailField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    agent_count = models.IntegerField(blank=True, null=True)
    preferred_version = models.CharField(max_length=150, blank=True, null=True)
    preferred_date = models.DateField(blank=True, null=True)
    preferred_time = models.TimeField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    meeting_type = models.CharField(max_length=100, blank=True, null=True)
    meeting_link = models.URLField(blank=True, null=True)
    mail_subject = models.CharField(max_length=255, blank=True, null=True)
    mail_body = models.TextField(blank=True, null=True)
    is_mail_sent = models.BooleanField(default=False)
    request_type = models.CharField(max_length=25, choices=RequestTypeChoices.choices, default=RequestTypeChoices.LIVE_DEMO)

    def __str__(self):
        return f"{self.email}_{self.company_name}"
