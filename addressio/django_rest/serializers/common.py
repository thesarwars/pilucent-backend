from rest_framework.serializers import ModelSerializer, CharField

from addressio.models import Address, AddressConnector


class AddressBaseSerializer(ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "country",
            "street",
            "city",
            "province",
            "postal_code",
            "full_address",
            "is_shipping",
            "is_work_address",
            "shipping_by",
            "shipping_date",
        ]
        read_only_fields = fields


class PrivateAddressSerializer(AddressBaseSerializer):
    class Meta:
        model = AddressBaseSerializer.Meta.model
        fields = ["uid", "is_shipping"] + AddressBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAddressSerializer(AddressBaseSerializer):
    class Meta:
        model = AddressBaseSerializer.Meta.model
        fields = ["slug"] + AddressBaseSerializer.Meta.fields
        read_only_fields = fields


class AddressConnectorBaseSerializer(ModelSerializer):
    street = CharField(source="address.street", read_only=True)
    city = CharField(source="address.city", read_only=True)
    province = CharField(source="address.province", read_only=True)
    postal_code = CharField(source="address.postal_code", read_only=True)
    full_address = CharField(source="address.full_address", read_only=True)

    class Meta:
        model = AddressConnector
        fields = [
            "street",
            "city",
            "province",
            "postal_code",
            "full_address",
        ]


class PrivateAddressConnectorSerializer(AddressConnectorBaseSerializer):
    class Meta:
        model = AddressConnectorBaseSerializer.Meta.model
        fields = ["uid"] + AddressConnectorBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAddressConnectorSerializer(AddressConnectorBaseSerializer):
    class Meta:
        model = AddressConnectorBaseSerializer.Meta.model
        fields = ["slug"] + AddressConnectorBaseSerializer.Meta.fields
        read_only_fields = fields
