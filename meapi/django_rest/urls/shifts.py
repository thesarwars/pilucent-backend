from django.urls import path

from ..views.shifts import PrivateMeShiftDetails

urlpatterns = [
    path(
        "",
        PrivateMeShiftDetails.as_view(),
        name="meapi.shift-details",
    ),
]
