   
from django.urls import path
from weapi.django_rest.views.leaves.leave_balance import (
    PrivateWeLeaveBalanceListCreateView,
    PrivateWeLeaveBalanceDetailView,
    PrivateWeEmployeeLeaveAllocationListCreateView,
    PrivateWeEmployeeLeaveAllocationDetailView,
    CompanyEmployeeLeaveTypeListView
)

urlpatterns = [
    path(
        r"/",
        PrivateWeLeaveBalanceListCreateView.as_view(),
        name="leave_balance_list_create",
    ),
    path(
        r"/<uuid:uid>/",
        PrivateWeLeaveBalanceDetailView.as_view(),
        name="leave_balance_detail",
    ),
    path(
        r"/allocations/",
        PrivateWeEmployeeLeaveAllocationListCreateView.as_view(),
        name="leave_allocation_list_create",
    ),
    path(
        r"/allocations/<uuid:uid>/",
        PrivateWeEmployeeLeaveAllocationDetailView.as_view(),
        name="leave_allocation_detail",
    ),
    path(
        r"/company-employee-leave-types/",
        CompanyEmployeeLeaveTypeListView.as_view(),
        name="company_employee_leave_types",
    ),
]
