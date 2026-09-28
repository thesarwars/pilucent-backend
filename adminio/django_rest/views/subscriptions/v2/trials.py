from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from companyio.models import Company
from subscriptionio.services.admin_trial_service import AdminTrialService


class AdminSubscriptionTrialSettings(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return response.Response(AdminTrialService.get_settings())

    def patch(self, request):
        return response.Response(AdminTrialService.update_settings(request.data))


class AdminSubscriptionTrialList(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminTrialService.get_active_trials_queryset(
            search=self.request.query_params.get("search"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminTrialService.serialize_trial_rows,
        )


class AdminSubscriptionTrialAction(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, company_uid):
        company = get_object_or_404(Company, uid=company_uid)
        action = request.data.get("action")
        actor = request.user.get_employee()
        try:
            if action == "extend":
                result = AdminTrialService.extend_trial(
                    company,
                    days=int(request.data.get("days", 7)),
                    actor=actor,
                )
            elif action == "convert":
                result = AdminTrialService.convert_trial(company, actor=actor)
            else:
                return response.Response(
                    {"error": "action must be extend or convert"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)
