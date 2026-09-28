from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView, RetrieveAPIView, get_object_or_404
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from subscriptionio.choices import SubscriptionStatusChoices
from subscriptionio.models import Subscription, SubscriptionPrice

from ..serializers.subscription_plan import (
    PublicSubscriptionListSerializer,
    PublicSubscriptionDetailsSerializer,
    PublicSubscriptionPriceListSerializer,
)


class PublicSubscriptionList(ListAPIView):
    serializer_class = PublicSubscriptionListSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["status", "kind"]
    queryset = Subscription.objects.filter(status=SubscriptionStatusChoices.PUBLISHED)


class PublicSubscriptionDetails(RetrieveAPIView):
    serializer_class = PublicSubscriptionDetailsSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Subscription.objects.filter(status=SubscriptionStatusChoices.PUBLISHED)
    lookup_field = "slug"


class PublicSubscriptionPriceList(ListAPIView):
    serializer_class = PublicSubscriptionPriceListSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["slug"]
    filterset_fields = ["billing_frequency", "discount_kind", "discount"]

    def get_queryset(self):
        return SubscriptionPrice.objects.filter(
            subscription=get_object_or_404(
                Subscription.objects.filter(
                    status=SubscriptionStatusChoices.PUBLISHED,
                    slug=self.kwargs.get("slug"),
                ),
            ),
        )
