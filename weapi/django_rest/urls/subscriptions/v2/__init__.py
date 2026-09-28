from django.urls import include, path

urlpatterns = [
    path(r"/entitlements", include("weapi.django_rest.urls.subscriptions.v2.entitlements")),
    path(r"/billing", include("weapi.django_rest.urls.subscriptions.v2.billing")),
    path(r"/addons", include("weapi.django_rest.urls.subscriptions.v2.addons")),
    path(r"/checkout", include("weapi.django_rest.urls.subscriptions.v2.checkout")),
    path(r"/promotions", include("weapi.django_rest.urls.subscriptions.v2.promotions")),
    path(r"/trial", include("weapi.django_rest.urls.subscriptions.v2.trial")),
    path(r"/lifecycle", include("weapi.django_rest.urls.subscriptions.v2.lifecycle")),
    path(r"/plan-changes", include("weapi.django_rest.urls.subscriptions.v2.plan_changes")),
]
