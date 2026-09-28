from rest_framework import serializers

from payrollio.models import PayrollSalaryProcess

from weapi.django_rest.helpers.payroll.paycheck_report import format_money
from weapi.django_rest.serializers.payroll.salary_process import (
    PayrollSalaryProcessDetailsSerializer,
)


class PaycheckProcessedRunSerializer(serializers.ModelSerializer):
    gross_pay = serializers.SerializerMethodField()
    net_pay = serializers.SerializerMethodField()

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "pay_date",
            "pay_period",
            "pay_method",
            "accrue_time_off",
            "gross_pay",
            "net_pay",
            "is_salary_done",
            "status",
        ]
        read_only_fields = fields

    def get_gross_pay(self, obj):
        return format_money(obj.gross_pay)

    def get_net_pay(self, obj):
        return format_money(obj.net_pay)


class PaycheckEmployeeHeaderSerializer(serializers.Serializer):
    uid = serializers.UUIDField()
    full_name = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    work_locations = serializers.CharField(allow_null=True)
    employee_bank_info = serializers.JSONField(allow_null=True)
    pay_period = serializers.CharField()
    total_pay = serializers.CharField()
    net_pay = serializers.CharField()
    pay_method = serializers.CharField(allow_null=True)
    check_number = serializers.CharField(allow_null=True, allow_blank=True)
    status = serializers.CharField(allow_null=True)


class PaycheckEmployeeGroupSerializer(serializers.Serializer):
    employee = PaycheckEmployeeHeaderSerializer()
    processed_data = PaycheckProcessedRunSerializer(many=True)


class PaycheckRunDetailSerializer(PayrollSalaryProcessDetailsSerializer):
    """Single paycheck run with full payroll_components (read-only)."""

    class Meta(PayrollSalaryProcessDetailsSerializer.Meta):
        read_only_fields = PayrollSalaryProcessDetailsSerializer.Meta.fields
