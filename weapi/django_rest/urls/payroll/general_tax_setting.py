from django.urls import path
from weapi.django_rest.views.payroll.general_tax_setting import (
    PrivateWePayrollGeneralTaxSettingListCreateView,
    PrivateWePayrollGeneralTaxSettingDetailUpdateView,
)

urlpatterns = [
    path(
        r"",
        PrivateWePayrollGeneralTaxSettingListCreateView.as_view(),
        name="weapi.payroll-general-tax-setting-list-create",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWePayrollGeneralTaxSettingDetailUpdateView.as_view(),
        name="weapi.payroll-general-tax-setting-detail-update",
    ),
]
