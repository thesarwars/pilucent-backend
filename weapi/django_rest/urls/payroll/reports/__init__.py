from django.urls import path, include

urlpatterns = [
    path("/payroll", include("weapi.django_rest.urls.payroll.reports.payroll_summary")),
    path("", include("weapi.django_rest.urls.payroll.reports.paycheck")),
]