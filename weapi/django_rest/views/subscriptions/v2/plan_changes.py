from rest_framework import response, status, views

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from subscriptionio.services.plan_change_service import PlanChangeService


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeSubscriptionPlanChangePreview(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["view_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        try:
            result = PlanChangeService.preview_plan_change(
                company,
                subscription_price_slug=data.get("subscription_price_slug"),
                plan_title=data.get("plan_title"),
                billing_frequency=data.get("billing_frequency"),
                immediate=bool(data.get("immediate", False)),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)


class PrivateWeSubscriptionScheduledPlanChange(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        return response.Response(
            {"scheduled_plan_change": PlanChangeService.get_scheduled_change(company)}
        )

    def delete(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        try:
            result = PlanChangeService.cancel_scheduled_change(
                company,
                actor=request.user.get_employee(),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)


class PrivateWeSubscriptionScheduleDowngrade(views.APIView):
    permission_classes = [IsGroupPermission]
    required_permissions = ["change_companysubscription"]

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        data = request.data
        try:
            result = PlanChangeService.schedule_downgrade(
                company,
                subscription_price_slug=data.get("subscription_price_slug"),
                plan_title=data.get("plan_title"),
                billing_frequency=data.get("billing_frequency"),
                notes=data.get("notes", ""),
                actor=request.user.get_employee(),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result, status=status.HTTP_201_CREATED)
