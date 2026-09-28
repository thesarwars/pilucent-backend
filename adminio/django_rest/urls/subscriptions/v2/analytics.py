from django.urls import path

from adminio.django_rest.views.subscriptions.v2.analytics import (
    AdminSubscriptionAnalyticsMrrBreakdown,
    AdminSubscriptionAnalyticsOverview,
    AdminSubscriptionAnalyticsPlanDistribution,
    AdminSubscriptionAnalyticsRevenueTrend,
    AdminSubscriptionAnalyticsTrialFunnel,
)

urlpatterns = [
    path(
        r"/analytics/overview",
        AdminSubscriptionAnalyticsOverview.as_view(),
        name="adminio.subscription-analytics-overview",
    ),
    path(
        r"/analytics/mrr-breakdown",
        AdminSubscriptionAnalyticsMrrBreakdown.as_view(),
        name="adminio.subscription-analytics-mrr",
    ),
    path(
        r"/analytics/revenue-trend",
        AdminSubscriptionAnalyticsRevenueTrend.as_view(),
        name="adminio.subscription-analytics-revenue-trend",
    ),
    path(
        r"/analytics/plan-distribution",
        AdminSubscriptionAnalyticsPlanDistribution.as_view(),
        name="adminio.subscription-analytics-plan-distribution",
    ),
    path(
        r"/analytics/trial-funnel",
        AdminSubscriptionAnalyticsTrialFunnel.as_view(),
        name="adminio.subscription-analytics-trial-funnel",
    ),
]
