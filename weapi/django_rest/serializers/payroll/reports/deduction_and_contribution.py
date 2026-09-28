from rest_framework import serializers
import django_filters
from payrollio.models import PayrollSalaryProcess, PayrollSalaryComponent


class DeductionContributionFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='pay_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='pay_date', lookup_expr='lte')
    pay_date_after = django_filters.DateFilter(field_name='pay_date', lookup_expr='gte')
    pay_date_before = django_filters.DateFilter(field_name='pay_date', lookup_expr='lte')
    
    class Meta:
        model = PayrollSalaryProcess
        fields = ['date_from', 'date_to', 'pay_date_after', 'pay_date_before']


class DeductionContributionSerializer(serializers.ModelSerializer):
    """Serializer for deduction and contribution report data"""
    
    description = serializers.CharField()
    type = serializers.CharField()
    employee_deductions = serializers.DecimalField(max_digits=10, decimal_places=2)
    company_contributions = serializers.DecimalField(max_digits=10, decimal_places=2)
    plan_total = serializers.DecimalField(max_digits=10, decimal_places=2)
    
    class Meta:
        model = PayrollSalaryProcess
        fields = [
            'description',
            'type', 
            'employee_deductions',
            'company_contributions',
            'plan_total'
        ]
