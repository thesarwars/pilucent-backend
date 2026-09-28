from django.urls import path

from ..views.we import PrivateWeDetails, PrivateWeSettingDetails
from ..views.company_departments import (
    PrivateWeCompanyDepartmentList,
    PrivateWeCompanyDepartmentDetails,
)
from ..views.company_shifts import (
    PrivateWeCompanyShiftList,
    PrivateWeCompanyShiftDetails,
)
from ..views.company_sections import (
    PrivateWeCompanySectionList,
    PrivateWeCompanySectionDetails,
)
from ..views.company_designations import (
    PrivateWeCompanyDesignationList,
    PrivateWeCompanyDesignationDetails,
)

from ..views.employee_salaries import PrivateWeSalaryDetails
from ..views.employee_salaries import PrivateWeCompanyEmployeeSalaryList

urlpatterns = [
    path(
        r"/salaries",
        PrivateWeCompanyEmployeeSalaryList.as_view(),
        name="weapi.employee-salary-adjustment-list",
    ),
    path(
        r"/salary/<uuid:uid>",
        PrivateWeSalaryDetails.as_view(),
        name="weapi.employee-salary-details",
    ),
    # Designations
    path(
        r"/designations/<uuid:uid>",
        PrivateWeCompanyDesignationDetails.as_view(),
        name="weapi.private-designation-details",
    ),
    path(
        r"/designations",
        PrivateWeCompanyDesignationList.as_view(),
        name="weapi.private-designation-list",
    ),
    # Sections
    path(
        r"/sections/<uuid:uid>",
        PrivateWeCompanySectionDetails.as_view(),
        name="weapi.private-section-details",
    ),
    path(
        r"/sections",
        PrivateWeCompanySectionList.as_view(),
        name="weapi.private-section-list",
    ),
    # Shifts
    path(
        r"/shifts/<uuid:uid>",
        PrivateWeCompanyShiftDetails.as_view(),
        name="weapi.private-shift-details",
    ),
    path(
        r"/shifts",
        PrivateWeCompanyShiftList.as_view(),
        name="weapi.private-shift-list",
    ),
    # Department
    path(
        r"/departments/<uuid:uid>",
        PrivateWeCompanyDepartmentDetails.as_view(),
        name="weapi.private-deparment-details",
    ),
    path(
        r"/departments",
        PrivateWeCompanyDepartmentList.as_view(),
        name="weapi.private-deparment-list",
    ),
    path(
        r"/settings",
        PrivateWeSettingDetails.as_view(),
        name="weapi.company-setting-details",
    ),
    path(r"", PrivateWeDetails.as_view(), name="weapi.private-details"),
]
