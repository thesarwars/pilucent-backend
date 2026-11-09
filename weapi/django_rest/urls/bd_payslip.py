from django.urls import path

from ..views import bd_payslip as v

# Payslip and compliance (docs/backend/payslip-compliance-done.md §6).
urlpatterns = [
    path(r"", v.PsRoster.as_view(), name="weapi.bd-payslip-roster"),
    path(r"/<uuid:uid>", v.PsDocument.as_view(), name="weapi.bd-payslip-document"),
    path(r"/<uuid:uid>/printed", v.PsPrinted.as_view(), name="weapi.bd-payslip-printed"),
    path(r"/<uuid:uid>/findings/<uuid:finding>/resolve", v.PsResolve.as_view(), name="weapi.bd-payslip-resolve"),
    path(r"/<uuid:uid>/supersede", v.PsSupersede.as_view(), name="weapi.bd-payslip-supersede"),
    path(r"/<uuid:uid>/deliveries", v.PsDeliver.as_view(), name="weapi.bd-payslip-deliver"),
]
