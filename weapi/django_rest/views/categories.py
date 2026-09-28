from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from categoryio.models import Category

from categoryio.choicess import CategoryStatusChoices

from ..serializers.categories import (
    PrivateWeCategoryListSerializer,
    PrivateWeCategoryDetailsSerializer,
)


class PrivateWeCategoryList(ListCreateAPIView):
    serializer_class = PrivateWeCategoryListSerializer
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
        return Category.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeCategoryDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCategoryDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            Category.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = CategoryStatusChoices.REMOVED
        instance.save()
