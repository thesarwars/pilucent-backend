from django.urls import path

from adminio.django_rest.views.subscriptions.v2.promotions import (
    AdminSubscriptionCouponDetail,
    AdminSubscriptionCouponListCreate,
    AdminSubscriptionCouponRedemptionList,
    AdminSubscriptionCouponRedemptions,
    AdminSubscriptionOfferDetail,
    AdminSubscriptionOfferListCreate,
)

urlpatterns = [
    path(
        r"/coupons/redemptions",
        AdminSubscriptionCouponRedemptionList.as_view(),
        name="adminio.subscription-coupon-redemption-list",
    ),
    path(
        r"/coupons/<uuid:uid>/redemptions",
        AdminSubscriptionCouponRedemptions.as_view(),
        name="adminio.subscription-coupon-redemptions",
    ),
    path(
        r"/coupons/<uuid:uid>",
        AdminSubscriptionCouponDetail.as_view(),
        name="adminio.subscription-coupon-detail",
    ),
    path(
        r"/coupons",
        AdminSubscriptionCouponListCreate.as_view(),
        name="adminio.subscription-coupon-list",
    ),
    path(
        r"/offers/<uuid:uid>",
        AdminSubscriptionOfferDetail.as_view(),
        name="adminio.subscription-offer-detail",
    ),
    path(
        r"/offers",
        AdminSubscriptionOfferListCreate.as_view(),
        name="adminio.subscription-offer-list",
    ),
]
