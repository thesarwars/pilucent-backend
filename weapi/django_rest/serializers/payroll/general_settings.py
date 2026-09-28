from rest_framework import serializers

from payrollio.models import PayrollGeneralSettings

class PayrollGeneralSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollGeneralSettings
        fields = [
            'uid',
            'payroll_working_days',
            'is_total_working_days',
            'max_working_hours',
            'daily_salary_half_hours',
            'is_round_total',
            'is_show_leave_balance',
            'is_encrypt_salary_slip',
            'is_salary_slip',
            'email_template',
            'is_process_payroll_by_employee',
        ]
        read_only_fields = ['uid', 'created_by']
    
    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        attrs["created_by"] = self.context["request"].user.get_employee()
        return super().validate(attrs)