from django.urls import path, include
from rest_framework.routers import DefaultRouter
from weapi.django_rest.views.transactions.pdf_transactions import (
    TransactionInformationViewSet
)

router = DefaultRouter()
router.register(r'', TransactionInformationViewSet, basename='weapi-transactions')

urlpatterns = [
    path('/', include(router.urls)),
]
