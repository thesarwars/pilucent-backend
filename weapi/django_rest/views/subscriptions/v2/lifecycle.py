from rest_framework import response, status, views

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.lifecycle_service import LifecycleService
from subscriptionio.services.offer_service import OfferService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionLifecycleState(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        return response.Response(LifecycleService.get_lifecycle_state(company))


class PrivateWeSubscriptionCancel(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        result = LifecycleService.cancel_subscription(
            company,
            at_period_end=bool(data.get("at_period_end", True)),
            actor=request.user.get_employee(),
            reason=data.get("reason", ""),
        )
        if not result.success:
            return response.Response(
                {"error": result.message, "status": result.status},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(
            {
                "status": result.status,
                "cancel_at_period_end": result.cancel_at_period_end,
                "current_period_end": result.current_period_end,
                "message": result.message,
                "retention_offers": result.retention_offers or [],
            }
        )


class PrivateWeSubscriptionRetentionOffers(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        return response.Response(
            {"offers": OfferService.get_retention_offers(company)}
        )


class PrivateWeSubscriptionAcceptRetentionOffer(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        offer_code = request.data.get("offer_code")
        if not offer_code:
            return response.Response(
                {"error": "offer_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            offer = OfferService.accept_retention_offer(
                company,
                offer_code,
                actor=request.user.get_employee(),
            )
        except ValueError as exc:
            return response.Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(
            {
                "message": "Retention offer applied. Your subscription will continue.",
                "offer": offer,
            }
        )


class PrivateWeSubscriptionReactivate(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        result = LifecycleService.reactivate_subscription(
            company,
            actor=request.user.get_employee(),
        )
        if not result.success:
            return response.Response(
                {"error": result.message, "status": result.status},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(
            {"status": result.status, "message": result.message}
        )


class PrivateWeSubscriptionEventTimeline(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        limit = int(request.query_params.get("limit", 50))
        return response.Response(
            {"events": SubscriptionEventService.get_company_timeline(company, limit=limit)}
        )
