import tempfile
import weasyprint
import os

from decimal import Decimal
from collections import defaultdict
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_date
from django.db.models import Prefetch, Max
from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status, generics, filters
from rest_framework.response import Response
from payrollio.models import PayrollSalaryProcess, PayrollSalaryComponent
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter, WeekMonthYearRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription
from weapi.django_rest.serializers.payroll.reports.payroll_summary import PayrollSummarySerializer, PayrollSummaryFilter


class PayrollSummaryReportView(generics.ListAPIView): 
    serializer_class = PayrollSummarySerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = PayrollSummaryFilter
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    

    def get_queryset(self):
        user_company = self.request.user.get_active_company()
        return PayrollSalaryProcess.objects.select_related(
            'employee__user',
            'funding_account',
            'payment_account'
        ).prefetch_related(
            Prefetch(
                'payroll_components',
                queryset=PayrollSalaryComponent.objects.all()
            )
        ).filter(
            employee__user__companyuser__company=user_company
        ).order_by('employee__user__name', 'pay_date')

    def get_last_pay_date(self, user_company):
        """
        Get the most recent pay date
        """
        last_pay_date = PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=user_company
        ).aggregate(Max('pay_date'))['pay_date__max']
        
        if last_pay_date:
            return last_pay_date, last_pay_date
        return None, None

    def list(self, request, *args, **kwargs):
        # Get date parameters
        start_date_str = request.query_params.get("date_from")
        end_date_str = request.query_params.get("date_to") 
        
        # Fallback to old parameter names if new ones not provided
        if not start_date_str:
            start_date_str = request.query_params.get("pay_date_after")
        if not end_date_str:
            end_date_str = request.query_params.get("pay_date_before")
            
        filter_type = request.query_params.get("filter_type")
        is_pdf = request.query_params.get("is_pdf")

        start_date = None
        end_date = None
        user_company = self.request.user.get_active_company()
        
        # Check if last_pay_date filter is requested
        if filter_type == "last_pay_date":
            start_date, end_date = self.get_last_pay_date(user_company)
        elif start_date_str or end_date_str:
            # Parse custom dates with proper error handling
            if start_date_str:
                try:
                    start_date = parse_date(str(start_date_str))
                    if not start_date:
                        return Response(
                            {"error": "Invalid start date format. Use YYYY-MM-DD format."},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid start date format. Use YYYY-MM-DD format."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            if end_date_str:
                try:
                    end_date = parse_date(str(end_date_str))
                    if not end_date:
                        return Response(
                            {"error": "Invalid end date format. Use YYYY-MM-DD format."},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid end date format. Use YYYY-MM-DD format."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        else:
            # Default to last pay date if no parameters provided
            start_date, end_date = self.get_last_pay_date(user_company)

        queryset = self.filter_queryset(self.get_queryset())
        
        # Apply date filter if dates are available
        if start_date and end_date:
            queryset = queryset.filter(
                pay_date__range=(start_date, end_date)
            )
        elif start_date:
            queryset = queryset.filter(pay_date__gte=start_date)
        elif end_date:
            queryset = queryset.filter(pay_date__lte=end_date)

        def create_employee_data():
            return {
                'employee_info': {},
                'totals': {
                    'total_hours': Decimal('0.00'),
                    'total_gross_pay': Decimal('0.00'),
                    'total_other_pay': Decimal('0.00'),
                    'total_employee_taxes_deductions': Decimal('0.00'),
                    'total_net_pay': Decimal('0.00'),
                    'total_employer_taxes_contributions': Decimal('0.00'),
                    'total_payroll_cost': Decimal('0.00'),
                    'total_pay': Decimal('0.00'),
                    'total_employee_taxes': Decimal('0.00'),
                    'total_employee_deductions': Decimal('0.00'),
                    'total_employer_taxes': Decimal('0.00'),
                    'total_company_paid_contributions': Decimal('0.00'),
                }
            }

        grouped_data = defaultdict(create_employee_data)

        for payroll_entry in queryset:
            employee_name = payroll_entry.employee.user.name
            employee_data = grouped_data[employee_name]
            
            if not employee_data['employee_info']:
                employee_data['employee_info'] = {
                    'name': employee_name,
                    'employee_id': payroll_entry.employee.uid,
                }

            entry_hours = Decimal('0.00')
            entry_other_pay = Decimal('0.00')
            entry_category_totals = {
                'PAY': Decimal('0.00'),
                'EMPLOYEE_TAXES': Decimal('0.00'),
                'EMPLOYEE_DEDUCTIONS': Decimal('0.00'),
                'EMPLOYER_TAXES': Decimal('0.00'),
                'COMPANY_PAID_CONTRIBUTIONS': Decimal('0.00'),
            }

            for component in payroll_entry.payroll_components.all():
                component_current = Decimal(str(component.current or 0))
                component_hours = Decimal(str(component.hours or 0))
                
                entry_hours += component_hours
                
                if component.payroll_category in entry_category_totals:
                    entry_category_totals[component.payroll_category] += component_current
                
                if component.payroll_category not in ['EARNINGS'] or 'overtime' in component.payroll_type.lower():
                    entry_other_pay += component_current

            gross_pay = Decimal(str(payroll_entry.gross_pay))
            employer_taxes = Decimal(str(payroll_entry.employer_taxes_contributions))
            employee_taxes_deductions = Decimal(str(payroll_entry.employee_taxes_deductions))
            net_pay = Decimal(str(payroll_entry.net_pay))
            total_payroll_cost = gross_pay + employer_taxes

            totals = employee_data['totals']
            totals['total_hours'] += entry_hours
            totals['total_gross_pay'] += gross_pay
            totals['total_other_pay'] += entry_other_pay
            totals['total_employee_taxes_deductions'] += employee_taxes_deductions
            totals['total_net_pay'] += net_pay
            totals['total_employer_taxes_contributions'] += employer_taxes
            totals['total_payroll_cost'] += total_payroll_cost

            for category, amount in entry_category_totals.items():
                totals[f'total_{category.lower()}'] += amount

        final_data = {
            'employees': dict(grouped_data)
        }

        if request.query_params.get("keywords", None) == "overview":
            return Response({
                'employee_count': len(final_data['employees'])
            })

        if is_pdf == "true":
            return self.render_to_pdf(
                final_data,
                start_date,
                end_date,
                user_company,
            )

        return Response(final_data, status=status.HTTP_200_OK)

    def render_to_pdf(self, grouped_data, start_date, end_date, company):
        """
        Render payroll summary report to PDF.
        """
        
        html_string = render_to_string(
            "reports/payrolls/payroll_summary_temp.html",
            {
                "data": grouped_data,
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
        response_pdf["Content-Disposition"] = "inline; filename=payroll_summary_report.pdf"
        return response_pdf