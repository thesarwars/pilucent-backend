from django.urls import path

from ..views.bd_employees import (
    BDEmployeeCompliance,
    BDEmployeeDetail,
    BDEmployeeEmployment,
    BDEmployeeHistory,
    BDEmployeeInvestments,
    BDEmployeeListCreate,
    BDEmployeeNominees,
    BDEmployeePayment,
    BDEmployeePersonal,
    BDEmployeeSalary,
    BDEmployeeStatutory,
    BDEmployeeTaxProfile,
    BDEmployeeTaxProjection,
)
from ..views.employee_roles import (
    EmployeeRoleAssignView,
    EmployeeRoleUnassignView,
    EmployeeExtraPermissionsView,
)


urlpatterns = [
    # Role + permission overlay management (by uid, ahead of the code routes)
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
    # BD employee profile, keyed by business code (docs/employee-profile.md §9)
    path(r"", BDEmployeeListCreate.as_view(), name="weapi.bd-employee-list"),
    path(r"/<str:code>", BDEmployeeDetail.as_view(), name="weapi.bd-employee-detail"),
    path(r"/<str:code>/personal", BDEmployeePersonal.as_view(), name="weapi.bd-employee-personal"),
    path(r"/<str:code>/employment", BDEmployeeEmployment.as_view(), name="weapi.bd-employee-employment"),
    path(r"/<str:code>/statutory", BDEmployeeStatutory.as_view(), name="weapi.bd-employee-statutory"),
    path(r"/<str:code>/tax-profile", BDEmployeeTaxProfile.as_view(), name="weapi.bd-employee-tax-profile"),
    path(r"/<str:code>/payment", BDEmployeePayment.as_view(), name="weapi.bd-employee-payment"),
    path(r"/<str:code>/compliance", BDEmployeeCompliance.as_view(), name="weapi.bd-employee-compliance"),
    path(r"/<str:code>/tax-projection", BDEmployeeTaxProjection.as_view(), name="weapi.bd-employee-tax-projection"),
    path(r"/<str:code>/nominees", BDEmployeeNominees.as_view(), name="weapi.bd-employee-nominees"),
    path(r"/<str:code>/investments", BDEmployeeInvestments.as_view(), name="weapi.bd-employee-investments"),
    path(r"/<str:code>/history", BDEmployeeHistory.as_view(), name="weapi.bd-employee-history"),
    path(r"/<str:code>/salary", BDEmployeeSalary.as_view(), name="weapi.bd-employee-salary"),
]
