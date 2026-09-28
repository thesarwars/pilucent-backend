from django.urls import path

from weapi.django_rest.views.journals import (
    PrivateWeJournalEntryList,
    PrivateWeJournalEntryDetails,
    PrivateWeJournalEntryTagList,
    PrivateWeJournalEntryFileItemList,
    PrivateWeUndepositedFundsJournalEntryList,
)

urlpatterns = [
    path(
        r"/undeposited-funds",
        PrivateWeUndepositedFundsJournalEntryList.as_view(),
        name="weapi.undeposited-funds-journal-entry-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeJournalEntryDetails.as_view(),
        name="weapi.journal-entry-details",
    ),
    path(r"", PrivateWeJournalEntryList.as_view(), name="weapi.journal-entry-list"),
    path(
        r"/<uuid:uid>/tags",
        PrivateWeJournalEntryTagList.as_view(),
        name="weapi.journal-entry-tag-list",
    ),
    path(
        r"/<uuid:uid>/files",
        PrivateWeJournalEntryFileItemList.as_view(),
        name="weapi.journal-entry-file-item-list",
    ),
]
