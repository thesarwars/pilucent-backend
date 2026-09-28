from rest_framework import response, status, views
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from subscriptionio.services.public_plan_catalog_service import PublicPlanCatalogService


class PublicSubscriptionPlanList(views.APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):
        plans = PublicPlanCatalogService.list_plans(
            currency=request.query_params.get("currency"),
            kind=request.query_params.get("kind"),
        )
        return response.Response({"plans": plans})


class PublicSubscriptionPlanDetail(views.APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, slug):
        plan = PublicPlanCatalogService.get_plan(
            slug=slug,
            currency=request.query_params.get("currency"),
        )
        if not plan:
            return response.Response(
                {"error": "Plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return response.Response(plan)


class PublicSubscriptionPlanPreview(views.APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def post(self, request):
        data = request.data
        preview = PublicPlanCatalogService.quote_preview(
            subscription_price_slug=data.get("subscription_price_slug"),
            plan_slug=data.get("plan_slug"),
            billing_frequency=data.get("billing_frequency"),
            currency=data.get("currency"),
            employee_count=int(data.get("employee_count", 0)),
            user_count=int(data.get("user_count", 0)),
        )
        if not preview:
            return response.Response(
                {"error": "Subscription price not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(preview)
