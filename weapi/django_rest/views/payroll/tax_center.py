from django.db.models import Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, views
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.django_rest.helpers.form_941_builder import (
    build_form_941_download_payload,
    build_form_941_summary,
)
from payrollio.django_rest.helpers.form_940_builder import (
    build_form_940_download_payload,
    build_form_940_summary,
)
from payrollio.django_rest.helpers.tax_center_rollup import (
    apply_tax_period_payments,
    build_federal_tax_periods,
    build_futa_tax_periods,
    build_state_tax_periods,
    parse_report_year,
)
from payrollio.models import (
    PayrollFederalTaxInfoSetting,
    PayrollSalaryComponent,
    PayrollSalaryProcess,
    TaxCenterPayMethod,
)
from weapi.django_rest.serializers.payroll.tax_center import (
    PayrollTaxCenterFilingMarkSerializer,
    PayrollTexCenterPayMethodSerializer,
    TaxCenterReportSerializer,
)
from weapi.django_rest.views.pdf.f941 import create_form_941_pdf_url_response
from weapi.django_rest.views.pdf.f940 import create_form_940_pdf_url_response

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class TaxCenterReportView(generics.ListAPIView):
    serializer_class = TaxCenterReportSerializer

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            PayrollSalaryProcess.objects.select_related(
                "employee__user",
                "employee__work_locations",
            )
            .prefetch_related(
                Prefetch(
                    "payroll_components",
                    queryset=PayrollSalaryComponent.objects.filter(
                        Q(payroll_category="EMPLOYEE_TAXES")
                        | Q(payroll_category="EMPLOYER_TAXES")
                    ),
                )
            )
            .filter(
                employee__user__companyuser__company=user_company,
                status=PayrollSalaryProcessStatusChoices.FINALIZED,
            )
            .order_by("pay_date")
        )

    def get_federal_tax_settings(self, user_company):
        return (
            PayrollFederalTaxInfoSetting.objects.filter(company=user_company)
            .prefetch_related("items")
            .first()
        )

    def list(self, request, *args, **kwargs):
        user_company = request.user.get_active_company()
        year = parse_report_year(request)
        queryset = self.get_queryset().filter(pay_date__year=year)
        federal_tax_setting = self.get_federal_tax_settings(user_company)

        federal_tax_periods = build_federal_tax_periods(
            queryset,
            federal_tax_setting,
        )
        futa_tax_periods = build_futa_tax_periods(queryset)
        state_tax_periods = build_state_tax_periods(queryset)

        all_tax_periods = federal_tax_periods + futa_tax_periods + state_tax_periods
        all_tax_periods = apply_tax_period_payments(
            all_tax_periods, user_company, year=year
        )
        all_tax_periods.sort(key=lambda row: (row["due_date"], row["tax_category"]))

        return Response(
            {
                "tax_periods": all_tax_periods,
                "total_periods": len(all_tax_periods),
                "federal_periods": len(federal_tax_periods),
                "futa_periods": len(futa_tax_periods),
                "state_periods": len(state_tax_periods),
                "year": year,
            },
            status=status.HTTP_200_OK,
        )


class PayrollTaxPayProcessView(generics.ListCreateAPIView):
    serializer_class = PayrollTexCenterPayMethodSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ["liability_period", "check_number", "notes"]
    ordering_fields = ["created_at", "payment_date", "tax_amount"]
    filterset_fields = ["is_filed", "is_paid"]

    def get_queryset(self):
        company = self.request.user.get_active_company()
        return (
            TaxCenterPayMethod.objects.filter(
                Q(tax_liability_account__company=company)
                | Q(tax_record_account__company=company)
            )
            .select_related(
                "tax_liability_account",
                "tax_record_account",
            )
            .distinct()
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": self.request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "message": "Paid"}, status=status.HTTP_201_CREATED
        )


