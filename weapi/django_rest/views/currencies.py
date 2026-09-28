from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    get_object_or_404,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from currencyio.models import Currency

from ..serializers.currencies import (
    PrivateWeCurrencyListSerializer,
    PrivateWeCurrencyDetailsSerializer,
)


class PrivateWeCurrencyList(ListCreateAPIView):
    serializer_class = PrivateWeCurrencyListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_multicurrency"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "description"]

    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return Currency.objects.filter(company=self.request.user.get_active_company())


class PrivateWeCurrencyDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCurrencyDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_multicurrency"

    def get_object(self):
        return get_object_or_404(
            Currency.objects.filter(
                uid=self.kwargs.get("uid"),
                company=self.request.user.get_active_company(),
            )
        )
