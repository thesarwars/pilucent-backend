from django.urls import path

from weapi.django_rest.views.recurring_transactions import (
    PrivateWeRecurringTemplateList,
    PrivateWeRecurringTemplateDetails,
    PrivateWeRecurringTemplateDuplicate,
    PrivateWeRecurringTemplateUse,
    PrivateWeRecurringTemplatePauseResume,
)

from recurringio.choices import RecurringTemplateStatusChoices

urlpatterns = [
    path(
        r"/<uuid:uid>/duplicate",
        PrivateWeRecurringTemplateDuplicate.as_view(),
        name="weapi.recurring-templates.duplicate",
    ),
    path(
        r"/<uuid:uid>/pause",
        PrivateWeRecurringTemplatePauseResume.as_view(
            target_status=RecurringTemplateStatusChoices.PAUSED
        ),
        name="weapi.recurring-templates.pause",
    ),
    path(
        r"/<uuid:uid>/resume",
        PrivateWeRecurringTemplatePauseResume.as_view(
            target_status=RecurringTemplateStatusChoices.ACTIVE
        ),
        name="weapi.recurring-templates.resume",
    ),
    path(
        r"/<uuid:uid>/use",
        PrivateWeRecurringTemplateUse.as_view(),
        name="weapi.recurring-templates.use",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeRecurringTemplateDetails.as_view(),
        name="weapi.recurring-templates.details",
    ),
    path(
        r"",
        PrivateWeRecurringTemplateList.as_view(),
        name="weapi.recurring-templates.list",
    ),
]
