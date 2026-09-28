from django.urls import path
from weapi.django_rest.views.payment_methods import (
    PrivateWePaymentMethodList,
    PrivateWePaymentMethodDetails,
)

urlpatterns = [
    path(r"", PrivateWePaymentMethodList.as_view(), name="weapi.payment-method-list"),
    path(
        r"/<uuid:uid>",
        PrivateWePaymentMethodDetails.as_view(),
        name="weapi.payment-method-details",
    ),
]
