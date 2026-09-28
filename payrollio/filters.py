from django_filters import BooleanFilter, CharFilter, FilterSet

from payrollio.models import PayrollSalaryProcess


class PaycheckReportFilter(FilterSet):
    employee = CharFilter(field_name="employee__uid", lookup_expr="exact")
    is_salary_done = BooleanFilter(field_name="is_salary_done")
    pay_method = CharFilter(field_name="pay_method", lookup_expr="exact")
    status = CharFilter(field_name="status", lookup_expr="exact")

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "employee",
            "is_salary_done",
            "pay_method",
            "status",
        ]
