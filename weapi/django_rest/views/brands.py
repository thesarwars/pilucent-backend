from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from brandio.models import Brand

from brandio.choicess import BrandStatusChoices

from ..serializers.brands import (
    PrivateWeBrandListSerializer,
    PrivateWeBrandDetailsSerializer,
)


class PrivateWeBrandList(ListCreateAPIView):
    serializer_class = PrivateWeBrandListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return Brand.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeBrandDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeBrandDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            Brand.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = BrandStatusChoices.REMOVED
        instance.save()
