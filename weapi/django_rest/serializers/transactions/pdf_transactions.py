from rest_framework import serializers
from rest_framework.serializers import ModelSerializer, ValidationError

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

from transactionio.models import TransactionMethod, TransactionInformation
from accounts.models import ChartOfAccount
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from companyio.django_rest.serializers.common import PrivateWeCompanySlimSerializer

class PrivateTransactionMethodListSerializer(ModelSerializer):
    class Meta:
        model = TransactionMethod
        fields = ["uid", "status", "created_at"]
        read_only_fields = ["uid", "created_at"]

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        # Check for duplicate TransactionMethod by uid within the company
        if TransactionMethod.objects.filter(uid=attrs.get("uid"), company=company).exists():
            raise ValidationError("Transaction method with this UID already exists in your company.")
        attrs["company"] = company
        # Set the status to "ACTIVE" (adjust this string if you have other conventions)
        attrs["status"] = "ACTIVE"
        return super().validate(attrs)


class PrivateTransactionMethodDetailsSerializer(ModelSerializer):
    class Meta:
        model = TransactionMethod
        fields = ["uid", "status", "created_at"]
        read_only_fields = ["uid", "created_at"]

    def validate(self, attrs):
        # For updates, just ensure that the company is set correctly
        company = self.context["request"].user.get_active_company()
        attrs["company"] = company
        return super().validate(attrs)


class PrivateTransactionInformationSerializer(
    CompanyScopedRelatedFieldsMixin, ModelSerializer
):
    """The router-registered CRUD surface for imported statement lines.

    Two things were wrong here, and both were invisible to a grep because
    `fields = "__all__"` never names a field.

    `is_matched` is the clearing tick. It is set by the reconciliation close
    path and by nothing else, but it was PATCH-writable on
    `/transactions/<pk>/` -- so a client could tick its own rows until
    `cleared_totals()` read whatever it wanted, then close a session with an
    empty `transaction_ids` list and a difference of zero. That is the same hole
    `csv_transactions.py` closed; this was the other serializer that writes the
    field. `journal_entry` and `matched_rule` are server-set for the same
    reason.

    `chart_of_account` resolved against every company's accounts. The mixin
    narrows it, as it does on the reconciliation and customer serializers.

    `fields = "__all__"` is kept so the response shape does not change, but it
    remains a standing hazard: any field added to the model in future is
    exposed, and writable, without anyone deciding to.
    """

    company = PrivateWeCompanySlimSerializer(read_only=True)
    chart_of_account = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TransactionInformation
        fields = "__all__"
        read_only_fields = [
            "slug",
            "is_matched",
            "journal_entry",
            "matched_rule",
        ]

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        attrs["company"] = company
        return super().validate(attrs)
