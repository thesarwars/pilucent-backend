from django.urls import path

from weapi.django_rest.views.agencies import (
    PrivateWeAgencyList,
    PrivateWeAgencyDetails,
    PrivateWeAgencyTaxList,
    PrivateWeAgencyTaxDetails,
    CombineAgencyTaxViews,
	AgencyTaxSetViews,
    PrivateWeAgencyTaxTracker
)


urlpatterns = [
    path(
        r"",
        PrivateWeAgencyList.as_view(),
        name="weapi.agency-list",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeAgencyDetails.as_view(),
        name="weapi.agency-details",
    ),
    path(
        r"/<uuid:uid>/tax-tracker",
        PrivateWeAgencyTaxTracker.as_view(),
        name="weapi.agency-tax-tracker",
    ),
    path(
        r"/taxes",
        PrivateWeAgencyTaxList.as_view(),
        name="weapi.agency-tax-list",
    ),
    path(
        r"/tax/<uuid:uid>",
        PrivateWeAgencyTaxDetails.as_view(),
        name="weapi.agency-tax-details",
    ),
	path(
        r"/tax/set",
        AgencyTaxSetViews.as_view(),
        name="weapi.agency-tax-set",
    ),
    path("/taxes/combines", CombineAgencyTaxViews.as_view(), name="POST.combine-taxes"),
]
