import logging

from django.db import transaction
from rest_framework import response, status, views

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.stripe_checkout_service import StripeCheckoutService

logger = logging.getLogger("weapi.stripe")


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionCheckoutV2(views.APIView):
    """Create a Stripe checkout session with base plan + employee/user overage items."""

    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        user = request.user
        company = user.get_active_company()
        data = request.data

        employee_count = data.get("employee_count")
        user_count = data.get("user_count")
        if employee_count is not None:
            employee_count = int(employee_count)
        if user_count is not None:
            user_count = int(user_count)

        try:
            payload = StripeCheckoutService.create_checkout_session(
                user=user,
                company=company,
                subscription_price_slug=data.get("subscription_price_slug"),
                plan_title=data.get("plan_title"),
                billing_frequency=data.get("billing_frequency"),
                employee_count=employee_count,
                user_count=user_count,
                include_overage=True,
                coupon_code=data.get("coupon_code"),
                offer_code=data.get("offer_code"),
                referral_code=data.get("referral_code"),
                start_trial=bool(data.get("start_trial")),
                addon_uids=data.get("addon_uids"),
                addon_codes=data.get("addon_codes"),
                addon_quantities=data.get("addon_quantities"),
            )
        except ValueError as exc:
            message = str(exc)
            status_code = (
                status.HTTP_404_NOT_FOUND
                if "not found" in message.lower()
                else status.HTTP_400_BAD_REQUEST
            )
            return response.Response({"error": message}, status=status_code)
        except Exception:
            logger.exception("Failed to create v2 Stripe checkout for company=%s", company.uid)
            return response.Response(
                {"error": "Unable to create checkout session."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return response.Response(payload)
