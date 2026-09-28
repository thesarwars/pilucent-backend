from typing import Any

from django.db import transaction
from django.db.models import Q

from subscriptionio.choices import CouponStatusChoices, OfferStatusChoices
from subscriptionio.models import CouponRedemption, Subscription, SubscriptionCoupon, SubscriptionOffer


class AdminCouponService:
    @classmethod
    def _serialize_redemption(cls, redemption: CouponRedemption) -> dict[str, Any]:
        return {
            "uid": str(redemption.uid),
            "coupon_uid": str(redemption.coupon.uid),
            "coupon_code": redemption.coupon.code,
            "company_uid": str(redemption.company.uid),
            "company_name": redemption.company.name,
            "company_email": redemption.company.email,
            "discount_amount": str(redemption.discount_amount),
            "checkout_session_id": redemption.checkout_session_id,
            "created_at": redemption.created_at,
        }

    @classmethod
    def get_redemptions_queryset(
        cls,
        *,
        coupon=None,
        search: str | None = None,
    ):
        queryset = CouponRedemption.objects.select_related(
            "coupon", "company"
        ).order_by("-created_at")

        if coupon:
            queryset = queryset.filter(coupon=coupon)

        if search:
            queryset = queryset.filter(
                Q(coupon__code__icontains=search)
                | Q(company__name__icontains=search)
                | Q(company__email__icontains=search)
            )
        return queryset

    @classmethod
    def serialize_redemptions(cls, redemptions) -> list[dict[str, Any]]:
        return [cls._serialize_redemption(item) for item in redemptions]

    @classmethod
    def list_redemptions(
        cls,
        *,
        coupon=None,
        search: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        queryset = cls.get_redemptions_queryset(coupon=coupon, search=search)
        limit = min(max(limit, 1), 200)
        items = queryset[:limit]
        return {
            "count": len(items),
            "results": cls.serialize_redemptions(items),
        }

    @classmethod
    def set_applies_to_subscriptions(
        cls, coupon: SubscriptionCoupon, subscription_uids: list | None
    ):
        if subscription_uids is None:
            return
        subscriptions = Subscription.objects.filter(uid__in=subscription_uids)
        coupon.applies_to_subscriptions.set(subscriptions)

    @classmethod
    @transaction.atomic
    def delete_coupon(cls, coupon: SubscriptionCoupon) -> dict[str, str]:
        if coupon.redemptions.exists():
            coupon.status = CouponStatusChoices.DISABLED
            coupon.save(update_fields=["status", "updated_at"])
            return {"status": "disabled", "message": "Coupon disabled because it has redemptions."}
        coupon.delete()
        return {"status": "deleted", "message": "Coupon deleted."}

    @classmethod
    @transaction.atomic
    def delete_offer(cls, offer: SubscriptionOffer) -> dict[str, str]:
        offer.status = OfferStatusChoices.EXPIRED
        offer.save(update_fields=["status", "updated_at"])
        return {"status": "expired", "message": "Offer archived."}
