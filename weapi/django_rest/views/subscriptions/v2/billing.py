from decimal import Decimal, InvalidOperation

from rest_framework import response, status, views
from rest_framework.generics import ListAPIView, RetrieveAPIView, get_object_or_404

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.models import SubscriptionInvoice
from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.limit_enforcement_service import LimitEnforcementService
from subscriptionio.services.offer_service import OfferService
from subscriptionio.services.subscription_billing_service import SubscriptionBillingService
from subscriptionio.services.usage_service import UsageService

from weapi.django_rest.serializers.subscriptions.v2.billing import (
    SubscriptionInvoiceDetailSerializer,
    SubscriptionInvoiceListSerializer,
)


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionUsage(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        UsageService.snapshot_company_usage(company)
        return response.Response(
            {
                "usage": UsageService.get_company_usage(company),
                "limits": LimitEnforcementService.get_company_limit_status(company),
            }
        )


class PrivateWeSubscriptionCurrent(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        payload = SubscriptionBillingService.get_current_subscription_payload(company)
        return response.Response(payload)


class PrivateWeSubscriptionPreview(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data

        employee_count = data.get("employee_count")
        user_count = data.get("user_count")
        tax_rate = data.get("tax_rate")

        if employee_count is not None:
            employee_count = int(employee_count)
        if user_count is not None:
            user_count = int(user_count)
        if tax_rate is not None:
            try:
                tax_rate = Decimal(str(tax_rate))
            except (InvalidOperation, TypeError):
                return response.Response(
                    {"error": "tax_rate must be a valid number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            subscription_price = BillingPreviewService._resolve_subscription_price(
                subscription_price_slug=data.get("subscription_price_slug"),
                plan_title=data.get("plan_title"),
                billing_frequency=data.get("billing_frequency"),
            )
            coupon_code, _ = OfferService.resolve_coupon_code(
                offer_code=data.get("offer_code"),
                coupon_code=data.get("coupon_code"),
                company=company,
                subscription_price=subscription_price,
            )
            preview = BillingPreviewService.preview(
                company,
                subscription_price=subscription_price,
                subscription_price_slug=data.get("subscription_price_slug"),
                plan_title=data.get("plan_title"),
                billing_frequency=data.get("billing_frequency"),
                employee_count=employee_count,
                user_count=user_count,
                tax_rate=tax_rate,
                coupon_code=coupon_code,
                currency=data.get("currency"),
                addon_uids=data.get("addon_uids"),
                addon_codes=data.get("addon_codes"),
                addon_quantities=data.get("addon_quantities"),
                apply_credits=data.get("apply_credits", True),
            )
        except ValueError as exc:
            return response.Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not preview:
            return response.Response(
                {"error": "Subscription price not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return response.Response(
            SubscriptionBillingService._serialize_preview(preview)
        )


class PrivateWeSubscriptionInvoiceList(ListAPIView):
    permission_classes = [IsGroupPermission]
    serializer_class = SubscriptionInvoiceListSerializer

    def get_queryset(self):
        company = self.request.user.get_active_company()
        return SubscriptionInvoice.objects.filter(company=company).prefetch_related(
            "lines"
        )


class PrivateWeSubscriptionInvoiceDetail(RetrieveAPIView):
    permission_classes = [IsGroupPermission]
    serializer_class = SubscriptionInvoiceDetailSerializer
    lookup_field = "uid"

    def get_queryset(self):
        company = self.request.user.get_active_company()
        return SubscriptionInvoice.objects.filter(company=company).prefetch_related(
            "lines"
        )

    def get_object(self):
        return get_object_or_404(self.get_queryset(), uid=self.kwargs.get("uid"))
