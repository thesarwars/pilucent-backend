from django.urls import path

from ..views.bd_salary import SalaryProfileList, SalaryStructureCancel, SalaryStructureOverrides, SalaryTemplateList

# The salary profile (docs/backend/salary-profile.md §6). The employee-scoped
# routes (/employees/{code}/salary-structures, /salary-history) live in
# urls/employees.py.
urlpatterns = [
    path(r"/salary-profiles", SalaryProfileList.as_view(), name="weapi.bd-salary-profiles"),
    path(r"/salary-templates", SalaryTemplateList.as_view(), name="weapi.bd-salary-templates"),
    path(r"/salary-structures/<uuid:uid>/overrides", SalaryStructureOverrides.as_view(),
         name="weapi.bd-salary-structure-overrides"),
    path(r"/salary-structures/<uuid:uid>/cancel", SalaryStructureCancel.as_view(),
         name="weapi.bd-salary-structure-cancel"),
]
