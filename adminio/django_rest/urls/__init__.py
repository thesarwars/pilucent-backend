from django.urls import path, include

urlpatterns = [
    path("", include("adminio.django_rest.urls.user_roles")),
    path("/admin-permissions", include("adminio.django_rest.urls.admin_permissions")),
    path(
        "/permissions-to-user-role",
        include("adminio.django_rest.urls.user_permissions"),
    ),
    path("/companies", include("adminio.django_rest.urls.companies")),
    path("/subscriptions", include("adminio.django_rest.urls.subscriptions")),
]
