from django.urls import path
from weapi.django_rest.views.payroll.federal_tax_setting import (
    PrivateWePayrollFederalTaxInfoSettingListCreateView,
    PrivateWePayrollFederalTaxInfoSettingDetailUpdateView,
    PrivateWePayrollFederalTaxInfoSettingItemsCreateListView,
    PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateView,
)

urlpatterns = [
    path(
        r"",
        PrivateWePayrollFederalTaxInfoSettingListCreateView.as_view(),
        name="weapi.payroll-federal-tax-info-setting-list-create",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWePayrollFederalTaxInfoSettingDetailUpdateView.as_view(),
        name="weapi.payroll-federal-tax-info-setting-detail-update",
    ),
    path(
        r"/<uuid:uid>/items",
        PrivateWePayrollFederalTaxInfoSettingItemsCreateListView.as_view(),
        name="weapi.payroll-federal-tax-info-setting-items-create-list",
    ),
    path(
        r"/<uuid:uid>/items/<uuid:item_uid>",
        PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateView.as_view(),
        name="weapi.payroll-federal-tax-info-setting-items-detail-update",
    ),
]
