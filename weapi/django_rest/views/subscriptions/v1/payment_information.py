from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from weapi.django_rest.serializers.subscriptions.v1.payment_information import (
    PrivateWeSubscriptionPaymentInformationListSerializer,
    PrivateWeSubscriptionPaymentInformationDetailsSerializer,
)

from paymentio.models import PaymentInformation


class PrivateWeSubscriptionPaymentInformationList(ListCreateAPIView):
    serializer_class = PrivateWeSubscriptionPaymentInformationListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return PaymentInformation.objects.filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeSubscriptionPaymentInformationDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeSubscriptionPaymentInformationDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            PaymentInformation.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid"),
            ).select_related("company", "subscription", "payment_method")
        )
