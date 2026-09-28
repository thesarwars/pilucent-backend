from rest_framework import serializers
from subscriptionio.models import Subscription, SubscriptionPrice


class AdminSubsPriceSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False)

    class Meta:
        model = SubscriptionPrice
        fields = ["id", "billing_frequency", "price", "discount", "discount_kind"]
        # read_only_fields = fields


class AdminSubscriptionSerializer(serializers.ModelSerializer):
    sub_price = AdminSubsPriceSerializer(
        required=False, many=True, source="subscriptionprice_set"
    )
    uid = serializers.CharField(required=False)

    class Meta:
        model = Subscription
        fields = [
            "uid",
            "slug",
            "title",
            "status",
            "kind",
            "description",
            "currency",
            "user_limit",
            "storage_limit",
            "trial_period",
            "is_chart_of_account",
            "is_chart_of_account_tree",
            "is_journal_entry",
            "is_bank_transaction",
            "is_sales",
            "is_customer",
            "is_inventory",
            "is_warehouse",
            "is_expense",
            "is_supplier_management",
            "is_standard_report",
            "is_agency_tax",
            "is_employees",
            "is_payroll",
            "is_attendance",
            "is_punch_data_import",
            "is_multicurrency",
            "is_company_setting",
            "is_audit_log",
            "is_attachment",
            "is_user_role_management",
            "is_terms",
            "is_payment_management",
            "is_configuration",
            "is_user_profile",
            "is_support_ticket",
            "is_ai_finzify",
            "is_auto_renew",
            "is_enable_email_notification",
            "cancel_policy",
            "note",
            "sub_price",
            # Accountant related
            "is_monthly_bookkeeping_and_reconciliations",
            "is_reports",
            "is_annual_tax_filing",
            "is_1099_preparation_filing",
            "is_30_minute_consultation_per_quarter",
            "is_monthly_or_biweekly_payroll_processing",
            "is_quarterly_tax_planning_reviews",
            "is_budgeting_and_cash_flow_forecasting",
            "is_sales_tax_filing",
            "is_unlimited_email_support",
            "is_dedicated_accountant",
            "is_Virtual_CFO_services",
            "is_financial_modeling_and_custom_dashboards",
            "is_investo_ready_financial_statements",
            "is_audit_support_and_representation",
            "is_year_end_planning_for_tax_minimization",
            "is_multi_entity_or_multi_state_handling",
            "is_priority_support",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "slug",
            "created_at",
            "updated_at",
        ]

    def update_price(self, price_instance, subs_instance, data):
        id = data.get("id")
        print("price_id", id)
        instance = None
        if id:
            instance = price_instance.objects.filter(id=id).first()

        if instance:
            for field, value in data.items():
                setattr(instance, field, value)
            instance.save()
        else:
            instance = price_instance.objects.create(subscription=subs_instance, **data)

        return instance

    def create(self, validated_data):
        sub_price = validated_data.pop("subscriptionprice_set", None)
        print("sub_price", sub_price)
        uid = validated_data.get("uid")

        subscription = None
        if uid:
            subscription = Subscription.objects.get(uid=uid)
        else:
            subscription = Subscription.objects.create(**validated_data)

        if subscription:
            for field, value in validated_data.items():
                setattr(subscription, field, value)
            subscription.save()

        if sub_price:
            for subs in sub_price:
                self.update_price(SubscriptionPrice, subscription, subs)

        return subscription
