"""Payroll tax and wage summary -- what wages each tax was charged on."""

from datetime import date

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    resolve_state_from_general_tax_setting,
)
from payrollio.django_rest.helpers.payroll_tax_wage_summary import (
    build_tax_and_wage_summary,
    collect_wage_facts,
    resolve_prior_wages,
    resolve_state_configs,
    state_of,
)
from rest_framework.response import Response

from weapi.django_rest.views.payroll.reports.base import PayrollReportView


class PayrollTaxAndWageSummaryReportView(PayrollReportView):
    report_title = "Payroll tax and wage summary report"
    pdf_template = "reports/payrolls/payroll_tax_wage_summary_temp.html"
    pdf_filename = "payroll_tax_wage_summary_report.pdf"
    subtitle_names_employees = False
    component_fields = ("payroll", "payroll_type", "payroll_category", "current")

    def build_report(self, request, payrolls, context):
        company = context["company"]
        date_from = context["date_from"]
        date_to = context["date_to"]

        # Wage bases are annual, and the IRS rule is that the pay date governs,
        # so the range's end year selects the table.
        year = (date_to or date_from or date.today()).year
        state_code = resolve_state_from_general_tax_setting(company)

        # Wages earned earlier this year already ate into each employee's base.
        # Without this a December-only range looks like a fresh start and would
        # report taxable wages on a base that was exhausted in March.
        year_start = date(year, 1, 1)
        prior_wages = resolve_prior_wages(
            company, year, date_from if date_from and date_from > year_start else None
        )

        # Load a config for every state whose taxes actually appear, not just
        # the company's own -- otherwise a multi-state payroll charges one
        # state's unemployment against another's wage base.
        payrolls = list(payrolls)
        _, tax_totals, _ = collect_wage_facts(payrolls)
        states = {state_of(payroll_type) for payroll_type in tax_totals}
        states.add(state_code)

        return {
            "state_code": state_code or "",
            "wage_base_year": year,
            **build_tax_and_wage_summary(
                payrolls,
                state_code=state_code,
                year=year,
                prior_wages=prior_wages,
                state_configs=resolve_state_configs(states, year),
            ),
        }

    def overview(self, request, report):
        if request.query_params.get("keywords") != "overview":
            return None
        return Response(
            {"group_count": sum(1 for row in report["rows"] if row["is_group"])}
        )
