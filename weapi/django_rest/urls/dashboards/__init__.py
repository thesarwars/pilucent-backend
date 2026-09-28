from django.urls import include, path

urlpatterns = [
    # v1 keeps its original endpoints (e.g. /dashboards/finance-overview) so
    # existing frontend integrations do not break.
    path(r"", include("weapi.django_rest.urls.dashboards.v1")),
    # v2 lives under /dashboards/v2/...
    path(r"/v2", include("weapi.django_rest.urls.dashboards.v2")),
]
