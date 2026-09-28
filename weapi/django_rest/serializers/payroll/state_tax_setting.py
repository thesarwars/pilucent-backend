from django.db import transaction
from rest_framework import serializers
from rest_framework.fields import JSONField

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from payrollio.models import (
    PayrollStateTaxInfoSetting,
    PayrollStateTaxPaymentSchedule,
    PayrollUnemploymentInsuranceTaxInfo,
    PayrollReemploymentOrWorkforceServiceFund,
    PayrollFederalLoanInterestPaymentSchedule,
    PayrollMCTMTZone,
)


# Import slim serializers from common
from payrollio.django_rest.serializer.common import (
    PayrollStateTaxPaymentScheduleSlimSerializer,
    PayrollUnemploymentInsuranceTaxInfoSlimSerializer,
    PayrollReemploymentOrWorkforceServiceFundSlimSerializer,
    PayrollFederalLoanInterestPaymentScheduleSlimSerializer,
    PayrollMCTMTZoneSlimSerializer,
)


class PayrollStateTaxInfoSettingSerializer(serializers.ModelSerializer):
    payment_schedules_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of payment schedules, each containing 'payment_frequency' and 'effective_date'.",
    )

    unemployment_insurance_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of unemployment insurance tax info, each containing 'rate', and 'effective_date'.",
    )
    reemployment_service_funds_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of reemployment service funds, each containing 'rate', and 'effective_date'.",
    )
    federal_loan_interest_payment_schedule_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of federal loan interest payment schedules, each containing 'ui_rate' and 'effective_date'.",
    )
    mctmt_zone_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of MCTMT zones, each containing 'zone', 'rate', and 'effective_date'.",
    )
    payment_schedules = PayrollStateTaxPaymentScheduleSlimSerializer(
        many=True, read_only=True
    )
    unemployment_insurance = PayrollUnemploymentInsuranceTaxInfoSlimSerializer(
        many=True, read_only=True
    )
    federal_loan_interest_payment_schedules = PayrollFederalLoanInterestPaymentScheduleSlimSerializer(
        many=True, read_only=True
    )
    reemployment_service_funds = (
        PayrollReemploymentOrWorkforceServiceFundSlimSerializer(
            many=True, read_only=True
        )
    )
    mctmt_zones = PayrollMCTMTZoneSlimSerializer(many=True, read_only=True)
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollStateTaxInfoSetting
        fields = [
            "uid",
            "state",
            "win_number",
            "ui_registration_number",
            "payment_schedules",
            "unemployment_insurance",
            "federal_loan_interest_payment_schedules",
            "reemployment_service_funds",
            "mctmt_zones",
            "payment_schedules_list",
            "unemployment_insurance_list",
            "reemployment_service_funds_list",
            "federal_loan_interest_payment_schedule_list",
            "mctmt_zone_list",
            "created_by",
        ]
        read_only_fields = ["uid"]

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()

        payment_schedules_data = validated_data.pop("payment_schedules_list", [])
        unemployment_insurance_data = validated_data.pop(
            "unemployment_insurance_list", []
        )
        reemployment_service_funds_data = validated_data.pop(
            "reemployment_service_funds_list", []
        )
        federal_loan_interest_payment_schedule = validated_data.pop(
            "federal_loan_interest_payment_schedule_list", []
        )
        mctmt_zone_data = validated_data.pop("mctmt_zone_list", [])

        state_tax_setting = super().create(validated_data)

        for schedule in payment_schedules_data:
            PayrollStateTaxPaymentSchedule.objects.create(
                payroll_state_tax_info=state_tax_setting,
                **schedule,
            )

        for ui_info in unemployment_insurance_data:
            PayrollUnemploymentInsuranceTaxInfo.objects.create(
                payroll_state_tax_info=state_tax_setting,
                **ui_info,
            )

        for fund in reemployment_service_funds_data:
            PayrollReemploymentOrWorkforceServiceFund.objects.create(
                payroll_state_tax_info=state_tax_setting,
                **fund,
            )
            
        for loan_info in federal_loan_interest_payment_schedule:
            PayrollFederalLoanInterestPaymentSchedule.objects.create(
                payroll_state_tax_info=state_tax_setting,
                **loan_info,
            )

        for zone in mctmt_zone_data:
            PayrollMCTMTZone.objects.create(
                payroll_state_tax_info=state_tax_setting,
                **zone,
            )

        return state_tax_setting


