from django.urls import path
from weapi.django_rest.views.payroll.state_tax_setting import (
    PrivateWePayrollStateTaxSettingView,
    PrivateWePayrollStateTaxSettingDetailsUpdateView,
    PrivateWePayrollStateTaxRelatedDeleteView,
)

urlpatterns = [
    path(
        r"",
        PrivateWePayrollStateTaxSettingView.as_view(),
        name="weapi-payroll-state-tax-setting-list-create",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWePayrollStateTaxSettingDetailsUpdateView.as_view(),
        name="weapi-payroll-state-tax-setting-detail-update",
    ),
    path(
        r"/item-delete/<uuid:uid>",
        PrivateWePayrollStateTaxRelatedDeleteView.as_view(),
        name="weapi-payroll-state-tax-setting-related-delete",
    ),
]
