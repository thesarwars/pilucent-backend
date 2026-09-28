from rest_framework import response, views

from adminio.mixins import IsSuperAdmin

from subscriptionio.services.analytics_service import SubscriptionAnalyticsService


class AdminSubscriptionAnalyticsOverview(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        return response.Response(SubscriptionAnalyticsService.get_overview())


class AdminSubscriptionAnalyticsMrrBreakdown(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        return response.Response(
            {"plans": SubscriptionAnalyticsService.get_mrr_breakdown()}
        )


class AdminSubscriptionAnalyticsRevenueTrend(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        months = int(request.query_params.get("months", 12))
        return response.Response(
            SubscriptionAnalyticsService.get_revenue_trend(months=months)
        )


class AdminSubscriptionAnalyticsPlanDistribution(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        return response.Response(SubscriptionAnalyticsService.get_plan_distribution())


class AdminSubscriptionAnalyticsTrialFunnel(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        days = int(request.query_params.get("days", 90))
        return response.Response(
            SubscriptionAnalyticsService.get_trial_funnel(days=days)
        )