class PayrollStateTaxInfoDetailsUpdateSettingSerializer(serializers.ModelSerializer):
    payment_schedules = PayrollStateTaxPaymentScheduleSlimSerializer(
        many=True, read_only=True
    )
    unemployment_insurance = PayrollUnemploymentInsuranceTaxInfoSlimSerializer(
        many=True, read_only=True
    )
    reemployment_service_funds = (
        PayrollReemploymentOrWorkforceServiceFundSlimSerializer(
            many=True, read_only=True
        )
    )
    federal_loan_interest_payment_schedules = PayrollFederalLoanInterestPaymentScheduleSlimSerializer(
        many=True, read_only=True
    )
    mctmt_zones = PayrollMCTMTZoneSlimSerializer(many=True, read_only=True)
    payment_schedules_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of payment schedules, each containing 'payment_frequency' and 'effective_date'.",
    )
    unemployment_insurance_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of unemployment insurance tax info, each containing 'rate', and 'effective_date'.",
    )
    federal_loan_interest_payment_schedule_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of federal loan interest payment schedules, each containing 'ui_rate' and 'effective_date'.",
    )
    reemployment_service_funds_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of reemployment service funds, each containing 'rate', and 'effective_date'.",
    )
    mctmt_zone_list = JSONField(
        required=False,
        write_only=True,
        help_text="List of MCTMT zones, each containing 'zone', 'rate', and 'effective_date'.",
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollStateTaxInfoSetting
        fields = [
            "uid",
            "state",
            "win_number",
            "ui_registration_number",
            "payment_schedules",
            "unemployment_insurance",
            "reemployment_service_funds",
            "federal_loan_interest_payment_schedules",
            "mctmt_zones",
            "payment_schedules_list",
            "federal_loan_interest_payment_schedule_list",
            "unemployment_insurance_list",
            "reemployment_service_funds_list",
            "mctmt_zone_list",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user

        payment_schedules_data = validated_data.pop("payment_schedules_list", []) or []
        unemployment_insurance_data = (
            validated_data.pop("unemployment_insurance_list", []) or []
        )
        reemployment_service_funds_data = (
            validated_data.pop("reemployment_service_funds_list", []) or []
        )
        federal_loan_interest_payment_schedule = (
            validated_data.pop("federal_loan_interest_payment_schedule_list", []) or []
        )
        mctmt_zone_data = validated_data.pop("mctmt_zone_list", []) or []

        instance.state = validated_data.get("state", instance.state)
        instance.win_number = validated_data.get("win_number", instance.win_number)
        instance.ui_registration_number = validated_data.get(
            "ui_registration_number", instance.ui_registration_number
        )
        instance.save()

        # Update or create payment schedules
        for schedule in payment_schedules_data:
            uid = schedule.pop("uid", None)
            if uid:
                obj = PayrollStateTaxPaymentSchedule.objects.filter(
                    uid=uid, payroll_state_tax_info=instance
                ).first()
                if obj:
                    for key, value in schedule.items():
                        setattr(obj, key, value)
                    obj.save()
            else:
                PayrollStateTaxPaymentSchedule.objects.create(
                    payroll_state_tax_info=instance,
                    **schedule,
                )

        # Update or create unemployment insurance
        for ui_info in unemployment_insurance_data:
            uid = ui_info.pop("uid", None)
            if uid:
                obj = PayrollUnemploymentInsuranceTaxInfo.objects.filter(
                    uid=uid, payroll_state_tax_info=instance
                ).first()
                if obj:
                    for key, value in ui_info.items():
                        setattr(obj, key, value)
                    obj.save()
            else:
                PayrollUnemploymentInsuranceTaxInfo.objects.create(
                    payroll_state_tax_info=instance,
                    **ui_info,
                )

        # Update or create reemployment service funds
        for fund in reemployment_service_funds_data:
            uid = fund.pop("uid", None)
            if uid:
                obj = PayrollReemploymentOrWorkforceServiceFund.objects.filter(
                    uid=uid, payroll_state_tax_info=instance
                ).first()
                if obj:
                    for key, value in fund.items():
                        setattr(obj, key, value)
                    obj.save()
            else:
                PayrollReemploymentOrWorkforceServiceFund.objects.create(
                    payroll_state_tax_info=instance,
                    **fund,
                )
                
        # Update or create federal loan interest payment schedules
        for loan_info in federal_loan_interest_payment_schedule:
            uid = loan_info.pop("uid", None)
            if uid:
                obj = PayrollFederalLoanInterestPaymentSchedule.objects.filter(
                    uid=uid, payroll_state_tax_info=instance
                ).first()
                if obj:
                    for key, value in loan_info.items():
                        setattr(obj, key, value)
                    obj.save()
            else:
                PayrollFederalLoanInterestPaymentSchedule.objects.create(
                    payroll_state_tax_info=instance,
                    **loan_info,
                )
                
        # Update or create MCTMT zones
        for zone in mctmt_zone_data:
            uid = zone.pop("uid", None)
            if uid:
                obj = PayrollMCTMTZone.objects.filter(
                    uid=uid, payroll_state_tax_info=instance
                ).first()
                if obj:
                    for key, value in zone.items():
                        setattr(obj, key, value)
                    obj.save()
            else:
                PayrollMCTMTZone.objects.create(
                    payroll_state_tax_info=instance,
                    **zone,
                )

        return instance