class PayrollTaxFilingPreView(views.APIView):
    """Filing preview for federal tax forms.

    Query params:
        year: defaults to current year
        form_type: optional filter (``941`` or ``940``). When omitted, all
            available filings for the year are returned (each with due date).
        pay_quarter: optional. When provided with ``form_type=941`` (or with no
            form_type, narrows 941 results), includes the full 941 field map.
    """

    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    required_permissions = ["view_payrollfederaltaxinfosetting"]

    QUARTER_DUE_DATES = {
        "Q1": (4, 30),
        "Q2": (7, 31),
        "Q3": (10, 31),
        "Q4": (1, 31),  # following year
    }

    SUPPORTED_FORMS = ("941", "940")

    def get(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        if not company:
            return Response(
                {"error": "Active company is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        form_type = (request.query_params.get("form_type") or "").strip()
        if form_type and form_type not in self.SUPPORTED_FORMS:
            return Response(
                {
                    "error": f"form_type must be one of {', '.join(self.SUPPORTED_FORMS)}.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        year = parse_report_year(request)
        pay_quarter = request.query_params.get("pay_quarter")

        filings = []
        if not form_type or form_type == "941":
            filings.extend(self._build_941_filings(company, year, pay_quarter))
        if not form_type or form_type == "940":
            include_940_fields = form_type == "940"
            filings.extend(
                self._build_940_filings(company, year, include_fields=include_940_fields)
            )

        filings.sort(key=lambda row: row["due_date"])

        return Response(
            {
                "year": year,
                "filings": filings,
                "total_filings": len(filings),
            },
            status=status.HTTP_200_OK,
        )

    def _quarter_due_date(self, quarter, year):
        from datetime import date

        month, day = self.QUARTER_DUE_DATES[quarter]
        due_year = year + 1 if quarter == "Q4" else year
        return date(due_year, month, day).isoformat()

    def _build_941_filings(self, company, year, pay_quarter=None):
        quarters = [pay_quarter] if pay_quarter in self.QUARTER_DUE_DATES else list(
            self.QUARTER_DUE_DATES
        )
        rows = []
        for quarter in quarters:
            summary = build_form_941_summary(company, quarter, year)
            wages = float(summary.get("wages_total") or 0)
            federal_tax_total = float(summary.get("federal_tax_total") or 0)
            if wages <= 0 and federal_tax_total <= 0:
                continue
            row = {
                "form_type": "941",
                "form_title": "Employer's Quarterly Federal Tax Return",
                "period_label": f"{quarter} {year}",
                "quarter": quarter,
                "year": year,
                "due_date": self._quarter_due_date(quarter, year),
                "total_tax": federal_tax_total,
                "summary": summary,
            }
            if pay_quarter == quarter:
                row["form_941_fields"] = build_form_941_download_payload(
                    company, quarter, year
                )
            rows.append(row)
        return rows

    def _build_940_filings(self, company, year, include_fields=False):
        summary = build_form_940_summary(company, year)
        if summary["line_12_total_futa_tax"] <= 0 and summary["line_3_total_payments"] <= 0:
            return []

        from datetime import date

        annual_due_date = date(year + 1, 1, 31).isoformat()
        row = {
            "form_type": "940",
            "form_title": "Employer's Annual Federal Unemployment (FUTA) Tax Return",
            "period_label": f"Annual {year}",
            "year": year,
            "due_date": annual_due_date,
            "total_tax": summary["line_12_total_futa_tax"],
            "summary": summary,
            "futa_quarters": [
                {
                    "quarter": quarter,
                    "amount": amount,
                }
                for quarter, amount in summary["quarterly_futa_liability"].items()
                if amount > 0
            ],
        }
        if include_fields:
            row["form_940_fields"] = build_form_940_download_payload(company, year)
        return [row]


class PayrollTaxFilingDownloadView(views.APIView):
    """Deprecated alias — prefer ``GET /we/pdf/941/?quarter=Q3&year=2026``."""

    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    required_permissions = ["view_payrollfederaltaxinfosetting"]

    def get(self, request, *args, **kwargs):
        return create_form_941_pdf_url_response(request, {})

    def post(self, request, *args, **kwargs):
        return Response(
            {
                "error": "Use GET /we/pdf/941/?quarter=Q3&year=2026 instead.",
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class PayrollTaxFiling940DownloadView(views.APIView):
    """Generate Form 940 PDF from payroll — ``GET /we/pdf/940/?year=2026``."""

    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    required_permissions = ["view_payrollfederaltaxinfosetting"]

    def get(self, request, *args, **kwargs):
        return create_form_940_pdf_url_response(request, {})


class PayrollTaxFilingMarkFiledView(generics.CreateAPIView):
    serializer_class = PayrollTaxCenterFilingMarkSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            {
                "success": True,
                "uid": str(instance.uid),
                "is_filed": instance.is_filed,
            },
            status=status.HTTP_201_CREATED,
        )
