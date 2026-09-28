from rest_framework.serializers import ModelSerializer, CharField

from categoryio.models import Category, CategoryConnector


class CategoryBaseSerializer(ModelSerializer):
    class Meta:
        model = Category
        fields = ["title", "description", "status", "kind"  ]
        read_only_fields = fields


class PrivateCategorySlimSerializer(CategoryBaseSerializer):
    class Meta:
        model = CategoryBaseSerializer.Meta.model
        fields = ["uid"] + CategoryBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCategorySlimSerializer(CategoryBaseSerializer):
    class Meta:
        model = CategoryBaseSerializer.Meta.model
        fields = ["slug"] + CategoryBaseSerializer.Meta.fields
        read_only_fields = fields


class CategoryConnectorBaseSerializer(ModelSerializer):
    title = CharField(source='category.title', read_only=True)
    description = CharField(source='category.description', read_only=True)
    kind = CharField(source='category.kind', read_only=True)
    status = CharField(source='category.status', read_only=True)
    class Meta:
        model = CategoryConnector
        fields = ["title", "description", "kind", "status"]
        read_only_fields = fields


class PrivateCategoryConnectorSlimSerializer(CategoryConnectorBaseSerializer):
    class Meta:
        model = CategoryConnectorBaseSerializer.Meta.model
        fields = ["uid"] + CategoryConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCategoryConnectorSlimSerializer(CategoryConnectorBaseSerializer):
    class Meta:
        model = CategoryConnectorBaseSerializer.Meta.model
        fields = ["slug"] + CategoryConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateWeCategoryConnectorSlimDetailsSerializer(ModelSerializer):
    category = CharField(source='category.title', read_only=True)
    details = CharField(source='category.description', read_only=True)
    class Meta:
        model = CategoryConnectorBaseSerializer.Meta.model
        fields = ["category", "details", "uid"]
        read_only_fields = fields
        