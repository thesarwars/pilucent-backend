from django.urls import path

from adminio.django_rest.views.user_roles import (
    RoleCreateView,
    RoleBulkDeleteView,
    # RoleDeleteView,
    RoleModify,
    RoleSlimViewAPI,
    RoleView,
)

urlpatterns = [
    path(
        "/users-roles", RoleCreateView.as_view(), name="POST.adminio.create-role"
    ),  # api/v1/adminio/users-roles
    path(
        "/users-roles-slim/<str:company_uid>",
        RoleSlimViewAPI.as_view(),
        name="GET.adminio.get-role-slim",
    ),  # api/v1/adminio/users-roles-slim/<company_uid>?kind=USER
    path(
        "/users-roles/<str:company_uid>",
        RoleView.as_view(),
        name="GET.adminio.get-role",
    ),  # api/v1/adminio/users-roles/<company_uid>?kind=admin
    path(
        "/modify-role", RoleModify.as_view(), name="PATCH.adminio.modify-role"
    ),  # api/v1/adminio/modify-role?company_uid=<company_uid>&role_uid=<role_uid>
    path(
        "/delete-roles",
        RoleBulkDeleteView.as_view(),
        name="DELETE.adminio.bulk-delete-roles",
    ),  # api/v1/adminio/delete-roles  (payload: {role_uids: [...]})
    # path(
    #     "/delete-roles/<uuid:role_uid>",
    #     RoleDeleteView.as_view(),
    #     name="DELETE.adminio.delete-role",
    # ),  # api/v1/adminio/delete-roles/<role_uid>
]
