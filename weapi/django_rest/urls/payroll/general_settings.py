from django.urls import path, include
from ...views.payroll.general_settings import PayrollGeneralSettingsRetrieveUpdateView

urlpatterns = [
    path(
        r"/",
        PayrollGeneralSettingsRetrieveUpdateView.as_view(),
        name="weapi.general-settings",
    ),
]