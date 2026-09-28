from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from companyio.models import Company
from subscriptionio.services.admin_tenant_service import AdminTenantService


class AdminSubscriptionTenantList(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminTenantService.get_tenants_queryset(
            search=self.request.query_params.get("search"),
            status=self.request.query_params.get("status"),
            plan_uid=self.request.query_params.get("plan_uid"),
        )

    def list(self, request, *args, **kwargs):
        return self.paginated_list_response(
            self.get_queryset(),
            AdminTenantService.serialize_tenant_rows,
        )


class AdminSubscriptionTenantDetail(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, company_uid):
        company = get_object_or_404(Company, uid=company_uid)
        return response.Response(AdminTenantService.get_tenant_detail(company))


class AdminSubscriptionTenantEvents(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, company_uid):
        company = get_object_or_404(Company, uid=company_uid)
        limit = int(request.query_params.get("limit", 50))
        return response.Response(
            AdminTenantService.get_tenant_events(company, limit=limit)
        )


class AdminSubscriptionTenantAction(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, company_uid):
        company = get_object_or_404(Company, uid=company_uid)
        action = request.data.get("action")
        if not action:
            return response.Response(
                {"error": "action is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = AdminTenantService.apply_action(
                company,
                action=action,
                actor=request.user.get_employee(),
                payload=request.data,
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)
