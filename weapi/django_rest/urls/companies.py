from django.urls import path

from ..views.companies import PrivateWeCompanyList

urlpatterns = [
    path(r"", PrivateWeCompanyList.as_view(), name="weapi.private-company-list"),
]
