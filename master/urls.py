import os

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from common.django_rest.views.home import home_view

# Change Admin Top Nav Header
admin.site.site_header = "Pilucent"

urlpatterns = [
    # Swagger
    path(r"", home_view, name="home"),
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    # Swagger
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Django Admin
    path("admin/", admin.site.urls),
    # Google Auth
    path("api/v1", include("socailauthio.django_rest.google.urls")),
    # User Accounts related APIs
    path("api/v1/accounts", include("accounts.django_rest.urls")),
    # Personal endpoints
    path("api/v1/me", include("meapi.django_rest.urls")),
    # Company related APIs
    path("api/v1/we", include("weapi.django_rest.urls")),
    path("api/v2/we", include("weapi.django_rest.urls.v2")),
    # Admin related APIs
    path("api/v1/adminio", include("adminio.django_rest.urls")),
    path("api/v2/adminio", include("adminio.django_rest.urls.v2")),
    # Chat (ChatRoom CRUD + WebSocket message part in consumers)
    path("api/v1/chat", include("chatio.django_rest.urls")),
    # Public APIs
    path("api/v1/public", include("publicapi.django_rest.urls")),
    path("api/v2/public", include("publicapi.django_rest.urls.v2")),
]

# Profiling
if os.environ.get("DEBUG") == "True":
    urlpatterns += [path("profiling", include("silk.urls", namespace="silk"))]

    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

