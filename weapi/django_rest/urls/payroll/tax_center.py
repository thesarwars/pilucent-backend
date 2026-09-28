from django.urls import path

from weapi.django_rest.views.payroll.tax_center import (
    PayrollTaxFiling940DownloadView,
    PayrollTaxFilingDownloadView,
    PayrollTaxFilingMarkFiledView,
    PayrollTaxFilingPreView,
    PayrollTaxPayProcessView,
    TaxCenterReportView,
)

urlpatterns = [
    path("", TaxCenterReportView.as_view()),
    path("/pay", PayrollTaxPayProcessView.as_view()),
    path("/filing-preview", PayrollTaxFilingPreView.as_view()),
    path("/file-941/download", PayrollTaxFilingDownloadView.as_view()),
    path("/file-940/download", PayrollTaxFiling940DownloadView.as_view()),
    path("/file-941/mark-filed", PayrollTaxFilingMarkFiledView.as_view()),
]
