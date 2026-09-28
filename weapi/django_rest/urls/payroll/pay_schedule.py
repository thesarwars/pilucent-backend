from django.urls import path, include
from ...views.payroll.pay_schedule import (
    PayScheduleListCreateView,
    PayScheduleUpdateView,
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
]
