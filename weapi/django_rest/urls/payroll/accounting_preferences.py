from django.urls import path
from weapi.django_rest.views.payroll.accounting_preferences import (
    PrivateWePayrollAccountingPreferencesListCreateView,
)

urlpatterns = [
    path(
        r"",
        PrivateWePayrollAccountingPreferencesListCreateView.as_view(),
        name="private_we_payroll_accounting_preferences_list_create",
    )
]