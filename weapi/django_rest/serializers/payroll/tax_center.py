from rest_framework import serializers

from payrollio.models import TaxCenterPayMethod, PayrollSalaryProcess

from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)

from journalio.django_rest.services.journals import JournalEntryService

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)


class TaxBreakdownLineSerializer(serializers.Serializer):
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class TaxBreakdownSerializer(serializers.Serializer):
    # Federal tax fields (only present for federal taxes)
    federal_income_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    social_security = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    social_security_employer = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    medicare = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    medicare_employer = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    total_federal_taxes = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )

    # State tax fields (only present for state taxes)
    state_income_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    state_unemployment_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    state_disability_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    state_employment_security_assessment = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    total_state_taxes = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )


class TaxPeriodSerializer(serializers.Serializer):
    period_key = serializers.CharField(max_length=100)
    period_label = serializers.CharField(max_length=255)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    due_date = serializers.DateField()
    status = serializers.CharField(max_length=50)
    tax_type = serializers.CharField(max_length=100)
    tax_category = serializers.CharField(max_length=20)
    account_type = serializers.CharField(max_length=100)
    action = serializers.CharField(max_length=20, required=False)
    tax_breakdown = TaxBreakdownSerializer()
    breakdown_lines = TaxBreakdownLineSerializer(many=True, required=False)
    payroll_count = serializers.IntegerField()
    amount_paid = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    amount_due = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    is_paid = serializers.BooleanField(required=False)


class TaxCenterReportSerializer(serializers.Serializer):
    tax_periods = TaxPeriodSerializer(many=True)
    total_periods = serializers.IntegerField()
    federal_periods = serializers.IntegerField()
    state_periods = serializers.IntegerField()
    year = serializers.IntegerField(required=False)


class PayrollTexCenterPayMethodSerializer(serializers.ModelSerializer):
    tax_liability_account_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
    )
    tax_record_account_uid = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
    )

    class Meta:
        model = TaxCenterPayMethod
        fields = [
            "uid",
            "tax_amount",
            "tax_liability_account_uid",
            "tax_record_account_uid",
            "payment_date",
            "check_number",
            "notes",
            "is_inside_balanzify",
            "liability_period",
            "is_paid",
            "is_filed",
        ]
        read_only_fields = ["uid"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.tax_liability_account_id:
            data["tax_liability_account_uid"] = str(instance.tax_liability_account.uid)
        if instance.tax_record_account_id:
            data["tax_record_account_uid"] = str(instance.tax_record_account.uid)
        return data

    def create(self, validated_data):
        company = self.context["request"].user.get_active_company()
        amount = validated_data.get("tax_amount", 0)
        tax_liability_account = validated_data.pop("tax_liability_account_uid")
        validated_data["tax_liability_account"] = tax_liability_account

        tax_record_account = validated_data.pop("tax_record_account_uid")
        validated_data["tax_record_account"] = tax_record_account
        validated_data.setdefault("is_paid", True)
        connector_data = []

        instance = TaxCenterPayMethod.objects.create(**validated_data)

        # Paying a payroll tax DEBITS the liability -- the debt goes down --
        # and CREDITS the account the money leaves. Both sides are fixed by the
        # transaction, and both accounts are user-chosen.
        #
        # The liability leg was mispaired: `"substraction"` is a DEBIT on a
        # liability, which is right, but its matching balance operation is
        # "debit" (subtract) and the call said "credit" (add). So recording a
        # payment pushed the tax debt UP by the amount just paid off, while the
        # journal entry footed perfectly. Same defect as 5d79e16f on the sales
        # tax payment, where both legs were mispaired rather than one.
        liability_action = action_for_side(
            tax_liability_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            tax_liability_account,
            balance_operation_for_action(liability_action),
            amount,
            0,
        )
        connector_data.append(
            (
                tax_liability_account,  # account = item[0]
                liability_action,  # action_type = item[1]
                amount,  # total_debit_or_credit = item[2]
                tax_liability_account.opening_balance,  # last_balance = item[3]
            )
        )
        funding_action = action_for_side(
            tax_record_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            tax_record_account,
            balance_operation_for_action(funding_action),
            amount,
            0,
        )
        connector_data.append(
            (
                tax_record_account,  # account = item[0]
                funding_action,  # action_type = item[1]
                amount,  # total_debit_or_credit = item[2]
                tax_record_account.opening_balance,  # last_balance = item[3]
            )
        )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PAYROLL_TAX_PAYMENT,
            is_transaction=True,
            is_journal_entry=False,
            company=company,
            object=instance,
        )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=amount,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            # employee=employee,
        )

        return instance

    # def update(self, instance, validated_data):
    #     for field, value in validated_data.items():
    #         setattr(instance, field, value)
    #     instance.save()
    #     return instance


class PayrollTaxCenterFilingMarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxCenterPayMethod
        fields = [
            "uid",
            "tax_amount",
            "payment_date",
            "liability_period",
            "notes",
            "is_filed",
            "is_paid",
        ]
        read_only_fields = ["uid"]

    def create(self, validated_data):
        validated_data.setdefault("is_filed", True)
        validated_data.setdefault("is_paid", False)
        return TaxCenterPayMethod.objects.create(**validated_data)


class PayrollTaxCenterFilingMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollSalaryProcess
        fields = [
            "uid",
            "filing_status",
            "filing_date",
            "confirmation_number",
            "notes",
        ]
        read_only_fields = ["uid"]