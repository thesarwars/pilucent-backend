from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from categoryio.choicess import CategoryKindChoices
from categoryio.django_rest.serializers.common import PublicCategorySlimSerializer
from categoryio.models import Category

from ..serializers.categories import (
    PublicCategoryChartOfAccountListSerializer,
    PublicCategoryChartOfAccountDetailsSerializer,
)


class PublicCategoryList(ListAPIView):
    serializer_class = PublicCategorySlimSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status", "title", "kind"]
    queryset = Category.objects.get_status_active()

    def get_serializer_class(self):
        return (
            PublicCategoryChartOfAccountListSerializer
            if (
                self.request.query_params.get("kind", None)
                == CategoryKindChoices.CHART_OF_ACCOUNT
            )
            else super().get_serializer_class()
        )

    def get_queryset(self):
        queryset = self.queryset
        return (
            queryset.filter(
                parent__isnull=True, kind=CategoryKindChoices.CHART_OF_ACCOUNT
            )
            if (
                self.request.query_params.get("kind", None)
                == CategoryKindChoices.CHART_OF_ACCOUNT
            )
            else queryset.exclude(kind=CategoryKindChoices.CHART_OF_ACCOUNT)
        )


class PublicCategoryDetails(RetrieveAPIView):
    serializer_class = PublicCategorySlimSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Category.objects.get_status_active()
    lookup_field = "slug"

    def get_serializer_class(self):
        return (
            PublicCategoryChartOfAccountDetailsSerializer
            if (self.get_object().kind == CategoryKindChoices.CHART_OF_ACCOUNT)
            else super().get_serializer_class()
        )
