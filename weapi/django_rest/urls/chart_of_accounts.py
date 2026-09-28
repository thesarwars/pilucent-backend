from django.urls import path

from ..views.chart_of_accounts import (
    PrivateWeChartOfAccountList,
    PrivateWeChartOfAccountDetails,
    ChartOfAccountTreeView,
    PrivateWeChartOfAccountSessionList,
    PrivateWeChartOfAccountDeactivate,
)

urlpatterns = [
    path(
        r"/trees",
        ChartOfAccountTreeView.as_view(),
        name="chart-of-accounts-tree",
    ),
    path(
        r"/<uuid:uid>/sessions",
        PrivateWeChartOfAccountSessionList.as_view(),
        name="weapi.chart-of-accounts-session-list",
    ),
    path(
        r"/<uuid:uid>/deactivate",
        PrivateWeChartOfAccountDeactivate.as_view(),
        name="weapi.chart-of-account-deactivate",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeChartOfAccountDetails.as_view(),
        name="weapi.chart-of-account-details",
    ),
    path(
        r"",
        PrivateWeChartOfAccountList.as_view(),
        name="weapi.chart-of-account-list",
    ),
]
