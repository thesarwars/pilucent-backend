from rest_framework.serializers import ModelSerializer, SlugRelatedField, CharField
from agencyio.models import Agency, AgencyTax, AgencyTaxSet
from accounts.models import ChartOfAccount
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer


class AgencyBaseSerializer(ModelSerializer):
    class Meta:
        model = Agency
        fields = [
            "title",
            "filling_frequency",
            "reporting_method",
            "status",
            "date",
            "state",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateWeAgencySlimSerializer(AgencyBaseSerializer):
    class Meta:
        model = AgencyBaseSerializer.Meta.model
        fields = ["uid"] + AgencyBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAgencySlimSerializer(AgencyBaseSerializer):
    class Meta:
        model = AgencyBaseSerializer.Meta.model
        fields = ["slug"] + AgencyBaseSerializer.Meta.fields
        read_only_fields = fields


class AgencyTaxBaseSerializer(ModelSerializer):
    class Meta:
        model = AgencyTax
        fields = [
            "title",
            # "rate",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateAgencyTaxSlimSerializer(AgencyTaxBaseSerializer):
    class Meta:
        model = AgencyTaxBaseSerializer.Meta.model
        fields = ["uid"] + AgencyTaxBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAgencyTaxSlimSerializer(AgencyTaxBaseSerializer):
    class Meta:
        model = AgencyTaxBaseSerializer.Meta.model
        fields = ["slug"] + AgencyTaxBaseSerializer.Meta.fields
        read_only_fields = fields


class AgencyTaxForGroupSerializer(ModelSerializer):
    agency_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Agency.objects.get_status_all(),
        write_only=True,
    )

    sales_tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
    )

    class Meta:
        model = AgencyTax
        fields = [
            "uid",
            "title",
            "is_single",
            "rate",
            "created_at",
            "updated_at",
        ]


class AgencyTaxSetSerializer(ModelSerializer):
    uid = CharField(required=False)
    agency_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Agency.objects.get_status_all(),
        write_only=True,
    )
    agency = PrivateWeAgencySlimSerializer(read_only=True)

    sales_tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
    )
    sales_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

    class Meta:
        model = AgencyTaxSet
        fields = [
            "uid",
            "nickname",
            "rate",
            # "taxes",
            "agency_uid",
            "agency",
            "sales_tax_uid",
            "sales_tax_account",
        ]
        read_only_fields = ["uid", "slug", "created_at", "updated_at"]


class AgencyTaxSerializer(ModelSerializer):
    tax_groups = AgencyTaxSetSerializer(many=True, read_only=True)

    class Meta:
        model = AgencyTax
        fields = ["uid", "title", "slug", "is_single", "total_rate", "company", "tax_groups"]
