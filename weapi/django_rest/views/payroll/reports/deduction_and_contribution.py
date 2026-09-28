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
from common.django_rest.helpers.date_range_filters import WeekMonthYearRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription
from weapi.django_rest.serializers.payroll.reports.deduction_and_contribution import DeductionContributionSerializer, DeductionContributionFilter


class DeductionContributionReportView(generics.ListAPIView):
    serializer_class = DeductionContributionSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_standard_report"
    filterset_class = DeductionContributionFilter
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
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

        # Group data by payroll_type for deductions and contributions
        deduction_contribution_data = defaultdict(lambda: {
            'description': '',
            'type': '',
            'employee_deductions': Decimal('0.00'),
            'company_contributions': Decimal('0.00'),
            'plan_total': Decimal('0.00'),
        })

        # Process all payroll entries
        for payroll_entry in queryset:
            for component in payroll_entry.payroll_components.all():
                # Only process deductions and contributions
                if component.payroll_category in [
                    'EMPLOYEE_TAXES', 
                    'EMPLOYEE_DEDUCTIONS', 
                    'EMPLOYER_TAXES', 
                    'COMPANY_PAID_CONTRIBUTIONS'
                ]:
                    key = component.payroll_type
                    component_current = Decimal(str(component.current or 0))
                    
                    # Initialize if first time seeing this type
                    if not deduction_contribution_data[key]['description']:
                        deduction_contribution_data[key]['description'] = component.payroll_type
                        deduction_contribution_data[key]['type'] = component.payroll_category.replace('_', ' ').title()
                    
                    # Categorize amounts
                    if component.payroll_category in ['EMPLOYEE_TAXES', 'EMPLOYEE_DEDUCTIONS']:
                        deduction_contribution_data[key]['employee_deductions'] += component_current
                    elif component.payroll_category in ['EMPLOYER_TAXES', 'COMPANY_PAID_CONTRIBUTIONS']:
                        deduction_contribution_data[key]['company_contributions'] += component_current
                    
                    # Add to plan total
                    deduction_contribution_data[key]['plan_total'] += component_current

        # Convert to list and calculate totals
        deduction_list = []
        total_employee_deductions = Decimal('0.00')
        total_company_contributions = Decimal('0.00')
        total_plan_total = Decimal('0.00')

        for item_data in deduction_contribution_data.values():
            if item_data['plan_total'] > 0:  # Only include items with amounts
                deduction_list.append(item_data)
                total_employee_deductions += item_data['employee_deductions']
                total_company_contributions += item_data['company_contributions']
                total_plan_total += item_data['plan_total']

        # Sort by description for consistent ordering
        deduction_list.sort(key=lambda x: x['description'])

        final_data = {
            'deductions_and_contributions': deduction_list,
            'total_employee_deductions': total_employee_deductions,
            'total_company_contributions': total_company_contributions,
            'total_plan_total': total_plan_total,
        }

        if request.query_params.get("keywords", None) == "overview":
            return Response({
                'total_items': len(deduction_list),
                'total_employee_deductions': total_employee_deductions,
                'total_company_contributions': total_company_contributions,
                'total_plan_total': total_plan_total,
            })

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
        Render deduction and contribution report to PDF.
        """
        
        html_string = render_to_string(
            "reports/payrolls/deduction_contribution_temp.html",
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
        response_pdf["Content-Disposition"] = "inline; filename=deduction_contribution_report.pdf"
        return response_pdf