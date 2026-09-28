from django.urls import path
from ...views.payroll.salary_process import (
    PayrollSalaryProcessListCreateView,
    PayrollSalaryProcessDetailView,
    PayrollSalaryProcessVoidView,
    PayrollSalaryProcessPayView,
    PayrollPaymentTabCountsView,
)


urlpatterns = [
    path("", PayrollSalaryProcessListCreateView.as_view(), name="GET.salary-process-list-create"), # /api/v1/we/payroll/salary-process
    path(
        "/tab-counts",
        PayrollPaymentTabCountsView.as_view(),
        name="GET.salary-process-tab-counts",
    ),  # /api/v1/we/payroll/salary-process/tab-counts
    path(
        "/<str:uid>/void",
        PayrollSalaryProcessVoidView.as_view(),
        name="POST.salary-process-void",
    ),  # /api/v1/we/payroll/salary-process/<uid>/void
    path(
        "/<str:uid>/pay",
        PayrollSalaryProcessPayView.as_view(),
        name="POST.salary-process-pay",
    ),  # /api/v1/we/payroll/salary-process/<uid>/pay
    path("/<str:uid>/", PayrollSalaryProcessDetailView.as_view(), name="GET.salary-process-detail"), # /api/v1/we/payroll/salary-process/<str:uid>/
]