from rest_framework import serializers
from transactionio.models import (
    TransactionRules,
    TransactionRuleParams,
    TransactionRuleAssign,
)
from transactionio.tasks import apply_transaction_rule_task
from accounts.models import ChartOfAccount
from supplierio.models import Supplier
from customerio.models import Customer
from transactionio.django_rest.helpers.transaction_rule_apply import (
    apply_transaction_rule,
)

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from supplierio.django_rest.serializers.common import SupplierMinimalSerializer
from customerio.django_rest.serializers.common import CustomerMinimalSerializer

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class TransactionRuleSerializer(serializers.ModelSerializer):
    # uid = serializers.CharField(required=False, read_only=True)
    bank_accounts = serializers.SlugRelatedField(
        many=True,
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TransactionRules
        fields = [
            "uid",
            "title",
            "transaction_type",
            "all_account",
            "bank_accounts",
            "is_all",
            "auto_add",
            "company",
            "is_excluded",
        ]
        read_only_fields = ["uid", "slug", "company", "created_at", "updated_at"]


class TransactionRuleParamsSerializer(serializers.ModelSerializer):
    uid = serializers.CharField(required=False)

    class Meta:
        model = TransactionRuleParams
        fields = ["uid", "rule", "field", "operation", "value"]
        read_only_fields = ["uid", "slug", "rule", "created_at", "updated_at"]


class TransactionRuleAssignSerializer(CompanyScopedRelatedFieldsMixin, serializers.ModelSerializer):
    uid = serializers.CharField(required=False)
    chart_of_account = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        required=False,
        allow_null=True,
    )
    payee = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        required=False,
        allow_null=True,
    )
    customer = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Customer.objects.selectable().all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TransactionRuleAssign
        fields = [
            "uid",
            "trx_type",
            "rule",
            "chart_of_account",
            "payee",
            "customer",
            "memo",
            "is_split",
        ]
        read_only_fields = ["uid", "slug", "rule", "created_at", "updated_at"]


class TransactionRuleAssignListSerializer(serializers.ModelSerializer):
    # uid = serializers.CharField(required=False, read_only=True)
    chart_of_account = PrivateChartOfAccountSlimSerializer(
        required=False,
        allow_null=True,
    )
    payee = SupplierMinimalSerializer(
        required=False,
        allow_null=True,
    )
    customer = CustomerMinimalSerializer(
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TransactionRuleAssign
        fields = [
            "uid",
            "trx_type",
            "rule",
            "chart_of_account",
            "payee",
            "customer",
            "memo",
            "is_split",
        ]
        read_only_fields = ["uid", "slug", "rule", "created_at", "updated_at"]


class TransactionRuleCreateSerializer(serializers.Serializer):
    uid = serializers.CharField(required=False)
    transaction_rule = TransactionRuleSerializer(required=True)
    params = TransactionRuleParamsSerializer(many=True, required=False)
    assign = TransactionRuleAssignSerializer(required=False)

    def create_or_update(self, related_instance, rule_instance, data):
        """Resolve a rule's param or assignment row, or make one.

        Scoped to `rule_instance`, which is itself already resolved against the
        caller's company in `create()`. Without that predicate the lookup was
        `filter(uid=uid)` over every tenant's rows, and `uid` is client-writable
        on both nested serializers -- so posting somebody else's param uid
        rewrote their rule, and their bank feed then categorised against it.

        Narrowing by the parent rather than by company is the tighter of the two
        checks: a param belonging to the right company but a different rule is
        just as wrong to overwrite here.
        """
        uid = data.get("uid")
        instance = None
        if uid:
            instance = related_instance.objects.filter(
                uid=uid, rule=rule_instance
            ).first()
        if instance:
            for key, value in data.items():
                if key != "rule" and hasattr(instance, key):
                    setattr(instance, key, value)
            instance.save()
        else:

            create_data = {k: v for k, v in data.items() if k not in ("rule", "uid")}
            instance = related_instance.objects.create(
                rule=rule_instance, **create_data
            )
        return instance

    def create(self, validated_data):
        trx_uid = validated_data.get("uid", None)
        transaction_rule = validated_data.pop("transaction_rule", {})
        params_data = validated_data.pop("params", [])
        company = self.context.get("request").user.get_active_company()
        bank_accounts = transaction_rule.pop("bank_accounts", None)

        if trx_uid:
            rule_instance = TransactionRules.objects.filter(
                uid=trx_uid, company=company
            ).first()
        else:
            rule_instance = TransactionRules.objects.create(
                company=company, **transaction_rule
            )

        if rule_instance:
            for field, value in transaction_rule.items():
                setattr(rule_instance, field, value)
        if bank_accounts:
            rule_instance.bank_accounts.set(bank_accounts)
        rule_instance.save()

        for param in params_data:
            self.create_or_update(TransactionRuleParams, rule_instance, param)

        assign_data = validated_data.pop("assign", {})
        if assign_data:
            self.create_or_update(TransactionRuleAssign, rule_instance, assign_data)

        if not trx_uid and params_data:
            apply_transaction_rule_task.delay(str(rule_instance.uid))

        return rule_instance


class TransactionRuleListSerializer(serializers.ModelSerializer):
    bank_accounts = PrivateChartOfAccountSlimSerializer(
        required=False, allow_null=True, many=True
    )
    params = TransactionRuleParamsSerializer(many=True, read_only=True)
    assign = TransactionRuleAssignListSerializer(read_only=True)
    company = serializers.CharField(
        source="company.uid", required=False, read_only=True
    )

    class Meta:
        model = TransactionRuleSerializer.Meta.model
        fields = TransactionRuleSerializer.Meta.fields + [
            "params",
            "assign",
        ]
        # read_only_fields = ["uid", "slug", "company", "created_at", "updated_at"]
