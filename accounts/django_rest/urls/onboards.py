from django.urls import path

from ..views.onboards import EmployeeOnboardView

urlpatterns = [
    path("", EmployeeOnboardView.as_view(), name="accounts.employee-onboard")
]
