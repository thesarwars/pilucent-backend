from django.urls import path, include
from ...views.payroll.work_location import (
    PayrollWorkLocationListCreateView,
    PayrollWorkLocationDetailView,
    PayrollWorkLocationListNoPaginationView,
)

urlpatterns = [
    path(
        r"/<uuid:uid>",
        PayrollWorkLocationDetailView.as_view(),
        name="weapi.leaves-details",
    ),
    path(
        r"/",
        PayrollWorkLocationListCreateView.as_view(),
        name="weapi.work-location-list",
    ),
    path(
        r"/list",
        PayrollWorkLocationListNoPaginationView.as_view(),
        name="weapi.work-location-list-nopagination",
    ),
]
