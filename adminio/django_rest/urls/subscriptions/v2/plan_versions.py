from django.urls import path

from adminio.django_rest.views.subscriptions.v2.plan_versions import (
    AdminSubscriptionFeatureCatalogList,
    AdminSubscriptionPlanVersionAddOns,
    AdminSubscriptionPlanVersionClone,
    AdminSubscriptionPlanVersionCreateDraft,
    AdminSubscriptionPlanVersionList,
    AdminSubscriptionPlanVersionPublish,
    AdminSubscriptionPlanVersionUpdateDraft,
)

urlpatterns = [
    path(
        r"/features",
        AdminSubscriptionFeatureCatalogList.as_view(),
        name="adminio.subscription-feature-catalog",
    ),
    path(
        r"/plans/<uuid:uid>/versions/draft",
        AdminSubscriptionPlanVersionCreateDraft.as_view(),
        name="adminio.subscription-plan-version-draft",
    ),
    path(
        r"/plans/<uuid:uid>/versions/<uuid:version_uid>/addons",
        AdminSubscriptionPlanVersionAddOns.as_view(),
        name="adminio.subscription-plan-version-addons",
    ),
    path(
        r"/plans/<uuid:uid>/versions/<uuid:version_uid>",
        AdminSubscriptionPlanVersionUpdateDraft.as_view(),
        name="adminio.subscription-plan-version-update",
    ),
    path(
        r"/plans/<uuid:uid>/versions/<uuid:version_uid>/clone",
        AdminSubscriptionPlanVersionClone.as_view(),
        name="adminio.subscription-plan-version-clone",
    ),
    path(
        r"/plans/<uuid:uid>/versions/<uuid:version_uid>/publish",
        AdminSubscriptionPlanVersionPublish.as_view(),
        name="adminio.subscription-plan-version-publish",
    ),
    path(
        r"/plans/<uuid:uid>/versions",
        AdminSubscriptionPlanVersionList.as_view(),
        name="adminio.subscription-plan-version-list",
    ),
]
