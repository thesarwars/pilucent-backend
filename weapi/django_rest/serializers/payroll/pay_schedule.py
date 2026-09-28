from datetime import datetime

from payrollio.models import PaySchedule
from payrollio.django_rest.serializer.common import (
    PayrollSalaryProcessSlimSerializerForEmployee,
    CompanyEmployeeSalaryAdjustmentBaseSerializer,
    PrivateWePayrollWorkLocationSlimSerializer,
)
from payrollio.choicess import SalaryAdjustmentStatusChoices

from employeeio.models import Employee

from rest_framework import serializers

from common.django_rest.helpers.decorators import set_auditlog_actor

from weapi.django_rest.serializers.employees import (
    PrivateWeEmployeeDetailsSerializer,
    PrivateWeEmployeeEarningDetilsSerializer,
    PrivateWeEmployeeGarnishmentDetailsSerializer,
    PrivateWeEmployeeDeductionContributionDetailsSerializer,
    PrivateEmployeePayScheduleSerializer,
    PrivateWeEmployeeTaxDetailsSerializer,
    PrivateEmployeeUserSerializer,
)
from weapi.django_rest.serializers.payroll.deduction_and_contribution import (
    DedConDetailsSerializer,
)

from attendanceio.django_rest.serializers.common import PrivateHolidaySlimSerializer

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
    PrivateEmployeeBankingInformationSlimSerializer,
)

from addressio.django_rest.serializers.common import PrivateAddressSerializer

from adminio.django_rest.serializers.common import PrivateCompanyRoleSlimSerializer

from companyio.django_rest.serializers.common import (
    PrivateCompanyDepartmentSlimSerializer,
    PrivateCompanyDesignationSlimSerializer,
    PrivateCompanyShiftSlimSerializer,
)

from leaveio.django_rest.serializers.common import PrivateLeaveRequestSlimSerializer


class PayScheduleListCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaySchedule
        fields = [
            "uid",
            "title",
            "pay_frequency",
            "status",
            "is_default",
            "first_payday",
            "first_end_day",
            "first_month",
            "first_day",
            "second_payday",
            "second_end_day",
            "second_month",
            "second_day",
            "next_pay_date",
            "end_of_next_pay_period",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        company = self.context["request"].user.get_active_company()
        is_default = validated_data.get("is_default", False)
        if is_default:
            PaySchedule.objects.filter(company=company, is_default=is_default).update(
                is_default=False
            )
        return PaySchedule.objects.create(company=company, **validated_data)


class PayScheduleListUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaySchedule
        fields = PayScheduleListCreateSerializer.Meta.fields

    @set_auditlog_actor
    def update(self, instance, validated_data):
        company = self.context["request"].user.get_active_company()
        is_default = validated_data.get("is_default", False)
        if is_default:
            PaySchedule.objects.filter(company=company, is_default=True).exclude(
                id=instance.id
            ).update(is_default=False)
        return super().update(instance, validated_data)


class PayScheduleWithEmployeeCountSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PaySchedule
        fields = [
            "uid",
            "title",
            "employee_count",
            "pay_frequency",
            "next_pay_date",
        ]
        read_only_fields = fields


class PayScheduleAssignedEmployeeDetailsSerializer(serializers.ModelSerializer):
    user = PrivateEmployeeUserSerializer(read_only=True)
    # Department
    department = PrivateCompanyDepartmentSlimSerializer(read_only=True)
    # Desgnation
    designation = PrivateCompanyDesignationSlimSerializer(read_only=True)
    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    # Company role information
    company_role = PrivateCompanyRoleSlimSerializer(
        read_only=True, source="get_company_role"
    )
    # Report to information
    report_to = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    addresses = PrivateAddressSerializer(
        many=True, read_only=True, source="get_addresses"
    )
    # Banking informations
    banaking_informations = PrivateEmployeeBankingInformationSlimSerializer(
        source="get_banking_informations", read_only=True, many=True
    )
    # Tax information
    taxes = PrivateWeEmployeeTaxDetailsSerializer(
        source="get_first_tax", read_only=True
    )
    # Pay shedule information
    pay_schedule = PrivateEmployeePayScheduleSerializer(read_only=True)
    # Holyday information
    holiday = PrivateHolidaySlimSerializer(read_only=True)
    payroll_salary_process = PayrollSalaryProcessSlimSerializerForEmployee(
        read_only=True, allow_null=True, source="employee_salary", many=True
    )
    addition_deduction = serializers.SerializerMethodField(read_only=True)
    garnishment = PrivateWeEmployeeGarnishmentDetailsSerializer(
        read_only=True, many=True, allow_null=True, source="employeegarnishment_set"
    )
    earnings = PrivateWeEmployeeEarningDetilsSerializer(
        read_only=True, many=True, allow_null=True, source="employeeearning_set"
    )
    deduction_contributions = PrivateWeEmployeeDeductionContributionDetailsSerializer(
        read_only=True,
        many=True,
        allow_null=True,
        source="employeedeductioncontribution_set",
    )
    worked_hour_count = serializers.SerializerMethodField(read_only=True)
    paid_leave_hour_count = serializers.SerializerMethodField(read_only=True)
    un_paid_leave_hour_count = serializers.SerializerMethodField(read_only=True)
    ot_hour_count = serializers.SerializerMethodField(read_only=True)
    partial_paid_leave_hour_count = serializers.SerializerMethodField(read_only=True)
    leave_requests = serializers.SerializerMethodField(read_only=True)
    work_locations = PrivateWePayrollWorkLocationSlimSerializer(read_only=True)

    class Meta:
        model = Employee
        fields = [
            "uid",
            # User information
            "user",
            # Employee information
            "code",
            "employee_id",
            "kind",
            "status",
            "company_phone_number",
            "company_email",
            "is_joined",
            "on_boarding_kind",
            # Hiring information
            "confirmation_date",
            "notice_period",
            "offer_date",
            "contract_end_date",
            # Terminate information
            "terminate_date",
            "last_date_of_work",
            "terminate_kind",
            "terminate_description",
            # Company information
            "designation",
            "department",
            "shift",
            # Contact information
            "phone_number",
            "home_phone_number",
            "personal_email",
            "preferred_email",
            # Emargency contact information
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_phone_number",
            # Attendance information
            "attendance_device_id",
            # Company role information
            "company_role",
            # Report information
            "report_to",
            # Addresses
            "addresses",
            # Baking informations
            "banaking_informations",
            "is_banking_info_verified",
            # Tax information
            "taxes",
            # Payroll information
            "pay_kind",
            "is_over_time",
            "is_double_over_time",
            "is_holiday_pay",
            "is_bonus",
            "salary_frequency",
            "total_salary",
            "total_hour_per_day",
            "total_day_per_week",
            "total_rate_per_hour",
            "pay_schedule",
            "payroll_salary_process",
            "addition_deduction",
            "garnishment",
            "earnings",
            "deduction_contributions",
            # Eligibility
            "citizenship_kind",
            "uscis_or_alien_registration_number",
            "from_i_94",
            "foreign_passport",
            "w4_signature",
            "authorized_to_work_until",
            "is_not_applicable",
            "is_included_social_security_number_from_i9",
            # Holiday information
            "holiday",
            "worked_hour_count",
            "paid_leave_hour_count",
            "un_paid_leave_hour_count",
            "ot_hour_count",
            "partial_paid_leave_hour_count",
            "leave_requests",
            "work_locations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_addition_deduction(self, obj):
        pay_period = self.context.get("pay_period")
        if not pay_period:
            return []
        start_date, end_date = pay_period
        qs = obj.salaryadjustment_set.filter(
            status=SalaryAdjustmentStatusChoices.ACTIVE,
            input_date__range=(start_date, end_date),
        )
        return CompanyEmployeeSalaryAdjustmentBaseSerializer(qs, many=True).data

    def get_worked_hour_count(self, object):
        start_date, end_date = self.context.get("pay_period")
        return (
            object.get_worked_hours([start_date, end_date])
            if start_date and end_date
            else object.get_worked_hours(None)
        )

    def get_dates(self):
        return [
            date.strftime("%Y-%m-%d") for date in self.context.get("pay_period", [])
        ]

    def get_paid_leave_hour_count(self, object):
        return object.get_paid_leave_hour_count(self.get_dates())

    def get_un_paid_leave_hour_count(self, object):
        return object.get_un_paid_leave_hour_count(self.get_dates())

    def get_ot_hour_count(self, object):
        return object.get_ot_hour_count(self.get_dates())

    def get_partial_paid_leave_hour_count(self, object):
        return object.get_partial_paid_leave_hour_count(self.get_dates())

    def get_leave_requests(self, object):
        return PrivateLeaveRequestSlimSerializer(
            object.get_leave_requests(self.get_dates()), many=True
        ).data
