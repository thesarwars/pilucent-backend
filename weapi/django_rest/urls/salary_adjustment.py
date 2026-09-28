from django.urls import path, include
from ..views.salary_adjustment import PrivateWeCompanyEmployeeSalaryAdjustmentList, PrivateWeCompanyEmployeeSalaryAdjustmentDetail

urlpatterns = [
    path(r"", 
        PrivateWeCompanyEmployeeSalaryAdjustmentList.as_view(), 
        name="weapi.employee-salary-adjustment-list"
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeCompanyEmployeeSalaryAdjustmentDetail.as_view(),
        name="weapi.employee-salary-adjustment-detail",
    ),
]
