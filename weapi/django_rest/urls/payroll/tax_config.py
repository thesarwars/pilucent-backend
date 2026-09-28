from django.urls import path

from weapi.django_rest.views.payroll.tax_config import (
    PayrollTaxConfigReadView,
    PayrollTaxConfigListView,
    PayrollTaxConfigAdminWriteView,
    PayrollTaxConfigPublishView,
)

urlpatterns = [
    path(
        r"/current",
        PayrollTaxConfigReadView.as_view(),
        name="weapi-payroll-tax-config-current",
    ),
    path(
        r"/<int:year>/<str:jurisdiction>/publish",
        PayrollTaxConfigPublishView.as_view(),
        name="weapi-payroll-tax-config-publish",
    ),
    path(
        r"/<int:year>/<str:jurisdiction>",
        PayrollTaxConfigAdminWriteView.as_view(),
        name="weapi-payroll-tax-config-write",
    ),
    path(
        r"/<int:year>",
        PayrollTaxConfigReadView.as_view(),
        name="weapi-payroll-tax-config-year",
    ),
    path(
        r"",
        PayrollTaxConfigListView.as_view(),
        name="weapi-payroll-tax-config-list",
    ),
]
