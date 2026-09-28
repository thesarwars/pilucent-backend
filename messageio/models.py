from autoslug import AutoSlugField

from django.db import models
from django.utils import timezone

from common.models import BaseModelWithUID

from .choices import (
    InboxStatusChoices,
    ThreadKindChoices,
    InboxKindChoices,
    InboxUserKindChoices,
)

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.models import FileItem

from .django_rest.helpers.slug_helpers import get_thread_slug, get_inbox_slug


class Inbox(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_inbox_slug, unique=True, db_index=True)
    ticket_noumber = models.CharField(unique=True, max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=InboxStatusChoices, default=InboxStatusChoices.PENDING
    )
    kind = models.CharField(
        choices=InboxKindChoices,
        default=InboxKindChoices.SUPPORT_AND_TICKET,
        max_length=50,
    )
    user_kind = models.CharField(choices=InboxUserKindChoices, max_length=50)
    is_seen = models.BooleanField(default=False)
    seen_at = models.DateTimeField(auto_now_add=True)

    # FKs
    user = models.ForeignKey(
        "accounts.User",
        help_text="The 'User' who created the inbox.",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    target = models.ForeignKey(
        "accounts.User",
        related_name="inbox_target_set",
        help_text="The 'User' who receive the thread",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    # is_balanzify = models.BooleanField(default=False)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"ID: {self.id} Status: {self.status}"

    def update_seen_status(self):
        self.is_seen = True
        self.seen_at = timezone.now()
        self.save_dirty_fields()

    def get_last_thread(self):
        return self.thread_set.first() or None


class Thread(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_thread_slug, unique=True, db_index=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reply_set",
    )
    kind = models.CharField(
        max_length=20,
        choices=ThreadKindChoices.choices,
        default=ThreadKindChoices.PARENT,
    )
    content = models.TextField(blank=True)

    # FK
    author = models.ForeignKey(
        "accounts.User",
        related_name="author_set",
        help_text="The 'User' who created the feed.",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    inbox = models.ForeignKey(Inbox, on_delete=models.CASCADE, blank=True, null=True)

    def __str__(self):
        return f"ID: {self.id} Status: {self.kind}"

    def get_file_items(self):
        return FileItem.objects.filter(
            fileitemconnector__thread=self,
            fileitemconnector__model_kind=FileItemConnectorModelKindChoices.THREAD,
        ).distinct()
