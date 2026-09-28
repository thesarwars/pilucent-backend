from django.urls import path

from ..views.employees import (
    PrivateWeEmployeeList,
    PrivateWeEmployeeDetails,
    PrivateWeEmployeeEducationList,
    PrivateWeEmployeeEducationDetails,
    PrivateWeEmployeeBankingInformationList,
    PrivateWeEmployeeBankingInformationDetails,
    PrivateWeEmployeeTaxList,
    PrivateWeEmployeeTaxDetails,
    PrivateWeEmployeeEarningList,
    PrivateWeEmployeeEarningDetails,
    PrivateWeEmployeeDeductionContributionList,
    PrivateWeEmployeeDeductionContributionDetails,
    PrivateWeEmployeeGarnishmentList,
    PrivateWeCompanyGarnishmentList,
    PrivateWeEmployeeGarnishmentDetails,
    PrivateWeEmployeeWorkExperienceList,
    PrivateWeEmployeeWorkExperienceDetails,
    PrivateWeEmployeeDocumentList,
    PrivateWeEmployeeDocumentDetails,
    PrivateWeEmployeeListAll,
)

from ..views.employee_job_cards import PrivateWeEmployeeJobCardOverView

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
    # Job card related
    path(
        r"/<uuid:uid>/job-card-overview",
        PrivateWeEmployeeJobCardOverView.as_view(),
        name="weapi.employee-job-card-overview",
    ),
    # Work Experience related
    path(
        r"/<uuid:uid>/documents/<uuid:document_uid>",
        PrivateWeEmployeeDocumentDetails.as_view(),
        name="weapi.employee-document-details",
    ),
    path(
        r"/<uuid:uid>/documents",
        PrivateWeEmployeeDocumentList.as_view(),
        name="weapi.employee-document-list",
    ),
    # Work Experience related
    path(
        r"/<uuid:uid>/work-experiences/<uuid:work_experience_uid>",
        PrivateWeEmployeeWorkExperienceDetails.as_view(),
        name="weapi.employee-work-experience-details",
    ),
    path(
        r"/<uuid:uid>/work-experiences",
        PrivateWeEmployeeWorkExperienceList.as_view(),
        name="weapi.employee-work-experience-list",
    ),
    # Garnishment related
    path(
        r"/<uuid:uid>/garnishments/<uuid:garnishment_uid>",
        PrivateWeEmployeeGarnishmentDetails.as_view(),
        name="weapi.employee-garnishment-details",
    ),
    path(
        r"/<uuid:uid>/garnishments",
        PrivateWeEmployeeGarnishmentList.as_view(),
        name="weapi.employee-garnishment-list",
    ),
    path(
        r"/garnishments-list",
        PrivateWeCompanyGarnishmentList.as_view(),
        name="weapi.employee-garnishment-list-all",
    ),
    # Deduction and Contribution related
    path(
        r"/<uuid:uid>/deduction-contributions/<uuid:deduction_and_contribution_uid>",
        PrivateWeEmployeeDeductionContributionDetails.as_view(),
        name="weapi.employee-deduction-contribution-details",
    ),
    path(
        r"/<uuid:uid>/deduction-contributions",
        PrivateWeEmployeeDeductionContributionList.as_view(),
        name="weapi.employee-deduction-contribution-list",
    ),
    # Earning related
    path(
        r"/<uuid:uid>/earnings/<uuid:earning_uid>",
        PrivateWeEmployeeEarningDetails.as_view(),
        name="weapi.employee-earning-details",
    ),
    path(
        r"/<uuid:uid>/earnings",
        PrivateWeEmployeeEarningList.as_view(),
        name="weapi.employee-earning-list",
    ),
    # Education related
    path(
        r"/<uuid:uid>/educations/<uuid:education_uid>",
        PrivateWeEmployeeEducationDetails.as_view(),
        name="weapi.employee-education-details",
    ),
    path(
        r"/<uuid:uid>/educations",
        PrivateWeEmployeeEducationList.as_view(),
        name="weapi.employee-education-list",
    ),
    # Tax related
    path(
        r"/<uuid:uid>/taxes/<uuid:tax_uid_uid>",
        PrivateWeEmployeeTaxDetails.as_view(),
        name="weapi.employee-tax-details",
    ),
    path(
        r"/<uuid:uid>/taxes",
        PrivateWeEmployeeTaxList.as_view(),
        name="weapi.employee-tax-list",
    ),
    # Banking Related
    path(
        r"/<uuid:uid>/banking-informations/<uuid:banking_information_uid>",
        PrivateWeEmployeeBankingInformationDetails.as_view(),
        name="weapi.employee-details",
    ),
    path(
        r"/<uuid:uid>/banking-informations",
        PrivateWeEmployeeBankingInformationList.as_view(),
        name="weapi.employee-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeEmployeeDetails.as_view(),
        name="weapi.employee-details",
    ),
    path(r"", PrivateWeEmployeeList.as_view(), name="weapi.employee-list"),
    path(r"/list", PrivateWeEmployeeListAll.as_view(), name="weapi.employee-list-all"),
]
