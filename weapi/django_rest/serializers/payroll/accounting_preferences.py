from rest_framework import serializers
from rest_framework.serializers import (
    CharField,
    SlugRelatedField,
    JSONField,
)
from django.db import transaction
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from employeeio.models import Employee
from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from payrollio.models import (
    PayrollAccountingPreferencesSetting,
    PayrollAccountExpenseAccountComponent,
    DeductionAndContributions,
)

from payrollio.django_rest.serializer.common import (
    PrivateWePayrollAccountExpenseAccountComponentSlimSerializer,
)


class PrivateWePayrollAccountingPreferencesListCreateSerializer(
    serializers.ModelSerializer
):
    uid = CharField(required=False)
    paycheck_payroll_tax_expense_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    paycheck_payroll_tax_expense_account = PrivateChartOfAccountSlimSerializer(
        read_only=True
    )
    global_wage_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    global_wage_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    global_contribution_expense_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    global_contribution_expense_account = PrivateChartOfAccountSlimSerializer(
        read_only=True
    )
    global_employer_tax_expenses_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    global_employer_tax_expenses = PrivateChartOfAccountSlimSerializer(read_only=True)
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    expense_accounts = PrivateWePayrollAccountExpenseAccountComponentSlimSerializer(
        many=True, read_only=True
    )
    expense_account_components = JSONField(
        required=False,
        write_only=True,
        help_text="List of expense account components, each containing 'uid', 'employee', 'account_type', 'expense_account', 'deduction and contribution'.",
    )

    class Meta:
        model = PayrollAccountingPreferencesSetting
        fields = [
            "uid",
            "paycheck_payroll_tax_expense_account_uid",
            "paycheck_payroll_tax_expense_account",
            "global_wage_account_uid",
            "global_wage_account",
            "global_contribution_expense_account_uid",
            "global_contribution_expense_account",
            "global_employer_tax_expenses_uid",
            "global_employer_tax_expenses",
            "expense_accounts",
            "expense_account_components",
            "wage_expense_type",
            "company_contribution_expense_type",
            "employer_tax_expense_type",
            "tax_liability_expense_type",
            "created_by",
        ]
        read_only_fields = ["created_by"]

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        uid = validated_data.pop("uid", None)

        # Handle account field assignments
        paycheck_payroll_tax_expense_account = validated_data.pop(
            "paycheck_payroll_tax_expense_account_uid", None
        )
        validated_data["paycheck_payroll_tax_expense_account"] = (
            paycheck_payroll_tax_expense_account
        )

        global_wage_account = validated_data.pop("global_wage_account_uid", None)
        validated_data["global_wage_account"] = global_wage_account

        global_contribution_expense_account = validated_data.pop(
            "global_contribution_expense_account_uid", None
        )
        validated_data["global_contribution_expense_account"] = (
            global_contribution_expense_account
        )

        global_employer_tax_expenses = validated_data.pop(
            "global_employer_tax_expenses_uid", None
        )
        validated_data["global_employer_tax_expenses"] = global_employer_tax_expenses

        expense_account_components_data = validated_data.pop(
            "expense_account_components", []
        )

        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()

        if uid:
            payroll_accounting_preferences = (
                PayrollAccountingPreferencesSetting.objects.get(uid=uid)
            )
            for field, value in validated_data.items():
                if value is not None:
                    setattr(payroll_accounting_preferences, field, value)
        else:
            payroll_accounting_preferences = (
                PayrollAccountingPreferencesSetting.objects.create(**validated_data)
            )

        payroll_accounting_preferences.save()

        # Handle expense account components
        if expense_account_components_data:
            for component_data in expense_account_components_data:
                component_uid = component_data.pop("uid", None)
                employee_uid = component_data.pop("employee", None)
                expense_account_uid = component_data.pop("expense_account", None)
                deduction_and_contribution_uid = component_data.pop(
                    "deduction_and_contribution", None
                )
                # Employee garnishments were removed with the US employee
                # module; drop the key so an old client cannot pass it to create().
                component_data.pop("employee_garnishment", None)

                # Resolve employee and expense_account from UID
                employee_instance = None
                expense_account_instance = None
                deduction_and_contribution_instance = None
                if employee_uid:
                    employee_instance = Employee.objects.get(
                uid=employee_uid, company=self.context["request"].user.get_active_company()
            )
                if expense_account_uid:
                    expense_account_instance = ChartOfAccount.objects.get(
                        uid=expense_account_uid
                    )
                if deduction_and_contribution_uid:
                    deduction_and_contribution_instance = (
                        DeductionAndContributions.objects.get(
                            uid=deduction_and_contribution_uid,
                            company=user.get_active_company(),
                        )
                    )

                if component_uid:
                    component_instance = (
                        PayrollAccountExpenseAccountComponent.objects.get(
                            uid=component_uid
                        )
                    )
                    for field, value in component_data.items():
                        setattr(component_instance, field, value)
                    if employee_instance:
                        component_instance.employee = employee_instance
                    if expense_account_instance:
                        component_instance.expense_account = expense_account_instance
                    if deduction_and_contribution_instance:
                        component_instance.deduction_and_contribution = (
                            deduction_and_contribution_instance
                        )
                else:
                    component_instance = PayrollAccountExpenseAccountComponent.objects.create(
                        payroll_accounting_preferences=payroll_accounting_preferences,
                        employee=employee_instance,
                        expense_account=expense_account_instance,
                        deduction_and_contribution=deduction_and_contribution_instance,
                        **component_data,
                    )
                component_instance.save()

        return payroll_accounting_preferences
