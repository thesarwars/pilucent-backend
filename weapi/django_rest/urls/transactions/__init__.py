from django.urls import path, include

urlpatterns = [
    path("", include("weapi.django_rest.urls.transactions.pdf_transactions")),
    path("/csv", include("weapi.django_rest.urls.transactions.csv_transactions")),
    path("/rules", include("weapi.django_rest.urls.transactions.rules")),
    path("/bank-deposits", include("weapi.django_rest.urls.transactions.bank_deposits")),
    path("/reconcile", include("weapi.django_rest.urls.transactions.bank_reconcile")),
]
