from rest_framework.serializers import ModelSerializer, CharField

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from agencyio.django_rest.serializers.common import PrivateAgencyTaxSlimSerializer

from productio.models import (
    Product,
    ProductBundle,
    ProductBundleConnector,
    ProductAdditionalCost,
)

from brandio.django_rest.serializers.common import PrivateBrandConnectorSlimSerializer

from categoryio.django_rest.serializers.common import (
    PrivateCategoryConnectorSlimSerializer,
)
from supplierio.django_rest.serializers.common import PrivateSupplierSlimSerializer


class ProductBaseSerializer(ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "title",
            "sku",
            "kind",
            "quantity",
            "status",
            "reorder_point",
            "sale_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateProductSlimSerializer(ProductBaseSerializer):
    class Meta:
        model = ProductBaseSerializer.Meta.model
        fields = ["uid"] + ProductBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicProductSlimSerializer(ProductBaseSerializer):
    class Meta:
        model = ProductBaseSerializer.Meta.model
        fields = ["slug"] + ProductBaseSerializer.Meta.fields
        read_only_fields = fields


class ProductBundleBaseSerializer(ModelSerializer):
    class Meta:
        model = ProductBundle
        fields = [
            "title",
            "description",
        ]
        read_only_fields = ["created_at", "updated_at"]


class ProductBundleSlimSerializer(ProductBundleBaseSerializer):
    class Meta:
        model = ProductBundleBaseSerializer.Meta.model
        fields = ["uid"] + ProductBundleBaseSerializer.Meta.fields
        read_only_fields = fields


class ProductBundleConnectorBaseSerializer(ModelSerializer):
    uid = CharField(source="products.uid")
    title = CharField(source="products.title")
    sku = CharField(source="products.sku")
    code = CharField(source="products.code")
    description = CharField(source="products.description")
    # quantity = CharField(source="products.quantity")
    brand = PrivateBrandConnectorSlimSerializer(
        source="products.brandconnector_set.first", read_only=True
    )
    category = PrivateCategoryConnectorSlimSerializer(
        source="products.categoryconnector_set.first", read_only=True
    )

    class Meta:
        model = ProductBundleConnector
        fields = [
            "uid",
            "title",
            "sku",
            "code",
            "description",
            # "quantity",
            "brand",
            "category",
        ]
        read_only_fields = ["created_at", "updated_at"]


class ProductBundleConnectorSlimSerializer(ProductBundleConnectorBaseSerializer):
    class Meta:
        model = ProductBundleConnectorBaseSerializer.Meta.model
        fields = ["uid"] + ProductBundleConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class PrivateProductAdditionalCostSlimSerializer(ModelSerializer):
    expense_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    prefferred_supplier = PrivateSupplierSlimSerializer(read_only=True)
    tax = PrivateAgencyTaxSlimSerializer(read_only=True)

    class Meta:
        model = ProductAdditionalCost
        fields = [
            "uid",
            "expense_account",
            "prefferred_supplier",
            "tax",
            "amount",
            "description",
        ]
