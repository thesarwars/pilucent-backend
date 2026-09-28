from rest_framework import response, status, views

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.offer_service import OfferService
from subscriptionio.services.referral_service import ReferralService
from subscriptionio.services.trial_service import TrialService


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionValidateCoupon(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        coupon_code = data.get("coupon_code")
        if not coupon_code:
            return response.Response(
                {"error": "coupon_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription_price = BillingPreviewService._resolve_subscription_price(
            subscription_price_slug=data.get("subscription_price_slug"),
            plan_title=data.get("plan_title"),
            billing_frequency=data.get("billing_frequency"),
        )
        existing_discount = (
            BillingPreviewService._apply_price_discount(subscription_price)[1]
            if subscription_price
            else 0
        )
        result = CouponService.validate(
            coupon_code,
            company=company,
            subscription_price=subscription_price,
            existing_plan_discount=existing_discount,
        )
        if not result.valid:
            return response.Response(
                {"valid": False, "message": result.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return response.Response(
            {
                "valid": True,
                "code": result.coupon.code,
                "discount_amount": str(result.discount_amount),
                "metadata": result.metadata,
            }
        )


class PrivateWeSubscriptionReferralCode(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        return response.Response(ReferralService.get_referral_dashboard(company))


class PrivateWeSubscriptionOfferList(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        subscription_price = BillingPreviewService._resolve_subscription_price(
            subscription_price_slug=request.query_params.get("subscription_price_slug"),
            plan_title=request.query_params.get("plan_title"),
            billing_frequency=request.query_params.get("billing_frequency"),
        )
        return response.Response(
            {
                "offers": OfferService.list_offers(
                    company,
                    subscription_price=subscription_price,
                )
            }
        )


class PrivateWeSubscriptionValidateOffer(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        offer_code = data.get("offer_code")
        if not offer_code:
            return response.Response(
                {"error": "offer_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription_price = BillingPreviewService._resolve_subscription_price(
            subscription_price_slug=data.get("subscription_price_slug"),
            plan_title=data.get("plan_title"),
            billing_frequency=data.get("billing_frequency"),
        )
        result = OfferService.validate(
            offer_code,
            company=company,
            subscription_price=subscription_price,
        )
        if not result.valid:
            return response.Response(
                {"valid": False, "message": result.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return response.Response(
            {
                "valid": True,
                "offer_code": result.offer.code if result.offer else offer_code,
                "coupon_code": result.coupon_code,
                "discount_amount": str(result.discount_amount),
                "metadata": result.metadata,
            }
        )


class PrivateWeSubscriptionTrialStatus(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        trial_status = TrialService.get_status(company)
        return response.Response(
            {
                "eligible": trial_status.eligible,
                "active": trial_status.active,
                "status": trial_status.status,
                "trial_start": trial_status.trial_start,
                "trial_end": trial_status.trial_end,
                "days_remaining": trial_status.days_remaining,
                "plan_title": trial_status.plan_title,
                "message": trial_status.message,
            }
        )


class PrivateWeSubscriptionTrialStart(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        trial_status = TrialService.start_trial(
            company,
            subscription_price_slug=data.get("subscription_price_slug"),
            plan_title=data.get("plan_title"),
            billing_frequency=data.get("billing_frequency"),
            created_by=request.user.get_employee(),
        )
        if not trial_status.active and trial_status.message:
            return response.Response(
                {"error": trial_status.message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(
            {
                "active": trial_status.active,
                "status": trial_status.status,
                "trial_start": trial_status.trial_start,
                "trial_end": trial_status.trial_end,
                "days_remaining": trial_status.days_remaining,
                "plan_title": trial_status.plan_title,
            },
            status=status.HTTP_201_CREATED,
        )
