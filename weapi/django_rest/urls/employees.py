from django.urls import path

from ..views.employee_roles import (
    EmployeeRoleAssignView,
    EmployeeRoleUnassignView,
    EmployeeExtraPermissionsView,
)


urlpatterns = [
    # Role + permission overlay management
    path(
        r"/<uuid:uid>/roles",
        EmployeeRoleAssignView.as_view(),
        name="weapi.employee-roles-assign",
    ),
    path(
        r"/<uuid:uid>/roles/<uuid:role_uid>",
        EmployeeRoleUnassignView.as_view(),
        name="weapi.employee-roles-unassign",
    ),
    path(
        r"/<uuid:uid>/extra-permissions",
        EmployeeExtraPermissionsView.as_view(),
        name="weapi.employee-extra-permissions",
    ),
]
