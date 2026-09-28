from rest_framework import serializers
import django_filters
from payrollio.models import PayrollSalaryProcess, PayrollSalaryComponent


class PayrollSummarySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.user.name", read_only=True)
    employee_id = serializers.CharField(source="employee.uid", read_only=True)
    
    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "slug", 
            "employee_name",
            "employee_id",
            "pay_date",
            "pay_period",
            "gross_pay",
            "employee_taxes_deductions", 
            "employer_taxes_contributions",
            "net_pay",
            "created_at",
        ]
        read_only_fields = ["uid", "slug", "created_at"]





class PayrollSummaryFilter(django_filters.FilterSet):
    """
    Filter class for filtering payroll summary entries.
    """
    pay_date_after = django_filters.DateFilter(
        field_name="pay_date", lookup_expr="gte"
    )
    pay_date_before = django_filters.DateFilter(
        field_name="pay_date", lookup_expr="lte"
    )
    employee = django_filters.CharFilter(
        field_name="employee__uid", lookup_expr="exact"
    )
    pay_period = django_filters.CharFilter(
        field_name="pay_period", lookup_expr="icontains"
    )

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "pay_date_after",
            "pay_date_before", 
            "employee",
            "pay_period",
            "pay_method",
        ]
