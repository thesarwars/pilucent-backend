from django.urls import include, path

urlpatterns = [
    # v1 keeps its original endpoints (e.g. /subscriptions/checkout) so
    # existing frontend integrations do not break.
    path(r"", include("weapi.django_rest.urls.subscriptions.v1")),
]
