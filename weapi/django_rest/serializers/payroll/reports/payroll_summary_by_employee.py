import django_filters

from payrollio.models import PayrollSalaryProcess


class PayrollSummaryByEmployeeFilter(django_filters.FilterSet):
    """Filters for the by-employee payroll summary.

    `employee` and `work_location` narrow which columns appear; the date
    filters narrow which runs are summed. Mirrors `PayrollSummaryFilter` so the
    two reports take the same query string.
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
    work_location = django_filters.CharFilter(
        field_name="employee__work_locations__uid", lookup_expr="exact"
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
            "work_location",
            "pay_period",
            "pay_method",
        ]
