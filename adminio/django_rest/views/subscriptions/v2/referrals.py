from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import ReferralRedemption
from subscriptionio.services.admin_referral_service import AdminReferralService


class AdminSubscriptionReferralSettings(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return response.Response(AdminReferralService.get_settings())

    def patch(self, request):
        return response.Response(AdminReferralService.update_settings(request.data))


class AdminSubscriptionReferralActivity(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminReferralService.get_activity_queryset(
            status=self.request.query_params.get("status"),
            search=self.request.query_params.get("search"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminReferralService.serialize_redemptions,
            summary=AdminReferralService.get_summary(),
        )


class AdminSubscriptionReferralAction(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid):
        redemption = get_object_or_404(ReferralRedemption, uid=uid)
        action = request.data.get("action")
        if action not in {"approve", "reject"}:
            return response.Response(
                {"error": "action must be approve or reject"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            actor = request.user.get_employee()
            if action == "approve":
                result = AdminReferralService.approve(redemption, actor=actor)
            else:
                result = AdminReferralService.reject(
                    redemption,
                    actor=actor,
                    reason=request.data.get("reason", ""),
                )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)
