from django.urls import path
from weapi.django_rest.views.reports.general_ledgers import PrivateWeGeneralLadgerList

urlpatterns = [
    path(r"", PrivateWeGeneralLadgerList.as_view(), name="weapi.general-ladger-list"),
]
