from rest_framework.serializers import ModelSerializer, CharField

from brandio.models import Brand, BrandConnector


class BrandBaseSerializer(ModelSerializer):
    class Meta:
        model = Brand
        fields = ["title", "description", "kind", "status"]
        read_only_fields = fields


class PrivateBrandSlimSerializer(BrandBaseSerializer):
    class Meta:
        model = BrandBaseSerializer.Meta.model
        fields = ["uid"] + BrandBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicBrandSlimSerializer(BrandBaseSerializer):
    class Meta:
        model = BrandBaseSerializer.Meta.model
        fields = ["slug"] + BrandBaseSerializer.Meta.fields
        read_only_fields = fields


class BrandConnectorBaseSerializer(ModelSerializer):
    class Meta:
        model = BrandConnector
        fields = ["brand", "product"]
        read_only_fields = fields


class PrivateBrandConnectorSlimSerializer(ModelSerializer):
    title = CharField(source="brand.title")
    description = CharField(source="brand.description")
    kind = CharField(source="brand.kind")
    status = CharField(source="brand.status")

    class Meta:
        model = BrandConnector
        fields = ["title", "description", "kind", "status"]
        read_only_fields = fields


class PublicBrandConnectorSlimSerializer(BrandConnectorBaseSerializer):
    class Meta:
        model = BrandConnectorBaseSerializer.Meta.model
        fields = ["slug"] + BrandConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class BrandConnectorDetailsSlimSerializer(ModelSerializer):
    title = CharField(source="brand.title", read_only=True)
    description = CharField(source="brand.description", read_only=True)

    class Meta:
        model = BrandConnectorBaseSerializer.Meta.model
        fields = ["title", "description", "uid"]
        read_only_fields = fields
