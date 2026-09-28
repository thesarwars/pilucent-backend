import tempfile
import weasyprint
import os
from decimal import Decimal
from collections import defaultdict
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_date
from django.db.models import Prefetch, Max, Count
from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status, generics, filters
from rest_framework.response import Response
from datetime import datetime, date
from payrollio.models import (
    PayrollSalaryProcess,
    PayrollSalaryComponent,
    PayrollWorkLocation,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.date_range_filters import WeekMonthYearRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription
from weapi.django_rest.serializers.payroll.reports.multiple_worksite import (
    MultipleWorksiteReportSerializer,
    MultipleWorksiteFilter,
)
from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


class MultipleWorksiteReportView(generics.ListAPIView):
    serializer_class = MultipleWorksiteReportSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    # `view_reports` for the same reason the rest of the report views use it,
    # and because the Employee Self-Service group holds
    # `view_payrollsalaryprocess` -- and this report is filtered by COMPANY, not
    # to the requesting employee, so that codename would expose every
    # colleague's pay.
    required_permissions = ["view_reports"]
    filterset_class = MultipleWorksiteFilter
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        WeekMonthYearRangeFilter,
    ]

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return (
            PayrollSalaryProcess.objects.select_related(
                "employee__user", "funding_account", "payment_account"
            )
            .prefetch_related(
                Prefetch(
                    "payroll_components",
                    queryset=PayrollSalaryComponent.objects.filter(
                        payroll_category="PAY"
                    ),
                )
            )
            .filter(employee__user__companyuser__company=user_company)
            .order_by("pay_date")
        )

    def get_company_worksites(self, user_company):
        """Get all work locations for the company"""
        # Get all work locations for the company that are not removed
        worksites = (
            PayrollWorkLocation.objects.filter(company=user_company)
            .exclude(status="REMOVED")
            .values(
                "title",
                "location_address",
                "location_city",
                "location_state",
                "location_zip",
            )
        )

        worksite_dict = {}
        for worksite in worksites:
            location_name = worksite["title"] or "Unknown Location"
            address = worksite["location_address"] or ""
            city_state_zip = f"{worksite['location_city'] or ''}, {worksite['location_state'] or ''} {worksite['location_zip'] or ''}".strip()
            if city_state_zip.startswith(","):
                city_state_zip = city_state_zip[1:].strip()

            worksite_dict[location_name] = {
                "address": address,
                "city_state_zip": city_state_zip,
            }

        return worksite_dict

    def get_quarter_months(self, quarter, year):
        """Get the 3 months for a given quarter"""
        quarters = {
            "Q1": [1, 2, 3],  # Jan, Feb, Mar
            "Q2": [4, 5, 6],  # Apr, May, Jun
            "Q3": [7, 8, 9],  # Jul, Aug, Sep
            "Q4": [10, 11, 12],  # Oct, Nov, Dec
        }
        return quarters.get(quarter, [])

    def get_quarter_from_date_range(self, start_date, end_date):
        """Determine quarter from date range"""
        if start_date and end_date:
            start_month = start_date.month
            end_month = end_date.month

            # If range spans multiple quarters, use the start month to determine quarter
            if start_month in [1, 2, 3]:
                return "Q1"
            elif start_month in [4, 5, 6]:
                return "Q2"
            elif start_month in [7, 8, 9]:
                return "Q3"
            elif start_month in [10, 11, 12]:
                return "Q4"
        return "Q3"  # Default to current quarter

    def get_month_names(self, quarter_months, year):
        """Get month names for the given quarter months"""
        month_names = {
            1: "Jan",
            2: "Feb",
            3: "Mar",
            4: "Apr",
            5: "May",
            6: "Jun",
            7: "Jul",
            8: "Aug",
            9: "Sep",
            10: "Oct",
            11: "Nov",
            12: "Dec",
        }
        return [month_names[month] for month in quarter_months]

    def list(self, request, *args, **kwargs):
        # Get date parameters
        start_date_str = request.query_params.get("date_from")
        end_date_str = request.query_params.get("date_to")
        year_param = request.query_params.get("year")
        quarter_param = request.query_params.get("quarter")

        # Fallback to old parameter names if new ones not provided
        if not start_date_str:
            start_date_str = request.query_params.get("pay_date_after")
        if not end_date_str:
            end_date_str = request.query_params.get("pay_date_before")

        is_pdf = request.query_params.get("is_pdf")

        start_date = None
        end_date = None
        user_company = self.request.user.get_active_company()
        current_year = datetime.now().year
        year = int(year_param) if year_param else current_year

        # Determine quarter
        if quarter_param:
            quarter = quarter_param
        else:
            # Parse dates to determine quarter
            if start_date_str:
                try:
                    start_date = parse_date(str(start_date_str))
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid start date format. Use YYYY-MM-DD format."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            if end_date_str:
                try:
                    end_date = parse_date(str(end_date_str))
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid end date format. Use YYYY-MM-DD format."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Determine quarter from date range or default to current quarter
            quarter = self.get_quarter_from_date_range(start_date, end_date)

        # Get quarter months
        quarter_months = self.get_quarter_months(quarter, year)

        # If no specific dates provided, use the entire quarter
        if not start_date or not end_date:
            start_date = date(year, quarter_months[0], 1)
            # Get last day of the last month in quarter
            if quarter_months[2] == 12:
                end_date = date(year, 12, 31)
            else:
                # Get first day of next month and subtract 1 day
                from calendar import monthrange

                end_date = date(
                    year, quarter_months[2], monthrange(year, quarter_months[2])[1]
                )

        queryset = self.filter_queryset(self.get_queryset())

        # Apply date filter
        queryset = queryset.filter(pay_date__range=(start_date, end_date))

        # Get company worksites info
        company_worksites = self.get_company_worksites(user_company)

        # Initialize data structure for all company worksites
        worksite_data = {}

        # First, add all company worksites (even if no payroll data)
        all_company_worksites = PayrollWorkLocation.objects.filter(
            company=user_company
        ).exclude(status="REMOVED")

        for worksite in all_company_worksites:
            worksite_title = worksite.title
            worksite_address = worksite.location_address or ""
            city_state_zip = f"{worksite.location_city or ''}, {worksite.location_state or ''} {worksite.location_zip or ''}".strip()
            if city_state_zip.startswith(","):
                city_state_zip = city_state_zip[1:].strip()

            worksite_data[worksite_title] = {
                "worksite": f"{user_company.name}",
                "address": worksite_address,
                "city_state_zip": city_state_zip,
                "month1_employees": set(),
                "month2_employees": set(),
                "month3_employees": set(),
                "quarterly_wages": Decimal("0.00"),
            }

        # Process all payroll entries
        for payroll_entry in queryset:
            work_location_obj = payroll_entry.employee.work_locations

            # Get worksite title
            if work_location_obj:
                worksite_title = work_location_obj.title
            else:
                # Handle employees without work location
                worksite_title = "Unknown Location"
                # Add unknown location to worksite_data if not exists
                if worksite_title not in worksite_data:
                    worksite_data[worksite_title] = {
                        "worksite": f"{user_company.name}",
                        "address": "",
                        "city_state_zip": "Unknown Location",
                        "month1_employees": set(),
                        "month2_employees": set(),
                        "month3_employees": set(),
                        "quarterly_wages": Decimal("0.00"),
                    }

            # Skip if worksite not in our data (shouldn't happen but safety check)
            if worksite_title not in worksite_data:
                continue

            # Determine which month this payroll belongs to
            pay_month = payroll_entry.pay_date.month
            employee_uid = payroll_entry.employee.uid

            # Add employee to appropriate month set (using sets to avoid duplicates)
            if pay_month == quarter_months[0]:  # First month of quarter
                worksite_data[worksite_title]["month1_employees"].add(employee_uid)
            elif pay_month == quarter_months[1]:  # Second month of quarter
                worksite_data[worksite_title]["month2_employees"].add(employee_uid)
            elif pay_month == quarter_months[2]:  # Third month of quarter
                worksite_data[worksite_title]["month3_employees"].add(employee_uid)

            # Add gross pay to quarterly wages
            worksite_data[worksite_title]["quarterly_wages"] += Decimal(
                str(payroll_entry.gross_pay or 0)
            )

        # Convert sets to counts and prepare final data
        worksites_list = []
        total_month1 = 0
        total_month2 = 0
        total_month3 = 0
        total_wages = Decimal("0.00")

        for worksite_info in worksite_data.values():
            month1_count = len(worksite_info["month1_employees"])
            month2_count = len(worksite_info["month2_employees"])
            month3_count = len(worksite_info["month3_employees"])

            # Add to totals
            total_month1 += month1_count
            total_month2 += month2_count
            total_month3 += month3_count
            total_wages += worksite_info["quarterly_wages"]

            worksites_list.append(
                {
                    "worksite": worksite_info["worksite"],
                    "address": worksite_info["address"],
                    "city_state_zip": worksite_info["city_state_zip"],
                    "month1_employees": month1_count,
                    "month2_employees": month2_count,
                    "month3_employees": month3_count,
                    "quarterly_wages": worksite_info["quarterly_wages"],
                }
            )

        worksites_list.sort(key=lambda x: x["worksite"])

        # Get month names for the quarter
        month_names = self.get_month_names(quarter_months, year)

        quarter_labels = {
            "Q1": f"Q1 {year} (Jan-Mar)",
            "Q2": f"Q2 {year} (Apr-Jun)",
            "Q3": f"Q3 {year} (Jul-Sep)",
            "Q4": f"Q4 {year} (Oct-Dec)",
        }
        quarter_label = quarter_labels.get(quarter, f"{quarter} {year}")

        final_data = {
            "company_name": user_company.name,
            "quarter_label": quarter_label,
            "year": year,
            "worksites": worksites_list,
            "month_names": month_names,
            "totals": {
                "month1_employees": total_month1,
                "month2_employees": total_month2,
                "month3_employees": total_month3,
                "quarterly_wages": total_wages,
            },
        }

        if is_pdf == "true":
            return self.render_to_pdf(
                final_data,
                start_date,
                end_date,
                user_company,
            )

        return Response(final_data, status=status.HTTP_200_OK)

    def render_to_pdf(self, final_data, start_date, end_date, company):
        """
        Render multiple worksite report to PDF.
        """

        html_string = render_to_string(
            "reports/payrolls/multiple_worksite_temp.html",
            {
                "data": final_data,
                "start_date": start_date,
                "end_date": end_date,
                "company": company,
            },
        )

        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_pdf.close()  # Close so WeasyPrint can write to it
        weasyprint.HTML(string=html_string).write_pdf(temp_pdf.name)

        with open(temp_pdf.name, "rb") as pdf_file:
            pdf_content = pdf_file.read()

        os.unlink(temp_pdf.name)  # Remove temp file after reading

        response_pdf = HttpResponse(pdf_content, content_type="application/pdf")
        response_pdf["Content-Disposition"] = (
            "inline; filename=multiple_worksite_report.pdf"
        )
        return response_pdf
