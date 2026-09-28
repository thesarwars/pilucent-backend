from django.urls import path, include

from ...views.reports.profit_loss_reports import PrivateWeProfitLossList

urlpatterns = [
    path(
        r"",
        PrivateWeProfitLossList.as_view(),
        name="weapi.profit-loss-list",
    ),
]
