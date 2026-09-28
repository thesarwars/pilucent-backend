from django.urls import path, include
from ...views.payroll.deduction_and_contribution import DeductionAndContributionView, DedConUpdateView, DeductionAndContributionListView

urlpatterns = [
    path("", DeductionAndContributionView.as_view(), name="POST.deduction-and-contribution"), #/api/v1/we/payroll/ded-con
    path("/<str:uid>/", DedConUpdateView.as_view(), name="GET.deduction-and-contribution-individual"), #/api/v1/we/payroll/ded-con/uid
    path("/list", DeductionAndContributionListView.as_view(), name="GET.deduction-and-contribution-list"), #/api/v1/we/payroll/ded-con/list
]