from versatileimagefield.serializers import VersatileImageFieldSerializer

from rest_framework.serializers import ModelSerializer, CharField, SerializerMethodField

from ...models import (
    SalaryAdjustment,
    DeductionAndContributions,
    PayrollSalaryProcess,
    PayrollSalaryComponent,
    PayrollStateTaxPaymentSchedule,
    PayrollUnemploymentInsuranceTaxInfo,
    PayrollReemploymentOrWorkforceServiceFund,
    PayrollMCTMTZone,
    PayrollAccountExpenseAccountComponent,
    PayrollAccountingPreferencesSetting,
    PayrollFederalLoanInterestPaymentSchedule,
    PayrollFederalTaxInfoSettingItems,
    PayrollWorkLocation
)

from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from accounts.django_rest.serializers.common import (
    PrivateChartOfAccountSlimSerializer,
)


class CompanyEmployeeSalaryAdjustmentBaseSerializer(ModelSerializer):
    class Meta:
        model = SalaryAdjustment
        fields = ["status", "kind", "input_date", "amount", "created_at", "updated_at"]
        read_only_fields = fields


class PrivateCompanyEmployeeSalaryAdjustmentSlimSerializer(
    CompanyEmployeeSalaryAdjustmentBaseSerializer
):

    class Meta:
        model = CompanyEmployeeSalaryAdjustmentBaseSerializer.Meta.model
        fields = ["uid"] + CompanyEmployeeSalaryAdjustmentBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCompanyEmployeeSalaryAdjustmentSlimSerializer(
    CompanyEmployeeSalaryAdjustmentBaseSerializer
):

    class Meta:
        model = CompanyEmployeeSalaryAdjustmentBaseSerializer.Meta.model
        fields = ["slug"] + CompanyEmployeeSalaryAdjustmentBaseSerializer.Meta.fields
        read_only_fields = fields


class PayrollComponentSerializer(ModelSerializer):
    uid = CharField(required=False)

    class Meta:
        model = PayrollSalaryComponent
        fields = [
            "uid",
            "payroll_type",
            "payroll_category",
            "current",
            "ytd",
            "hours",
            "rate",
        ]

class PrivateWeDeductionAndContributionsSlimSerializer(ModelSerializer):
    class Meta:
        model = DeductionAndContributions
        fields = [
            "uid",
            "title",
            "deduction_type",
            "sub_type",
            "tax_type",
        ]
        read_only_fields = ["uid", "slug"]

# Slim Serializers for Payroll State Tax Related Models
class PayrollStateTaxPaymentScheduleSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollStateTaxPaymentSchedule
        fields = ["uid", "payment_frequency", "effective_date"]
        read_only_fields = fields


class PayrollUnemploymentInsuranceTaxInfoSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollUnemploymentInsuranceTaxInfo
        fields = ["uid", "ui_rate", "effective_date"]
        read_only_fields = fields


class PayrollReemploymentOrWorkforceServiceFundSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollReemploymentOrWorkforceServiceFund
        fields = ["uid", "reemployment_or_workforce_fund_rate", "effective_date"]
        read_only_fields = fields


class PayrollFederalLoanInterestPaymentScheduleSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollFederalLoanInterestPaymentSchedule
        fields = ["uid", "ui_rate", "effective_date"]
        read_only_fields = fields


class PayrollMCTMTZoneSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollMCTMTZone
        fields = ["uid", "zone", "mctmt_rate", "effective_date"]
        read_only_fields = fields


class PayrollSalaryProcessSlimSerializerForEmployee(ModelSerializer):
    payroll_components = PayrollComponentSerializer(many=True, read_only=True)
    last_current_salary = SerializerMethodField()

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "title",
            "slug",
            "pay_date",
            "pay_period",
            "is_salary_done",
            "payroll_components",
            "last_current_salary",
            "created_at",
        ]
        read_only_fields = fields

    @staticmethod
    def _iter_payroll_components(obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", None)
        if prefetched is not None and "payroll_components" in prefetched:
            return prefetched["payroll_components"]
        return obj.payroll_components.all()

    def get_last_current_salary(self, obj):
        salary_components = [
            c
            for c in self._iter_payroll_components(obj)
            if c.payroll_type == "salary" and c.payroll_category == "PAY"
        ]
        if not salary_components:
            return 0.0
        return max(salary_components, key=lambda c: c.id).current


class PrivateWePayrollAccountingPreferencesSettingSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollAccountingPreferencesSetting
        fields = [
            "uid",
            "paycheck_payroll_tax_expense_account",
            "global_wage_account",
            "global_contribution_expense_account",
            "global_employer_tax_expenses",
            "wages_expense_type",
            "company_contribution_expense_type",   
        ]
        read_only_fields = ["uid"]


class PrivateWePayrollAccountExpenseAccountComponentSlimSerializer(ModelSerializer):
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    expense_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    deduction_and_contribution = PrivateWeDeductionAndContributionsSlimSerializer(
        read_only=True
    )

    class Meta:
        model = PayrollAccountExpenseAccountComponent
        fields = [
            "uid",
            "employee",
            "payroll_accounting_preferences_type",
            "account_type",
            "expense_account",
            "deduction_and_contribution",
        ]
        read_only_fields = fields


class PrivateWePayrollFederalTaxInfoSettingItemsSlimSerializer(ModelSerializer):
    is_current = SerializerMethodField()

    class Meta:
        model = PayrollFederalTaxInfoSettingItems
        fields = [
            "uid",
            "tax_form",
            "payment_frequency",
            "effective_date",
            "is_current",
        ]
        read_only_fields = fields

    def get_is_current(self, obj):
        from payrollio.django_rest.helpers.federal_tax_setting_items import (
            get_current_federal_tax_item,
        )

        if not obj.payroll_federal_tax_info_id:
            return False
        items = obj.payroll_federal_tax_info.items.all()
        current = get_current_federal_tax_item(items, obj.tax_form)
        return bool(current and current.pk == obj.pk)



class PrivateWePayrollWorkLocationSlimSerializer(ModelSerializer):
    class Meta:
        model = PayrollWorkLocation
        fields = [
            "uid",
            "location_address",
            "location_city",
            "location_state",
            "location_zip",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
