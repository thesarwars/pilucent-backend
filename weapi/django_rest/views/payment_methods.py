from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework import filters

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from paymentio.models import PaymentMethod
from paymentio.choices import PaymentMethodStatusChoices
from ..serializers.payment_methods import (
    PrivateWePaymentMethodListSerializer,
    PrivateWePaymentMethodDetailsSerializer,
)


class PrivateWePaymentMethodList(ListCreateAPIView):
    serializer_class = PrivateWePaymentMethodListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_payment_management"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return PaymentMethod.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWePaymentMethodDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePaymentMethodDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_payment_management"

    def get_object(self):
        return get_object_or_404(
            PaymentMethod.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = PaymentMethodStatusChoices.REMOVED
        instance.save()
