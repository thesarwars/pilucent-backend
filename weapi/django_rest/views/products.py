from datetime import date

from django.db.models import Count, Q, F

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters, response
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
    CreateAPIView,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from categoryio.models import CategoryConnector

from common.django_rest.permissions.company_subscription import HaveSubscription

from productio.django_rest.serializers.common import PrivateProductSlimSerializer
from productio.choices import ProductStatusChoices, ProductBundleStatusChoices
from productio.models import Product, ProductBundle

from ..serializers.products import (
    PrivateWeProductListSerializer,
    PrivateWeProductDetailsSerializer,
    PrivateWeProductBundleListSerializer,
    PrivateWeProductBundleDetailsSerializer,
    PrivateWeProductBulkCreateSerializer,
)


class PrivateWeProductList(ListCreateAPIView):
    serializer_class = PrivateWeProductListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        queryset = Product.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
        if category_uid := self.request.query_params.get("category", None):
            queryset = queryset.filter(
                id__in=CategoryConnector.objects.filter(
                    category__uid=category_uid
                ).values_list("product_id", flat=True)
            )

        if keyword := self.request.query_params.get("keywords", None):
            filter_condition = {
                "low_stock": Q(quantity__lte=F("reorder_point")),
                "out_of_stock": Q(quantity__lt=1),
                "expired_stock": Q(expired_date__lt=date.today()),
            }.get(keyword)
            if filter_condition:
                queryset = queryset.filter(filter_condition)

        return queryset

    def list(self, request, *args, **kwargs):
        return (
            response.Response(
                self.get_queryset().aggregate(
                    stock_count=Count(
                        "id",
                        filter=Q(quantity__gt=0),
                    ),
                    low_stock_count=Count(
                        "id",
                        filter=Q(quantity__lte=F("reorder_point")),
                    ),
                    out_of_stock_count=Count(
                        "id",
                        filter=Q(quantity__lt=1),
                    ),
                    expired_stock_count=Count(
                        "id",
                        filter=Q(expired_date__lt=date.today()),
                    ),
                )
            )
            if request.query_params.get("keywords", None) == "overview"
            else super().list(request, *args, **kwargs)
        )


class PrivateWeProductDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeProductDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"

    def get_object(self):
        return get_object_or_404(
            Product.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = ProductStatusChoices.REMOVED
        instance.save()


class PrivateWeBundleCreate(ListCreateAPIView):
    serializer_class = PrivateWeProductBundleListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]

    filterset_fields = ["status"]

    def get_queryset(self):
        return ProductBundle.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeBundleDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeProductBundleDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"

    def get_object(self):
        return get_object_or_404(
            ProductBundle.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = ProductBundleStatusChoices.REMOVED
        instance.save()


class PrivateWeBundleItemList(ListAPIView):
    serializer_class = PrivateProductSlimSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return Product.objects.filter(
            id__in=get_object_or_404(
                ProductBundle.objects.get_status_all(),
                company=self.request.user.get_active_company(),
                uid=self.kwargs["uid"],
            ).productbundleconnector_set.values_list("products_id", flat=True)
        )


class PrivateWeProductBulkCreate(CreateAPIView):
    serializer_class = PrivateWeProductBulkCreateSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_inventory"

    def get_queryset(self):
        return Product.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
