from django.urls import path

from ..views.sale_reports import PrivateWeOpenInvoiceReportList, PrivateWeOpenInvoiceReportDetails

urlpatterns = [
    path(
        r"/open-invoices/<uuid:uid>",
        PrivateWeOpenInvoiceReportDetails.as_view(),
        name="weapi.sale-open-invoice-report-details",
    ),
    path(
        r"/open-invoices",
        PrivateWeOpenInvoiceReportList.as_view(),
        name="weapi.sale-open-invoice-report-list",
    )
]
