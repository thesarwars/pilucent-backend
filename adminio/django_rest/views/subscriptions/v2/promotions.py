from rest_framework import generics, response, status, views
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.mixins.subscription_pagination import (
    AdminSubscriptionPaginationMixin,
)
from adminio.django_rest.serializers.promotions import (
    AdminSubscriptionCouponSerializer,
    AdminSubscriptionOfferSerializer,
)
from adminio.mixins import IsSuperAdmin
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination

from subscriptionio.models import SubscriptionCoupon, SubscriptionOffer
from subscriptionio.services.admin_coupon_service import AdminCouponService


class AdminSubscriptionCouponListCreate(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionCouponSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        return (
            SubscriptionCoupon.objects.prefetch_related("applies_to_subscriptions")
            .all()
            .order_by("-created_at")
        )


class AdminSubscriptionCouponRedemptionList(
    AdminSubscriptionPaginationMixin, generics.ListAPIView
):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminCouponService.get_redemptions_queryset(
            search=self.request.query_params.get("search"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminCouponService.serialize_redemptions,
        )


class AdminSubscriptionCouponDetail(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionCouponSerializer
    lookup_field = "uid"

    def get_queryset(self):
        return SubscriptionCoupon.objects.prefetch_related("applies_to_subscriptions")

    def destroy(self, request, *args, **kwargs):
        coupon = self.get_object()
        result = AdminCouponService.delete_coupon(coupon)
        return response.Response(result, status=status.HTTP_200_OK)


class AdminSubscriptionCouponRedemptions(
    AdminSubscriptionPaginationMixin, generics.ListAPIView
):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        coupon = get_object_or_404(SubscriptionCoupon, uid=self.kwargs["uid"])
        return AdminCouponService.get_redemptions_queryset(coupon=coupon)

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminCouponService.serialize_redemptions,
        )


class AdminSubscriptionOfferListCreate(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionOfferSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        return SubscriptionOffer.objects.select_related("coupon").order_by(
            "-created_at"
        )


class AdminSubscriptionOfferDetail(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionOfferSerializer
    lookup_field = "uid"

    def get_queryset(self):
        return SubscriptionOffer.objects.select_related("coupon")

    def destroy(self, request, *args, **kwargs):
        offer = self.get_object()
        result = AdminCouponService.delete_offer(offer)
        return response.Response(result, status=status.HTTP_200_OK)
