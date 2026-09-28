from django.urls import path, include
from ...views.payroll.pay_schedule import (
    PayScheduleListCreateView,
    PayScheduleUpdateView,
    PayScheduleAssignedEmployeeView,
    PayScheduleWithEmployeeCountView,
)

urlpatterns = [
    path(
        "", PayScheduleListCreateView.as_view(), name="POST.pay-schedule-list-create"
    ),  # /api/v1/we/payroll/pay-schedule
    path(
        "/<str:uid>/",
        PayScheduleUpdateView.as_view(),
        name="UP/DEL.deduction-and-contribution-individual",
    ),  # /api/v1/we/payroll/ded-con/uid
    path(
        "/employee-count",
        PayScheduleWithEmployeeCountView.as_view(),
        name="GET.employee-count",
    ),
    path(
        "/employees/<str:schedule_uid>/",
        PayScheduleAssignedEmployeeView.as_view(),
        name="GET.pay-schedule-employee",
    ),  # /api/v1/we/payroll/ded-con/employees
]
