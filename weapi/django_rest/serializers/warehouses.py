from rest_framework.serializers import ModelSerializer, CharField, ValidationError

from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices
from addressio.models import Address, AddressConnector
from addressio.django_rest.serializers.common import PrivateAddressSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

from wirehouseio.choicess import WarehouseKindChoices
from wirehouseio.models import Warehouse


class PrivateWeWarehouseListSerializer(ModelSerializer):
    full_address = CharField(write_only=True)
    address = PrivateAddressSerializer(source="get_address", read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "uid",
            "title",
            "short_name",
            "remark",
            "kind",
            "address",
            "full_address",
        ]

    read_only_fields = ["uid", "kind", "address"]

    def validate(self, validated_data):
        company = self.context["request"].user.get_active_company()
        if validated_data[
            "kind"
        ] == WarehouseKindChoices.MAIN and Warehouse.objects.get_status_all().filter(
            company=company, kind=WarehouseKindChoices.MAIN
        ):
            raise ValidationError({"message": "You already have main warehouse."})
        validated_data["company"] = company
        return super().validate(validated_data)

    @set_auditlog_actor
    def create(self, validated_data):
        address_data = {
            "full_address": validated_data.pop("full_address"),
            "company": validated_data["company"],
            "status": AddressStatusChoices.ACTIVE,
        }
        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.WAREHOUSE,
            warehouse=Warehouse.objects.create(**validated_data),
            address=Address.objects.create(**address_data),
        )
        return validated_data


class PrivateWeWarehouseDetailsSerializer(ModelSerializer):
    full_address = CharField(required=False)
    address = PrivateAddressSerializer(source="get_address", read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "uid",
            "title",
            "short_name",
            "remark",
            "kind",
            "address",
            "full_address",
        ]

    read_only_fields = ["uid", "kind", "address"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        company = self.context["request"].user.get_active_company()
        if validated_data[
            "kind"
        ] == WarehouseKindChoices.MAIN and Warehouse.objects.get_status_all().filter(
            company=company, kind=WarehouseKindChoices.MAIN
        ):
            raise ValidationError({"message": "You already have main warehouse."})
        
        full_address = validated_data.pop("full_address", None)
        if full_address:
            address_connector = instance.addressconnector_set.first().address
            address_connector.full_address = full_address
            address_connector.save()
        return super().update(instance, validated_data)
