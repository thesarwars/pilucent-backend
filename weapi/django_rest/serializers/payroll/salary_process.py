from django.db import transaction

from rest_framework import serializers
from payrollio.models import PayrollSalaryProcess, PayrollSalaryComponent

from employeeio.models import Employee

from accounts.models import ChartOfAccount

from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.django_rest.serializer.common import PayrollComponentSerializer
from payrollio.django_rest.helpers.rollups import recompute_parent_totals
from payrollio.django_rest.helpers.wage_caps import clamp_payroll_components
from payrollio.django_rest.helpers.ytd import compute_component_ytd

from common.django_rest.helpers.decorators import set_auditlog_actor

from moovmoneyio.django_rest.serializers.common import MoovBankAccountSettingsSerializer

from ...helpers.salary_process_journal_entry import (
    post_payroll_entries,
    unwind_existing_payroll_posting,
)


class EmployeePayrollBaseSerializer(serializers.ModelSerializer):
    work_locations = serializers.CharField(
        source="work_locations.location_state", allow_null=True
    )
    employee_bank_info = MoovBankAccountSettingsSerializer(
        allow_null=True, source="moov_employee_bank_accounts.first"
    )

    class Meta:
        model = Employee
        fields = ["uid", "full_name", "code", "work_locations", "employee_bank_info"]
        read_only_fields = fields


class PayrollSalaryProcessSerializer(serializers.ModelSerializer):
    uid = serializers.CharField(required=False)
    employee = EmployeePayrollBaseSerializer(read_only=True)
    employee_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all(),
        write_only=True,
        required=False,
    )
    payment_account_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
        required=False,
    )
    payroll_components = PayrollComponentSerializer(
        many=True, write_only=True, required=False
    )
    # payroll_components_detail = PayrollComponentSerializer(
    #     many=True, read_only=True, source="payroll_components", allow_null=True
    # )

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "title",
            "slug",
            "employee",
            "employee_uid",
            "schedule_name",
            "pay_date",
            "pay_period",
            "funding_account",
            "payment_account",
            "payment_account_uid",
            "pay_method",
            "project",
            "memo",
            "accrue_time_off",
            "gross_pay",
            "employee_taxes_deductions",
            "employer_taxes_contributions",
            "net_pay",
            "is_salary_done",
            "status",
            "payroll_components",
            # "payroll_components_detail",
        ]
        read_only_fields = ["slug", "employee", "funding_account", "payment_account"]

    # @set_auditlog_actor
    @transaction.atomic
    def create(self, validated_data):
        uid = validated_data.pop("uid", None)
        employee_uid = validated_data.pop("employee_uid", None)
        # print('employee_uid', employee_uid)
        payment_account_uid = validated_data.pop("payment_account_uid", None)
        payroll_components = validated_data.pop("payroll_components", [])

        # validated_data["company"] = self.context["company"]
        validated_data["employee"] = employee_uid
        validated_data["payment_account"] = payment_account_uid

        if uid:
            payroll_instance = PayrollSalaryProcess.objects.get(uid=uid)
            # Mutating a FINALIZED run would corrupt every later run's YTD.
            # Force the caller to void it and create a new run instead.
            if (
                payroll_instance.status
                == PayrollSalaryProcessStatusChoices.FINALIZED
            ):
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "Cannot modify a finalized payroll run. Void the "
                            "run and create a new one to make changes."
                        )
                    }
                )
            for field, value in validated_data.items():
                setattr(payroll_instance, field, value)
        else:
            payroll_instance = PayrollSalaryProcess.objects.create(**validated_data)

        payroll_instance.save()

        # Clamp capped federal taxes (SS, FUTA, Additional Medicare) against
        # YTD wages BEFORE persisting components. Excluding this run from the
        # YTD lookup prevents a re-saved DRAFT from double-counting itself.
        clamp_payroll_components(
            payroll_components,
            employee=employee_uid,
            pay_date=payroll_instance.pay_date,
            exclude_process_id=payroll_instance.id,
        )

        if payroll_components:
            for component_data in payroll_components:
                c_uid = component_data.pop("uid", None)
                if c_uid:
                    component_instance = PayrollSalaryComponent.objects.get(uid=c_uid)
                    for field, value in component_data.items():
                        setattr(component_instance, field, value)
                else:
                    component_instance = PayrollSalaryComponent.objects.create(
                        payroll=payroll_instance, **component_data
                    )
                # YTD = sum of prior FINALIZED runs of the same payroll_type
                # for this employee + this calendar year + the current row.
                compute_component_ytd(
                    component_instance,
                    exclude_process_id=payroll_instance.id,
                )
                component_instance.save()

            # Re-roll parent totals so they reflect any clamped child values.
            recompute_parent_totals(payroll_instance)

        employee = Employee.objects.select_related("work_locations").get(
            pk=employee_uid.pk
        )
        # Reverse before re-posting. This endpoint is an upsert -- pass a `uid`
        # and it edits the existing run -- and `create_journal_entry` is a
        # get_or_create keyed on `payroll_salary`, so a second save found the
        # SAME entry and appended another full set of legs to it. The entry
        # stayed balanced each pass, both sides being appended together, which
        # is exactly why the write-time balance check never caught it: what
        # doubled was the number of legs and every account's stored balance,
        # not the debit-credit totals.
        #
        # Same reverse-and-repost shape R5 settled on for sales, and the undo
        # direction comes from each connector's stored kind so rows written
        # before the side fixes unwind the way they actually posted.
        unwind_existing_payroll_posting(payroll_instance)
        post_payroll_entries(
            {**validated_data, "payroll_components": payroll_components},
            payroll_instance,
            self.context["company"],
            employee,
        )
        return validated_data


class PayrollSalaryProcessDetailsSerializer(serializers.ModelSerializer):
    employee = EmployeePayrollBaseSerializer(read_only=True)
    payroll_components = PayrollComponentSerializer(
        many=True, read_only=True, allow_null=True
    )
    company = serializers.SerializerMethodField()

    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "title",
            "slug",
            "employee",
            "company",
            "schedule_name",
            "pay_date",
            "pay_period",
            "funding_account",
            "payment_account",
            "pay_method",
            "project",
            "memo",
            "accrue_time_off",
            "gross_pay",
            "employee_taxes_deductions",
            "employer_taxes_contributions",
            "net_pay",
            "is_salary_done",
            "status",
            "payroll_components",
        ]
        read_only_fields = fields

    def get_company(self, obj):
        company = obj.employee.get_company()
        return {"uid": company.uid, "name": company.name} if company else None
