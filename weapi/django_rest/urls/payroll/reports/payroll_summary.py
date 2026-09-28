from django.urls import path


from weapi.django_rest.views.payroll.reports.payroll_summary import (
    PayrollSummaryReportView,
) 

from weapi.django_rest.views.payroll.reports.deduction_and_contribution import (
    DeductionContributionReportView,
)

from weapi.django_rest.views.payroll.reports.multiple_worksite import (
    MultipleWorksiteReportView,
)

from weapi.django_rest.views.payroll.reports.payroll_summary_by_employee import (
    PayrollSummaryByEmployeeReportView,
)

from weapi.django_rest.views.payroll.reports.payroll_details import (
    PayrollDetailsReportView,
)

from weapi.django_rest.views.payroll.reports.payroll_tax_liability import (
    PayrollTaxLiabilityReportView,
)

from weapi.django_rest.views.payroll.reports.payroll_tax_wage_summary import (
    PayrollTaxAndWageSummaryReportView,
)

from weapi.django_rest.views.payroll.reports.payroll_total_cost import (
    PayrollTotalCostReportView,
)


from weapi.django_rest.views.payroll.reports.payroll_total_pay import (
    PayrollTotalPayReportView,
)

from weapi.django_rest.views.payroll.reports.time_off import (
    TimeOffReportView,
)


urlpatterns = [
    path("/summary/", PayrollSummaryReportView.as_view(), name="weapi.payroll.reports.payroll-summary"), # /api/v1/payroll/reports/payroll/summary/
    path("/summary-by-employee/", PayrollSummaryByEmployeeReportView.as_view(), name="weapi.payroll.reports.payroll-summary-by-employee"),
    path("/details/", PayrollDetailsReportView.as_view(), name="weapi.payroll.reports.payroll-details"),
    path("/tax-liability/", PayrollTaxLiabilityReportView.as_view(), name="weapi.payroll.reports.payroll-tax-liability"),
    path("/tax-and-wage-summary/", PayrollTaxAndWageSummaryReportView.as_view(), name="weapi.payroll.reports.payroll-tax-and-wage-summary"),
    path("/total-cost/", PayrollTotalCostReportView.as_view(), name="weapi.payroll.reports.payroll-total-cost"),
    path("/total-pay/", PayrollTotalPayReportView.as_view(), name="weapi.payroll.reports.payroll-total-pay"),
    path("/time-off/", TimeOffReportView.as_view(), name="weapi.payroll.reports.time-off"),
    path("/deduction-and-contribution/", DeductionContributionReportView.as_view(), name="weapi.payroll.reports.deduction-and-contribution"),
    path("/multiple-worksite/", MultipleWorksiteReportView.as_view(), name="weapi.payroll.reports.multiple-worksite"),

]	