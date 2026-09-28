from rest_framework.serializers import ModelSerializer, CharField

from supplierio.models import Supplier


class SupplierBaseSerializer(ModelSerializer):
    total_credit = CharField(source="get_credit_count", read_only=True)
    class Meta:
        model = Supplier
        fields = [
            "currency",
            "first_name",
            "last_name",
            "email",
            "mobile_number",
            "image",
            "display_name",
            "company_name",
            "opening_balance",
            "total_credit"
        ]
        read_only_fields = fields


class PrivateSupplierSlimSerializer(SupplierBaseSerializer):
    class Meta:
        model = SupplierBaseSerializer.Meta.model
        fields = ["uid"] + SupplierBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicSupplierSlimSerializer(SupplierBaseSerializer):
    class Meta:
        model = SupplierBaseSerializer.Meta.model
        fields = ["slug"] + SupplierBaseSerializer.Meta.fields
        read_only_fields = fields


class SupplierMinimalSerializer(ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["uid", "first_name", "last_name",]