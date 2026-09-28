from rest_framework import serializers
import django_filters
from payrollio.models import PayrollSalaryProcess


class MultipleWorksiteFilter(django_filters.FilterSet):
	date_from = django_filters.DateFilter(field_name='pay_date', lookup_expr='gte')
	date_to = django_filters.DateFilter(field_name='pay_date', lookup_expr='lte')
	pay_date_after = django_filters.DateFilter(field_name='pay_date', lookup_expr='gte')
	pay_date_before = django_filters.DateFilter(field_name='pay_date', lookup_expr='lte')
	year = django_filters.NumberFilter(field_name='pay_date__year', lookup_expr='exact')
	quarter = django_filters.ChoiceFilter(
		field_name='pay_date__month',
		choices=[
			('Q1', 'Q1 (Jan-Mar)'),
			('Q2', 'Q2 (Apr-Jun)'),
			('Q3', 'Q3 (Jul-Sep)'),
			('Q4', 'Q4 (Oct-Dec)'),
		],
		method='filter_by_quarter'
	)
	
	def filter_by_quarter(self, queryset, name, value):
		if value == 'Q1':
			return queryset.filter(pay_date__month__in=[1, 2, 3])
		elif value == 'Q2':
			return queryset.filter(pay_date__month__in=[4, 5, 6])
		elif value == 'Q3':
			return queryset.filter(pay_date__month__in=[7, 8, 9])
		elif value == 'Q4':
			return queryset.filter(pay_date__month__in=[10, 11, 12])
		return queryset
	
	class Meta:
		model = PayrollSalaryProcess
		fields = ['date_from', 'date_to', 'pay_date_after', 'pay_date_before', 'year', 'quarter']


class WorksiteDataSerializer(serializers.Serializer):
	"""Serializer for individual worksite data - shows employee counts per month and quarterly wages"""
	
	worksite = serializers.CharField(help_text="Company name")
	address = serializers.CharField(allow_blank=True, allow_null=True, help_text="Worksite address")
	city_state_zip = serializers.CharField(allow_blank=True, allow_null=True, help_text="City, State ZIP")
	month1_employees = serializers.IntegerField(default=0, help_text="Number of employees in first month of quarter")
	month2_employees = serializers.IntegerField(default=0, help_text="Number of employees in second month of quarter")
	month3_employees = serializers.IntegerField(default=0, help_text="Number of employees in third month of quarter")
	quarterly_wages = serializers.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Total gross pay for the quarter")


class MultipleWorksiteReportSerializer(serializers.Serializer):
	"""Serializer for multiple worksite report data - QuickBooks style report"""
	
	company_name = serializers.CharField(help_text="Company name")
	quarter_label = serializers.CharField(help_text="Quarter label with year (e.g., Q3 2025 (Jul-Sep))")
	year = serializers.IntegerField(help_text="Year for the report")
	worksites = WorksiteDataSerializer(many=True, help_text="List of worksites with employee counts and wages")

	class Meta:
		fields = [
			'company_name', 'quarter_label', 'year', 'worksites'
		]