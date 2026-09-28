from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.date_range_filters import WeekMonthYearRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription
from addressio.models import AddressConnector

from payrollio.filters import PaycheckReportFilter
from payrollio.models import PayrollSalaryComponent, PayrollSalaryProcess

from weapi.django_rest.helpers.payroll.paycheck_report import (
    aggregate_paycheck_totals,
    apply_paycheck_pay_date_filter,
    build_paycheck_employee_groups,
    group_paycheck_runs_by_employee,
    parse_paycheck_report_dates,
    render_paycheck_detail_pdf,
)
from weapi.django_rest.serializers.payroll.reports.paycheck import (
    PaycheckEmployeeGroupSerializer,
    PaycheckRunDetailSerializer,
)


class PaycheckReportBaseMixin:
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"

    def get_company(self):
        return self.request.user.get_active_company()

    def get_base_queryset(self):
        return (
            PayrollSalaryProcess.objects.select_related(
                "employee__user",
                "employee__work_locations",
                "funding_account",
                "payment_account",
            )
            .prefetch_related(
                "employee__moov_employee_bank_accounts",
                "employee__employeebankinginformation_set",
                Prefetch(
                    "employee__addressconnector_set",
                    queryset=AddressConnector.objects.select_related("address"),
                ),
                Prefetch(
                    "payroll_components",
                    queryset=PayrollSalaryComponent.objects.all(),
                ),
            )
            .filter(employee__user__companyuser__company=self.get_company())
            .order_by("employee__user__name", "-pay_date")
        )


class PaycheckReportListView(PaycheckReportBaseMixin, generics.ListAPIView):
    """
    Paycheck report grouped by employee.

    Each result item contains employee summary totals for the filtered pay-date
    range and a list of individual processed payroll runs (processed_data).
    """

    # On the view rather than on PaycheckReportBaseMixin, deliberately. The
    # mixin's other user, PaycheckReportDetailView, declares a serializer whose
    # Meta names a model, so the resolver already handles it -- and an explicit
    # codename on the mixin would override that for both. This view is the one
    # that resolved to nothing.
    required_permissions = ["view_reports"]

    filterset_class = PaycheckReportFilter
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        WeekMonthYearRangeFilter,
    ]
    search_fields = [
        "employee__user__name",
        "employee__first_name",
        "employee__last_name",
        "pay_period",
    ]

    def get_queryset(self):
        return self.get_base_queryset()

    def list(self, request, *args, **kwargs):
        base_queryset = self.get_queryset()
        start_date, end_date = parse_paycheck_report_dates(request, base_queryset)
        queryset = self.filter_queryset(base_queryset)
        queryset = apply_paycheck_pay_date_filter(queryset, start_date, end_date)

        grouped = group_paycheck_runs_by_employee(queryset)
        results = build_paycheck_employee_groups(grouped, start_date, end_date)
        serializer = PaycheckEmployeeGroupSerializer(results, many=True)
        totals = aggregate_paycheck_totals(queryset)

        return Response(
            {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "count": len(results),
                "total_runs": queryset.count(),
                **totals,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class PaycheckReportDetailView(PaycheckReportBaseMixin, generics.RetrieveAPIView):
    """
    Single paycheck run for an employee, including read-only payroll_components.

    Query params: employee_uid, salary_process_uid (required).
    Optional: is_pdf=true — renders paycheck_details.html and returns file_uid + url.
    """

    serializer_class = PaycheckRunDetailSerializer

    def get_queryset(self):
        return self.get_base_queryset()

    def retrieve(self, request, *args, **kwargs):
        payroll_run = self.get_object()
        if request.query_params.get("is_pdf") == "true":
            pdf_payload = render_paycheck_detail_pdf(
                self, payroll_run, self.get_company()
            )
            return Response(pdf_payload, status=status.HTTP_200_OK)

        serializer = self.get_serializer(payroll_run)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def get_object(self):
        employee_uid = self.request.query_params.get("employee_uid")
        salary_process_uid = self.request.query_params.get("salary_process_uid")

        if not employee_uid or not salary_process_uid:
            raise ValidationError(
                {
                    "detail": (
                        "Query parameters 'employee_uid' and "
                        "'salary_process_uid' are required."
                    )
                }
            )

        payroll_run = (
            self.get_queryset()
            .filter(
                uid=salary_process_uid,
                employee__uid=employee_uid,
            )
            .first()
        )

        if payroll_run is None:
            raise NotFound("Paycheck run not found for this employee.")

        return payroll_run
