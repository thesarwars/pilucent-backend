from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from decimal import Decimal

from employeeio.django_rest.serializers.common import (
    PrivateEmployeeSalarySlimSerializer,
)
from employeeio.models import EmployeeSalary, EmployeeBankingInformation

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from payrollio.choicess import (
    SalaryAdjustmentKindChoices,
    SalaryAdjustmentStatusChoices,
)

from companyio.django_rest.serializers.common import (
    PrivateCompanyDesignationSlimSerializer,
    PrivateCompanyDepartmentSlimSerializer,
)

from employeeio.choices import EmployeeSalaryKind


class SalaryBreakdownSerializer(ModelSerializer):
    gross_earnings = SerializerMethodField()
    additions = SerializerMethodField()
    deductions = SerializerMethodField()
    total_addition = SerializerMethodField()
    total_deduction = SerializerMethodField()
    net_pay = SerializerMethodField()

    class Meta:
        model = EmployeeSalary
        fields = [
            "gross_earnings",
            "additions",
            "deductions",
            "total_addition",
            "total_deduction",
            "net_pay",
        ]

    def get_gross_earnings(self, obj):
        return float(Decimal(obj.gross or 0))

    def get_additions(self, obj):
        if obj.employee:
            adjustments = obj.employee.salaryadjustment_set.filter(
                status=SalaryAdjustmentStatusChoices.ACTIVE,
                kind=SalaryAdjustmentKindChoices.ADDITION,
            ).values("title", "amount")
            return [
                {"title": adj["title"], "amount": float(Decimal(adj["amount"] or 0))}
                for adj in adjustments
            ]
        return []

    def get_deductions(self, obj):
        if obj.employee:
            adjustments = obj.employee.salaryadjustment_set.filter(
                status=SalaryAdjustmentStatusChoices.ACTIVE,
                kind=SalaryAdjustmentKindChoices.DEDUCTION,
            ).values("title", "amount")
            return [
                {"title": adj["title"], "amount": float(Decimal(adj["amount"] or 0))}
                for adj in adjustments
            ]
        return []

    def get_total_addition(self, obj):
        if obj.employee:
            adjustments = obj.employee.salaryadjustment_set.filter(
                status=SalaryAdjustmentStatusChoices.ACTIVE,
                kind=SalaryAdjustmentKindChoices.ADDITION,
            ).values("amount")
            return float(sum(Decimal(adj["amount"] or 0) for adj in adjustments))
        return 0

    def get_total_deduction(self, obj):
        if obj.employee:
            adjustments = obj.employee.salaryadjustment_set.filter(
                status=SalaryAdjustmentStatusChoices.ACTIVE,
                kind=SalaryAdjustmentKindChoices.DEDUCTION,
            ).values("amount")
            return float(sum(Decimal(adj["amount"] or 0) for adj in adjustments))
        return 0

    def get_net_pay(self, obj):
        gross = Decimal(obj.gross or 0)
        additions = Decimal(self.get_total_addition(obj))
        deductions = Decimal(self.get_total_deduction(obj))
        return float(gross + additions - deductions)


class PrivateWeSalaryListSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    designation = PrivateCompanyDesignationSlimSerializer(
        source="employee.designation", read_only=True
    )
    department = PrivateCompanyDepartmentSlimSerializer(
        source="employee.department", read_only=True
    )
    salary_breakdown = SalaryBreakdownSerializer(source="*", read_only=True)

    class Meta:
        model = EmployeeSalary
        fields = [
            "uid",
            "slug",
            "title",
            "employee",
            "designation",
            "department",
            "kind",
            "salary_breakdown",
            "created_at",
            "updated_at",
            "gross",
            "basic",
            "house_rent",
            "medical_allowance",
            "transport_allowance",
            "food_allowance",
            "other_allowance",
            "grade_bonus",
            "mobile_allowance",
            "skill_bonus",
            "management_bonus",
            "special_allowance",
            "tiffin_allowance",
            "night_allowance",
            "income_tax",
            "lunch_deduction",
            "cash_provident_fund",
            "cash",
            "total",
            "over_time_rate",
        ]
        read_only_fields = [
            "uid",
            "slug",
            "employee",
            "designation",
            "department",
            "salary_breakdown",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if attrs.get('kind') == EmployeeSalaryKind.FIXED:
            company = self.context["request"].user.get_active_company()
            if not company:
                raise ValidationError("No active company found")
            
            # Check if company already has a FIXED salary
            existing_fixed = EmployeeSalary.objects.filter(
                company=company,
                kind=EmployeeSalaryKind.FIXED
            ).exists()
            
            if existing_fixed:
                raise ValidationError("Company already has a fixed salary configuration")
            
            attrs['company'] = company
        return attrs

    def create(self, validated_data):
        if validated_data.get('kind') != EmployeeSalaryKind.FIXED:
            validated_data.pop('company', None)
        return super().create(validated_data)


class PrivateWeSalaryDetailsSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    designation = PrivateCompanyDesignationSlimSerializer(
        source="employee.designation", read_only=True
    )
    department = PrivateCompanyDepartmentSlimSerializer(
        source="employee.department", read_only=True
    )
    salary_breakdown = SalaryBreakdownSerializer(source="*", read_only=True)

    class Meta:
        model = EmployeeSalary
        fields = [
            "uid",
            "slug",
            "title",
            "employee",
            "designation",
            "department",
            "salary_breakdown",
            "created_at",
            "updated_at",
            "gross",
            "basic",
            "house_rent",
            "medical_allowance",
            "transport_allowance",
            "food_allowance",
            "other_allowance",
            "grade_bonus",
            "mobile_allowance",
            "skill_bonus",
            "management_bonus",
            "special_allowance",
            "tiffin_allowance",
            "night_allowance",
            "income_tax",
            "lunch_deduction",
            "cash_provident_fund",
            "cash",
            "total",
            "over_time_rate",
        ]
        read_only_fields = [
            "uid",
            "slug",
            "employee",
            "designation",
            "department",
            "salary_breakdown",
            "created_at",
            "updated_at",
        ]


class PrivateWeEmployeeSalaryDetailsSerializer(ModelSerializer):
    class Meta:
        model = EmployeeSalary
        fields = [
            "uid",
            "gross",
            "basic",
            "house_rent",
            "medical_allowance",
            "transport_allowance",
            "food_allowance",
            "other_allowance",
            "grade_bonus",
            "mobile_allowance",
            "skill_bonus",
            "management_bonus",
            "special_allowance",
            "tiffin_allowance",
            "night_allowance",
            "income_tax",
            "lunch_deduction",
            "cash_provident_fund",
            "cash",
            "total",
            "over_time_rate",
        ]


class PrivateWeEmployeeBankingInformationDetailsSerializer(ModelSerializer):
    employee_salary = PrivateEmployeeSalarySlimSerializer(read_only=True)

    class Meta:
        model = EmployeeBankingInformation
        fields = [
            "uid",
            "bank_name",
            "account_number",
            "routing_number",
            "employee_salary",
            "iban",
            "kind",
            "created_at",
            "updated_at",
        ]
