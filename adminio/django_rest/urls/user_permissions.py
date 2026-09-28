from django.urls import path
from adminio.django_rest.views.user_permissions import (
    PermissionsToCompanyUser,
    ViewPermissionsOfUser,
)

urlpatterns = [
    path(
        "/company/<str:company_uid>",
        PermissionsToCompanyUser.as_view(),
        name="POST.companyio.add-role-permissions-to-company-user",
    ),
    path(
        "",
        ViewPermissionsOfUser.as_view(),
        name="GET.companyio.view-permissions-of-user-role",
    ),
]
