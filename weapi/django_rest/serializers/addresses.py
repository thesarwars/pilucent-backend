from rest_framework.serializers import CharField, ModelSerializer, SlugRelatedField

from addressio.choices import AddressConnectorKindCoices
from addressio.models import Address, AddressConnector

from common.django_rest.helpers.decorators import set_auditlog_actor

from employeeio.choices import EmployeeStatusChoices
from employeeio.models import Employee


class PrivateWeAddressListSerializer(ModelSerializer):
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all().exclude(status=EmployeeStatusChoices.REMOVED),
        write_only=True,
    )
    kind = CharField(source="get_kind", read_only=True)

    """Here will have rest of the related field such as supplier, customer, sale, purchase and so on """

    class Meta:
        model = Address
        fields = [
            "uid",
            "street",
            "city",
            "province",
            "postal_code",
            "full_address",
            "is_shipping",
            "shipping_by",
            "shipping_date",
            "status",
            "kind",
            "country",
            "is_work_address",
            "employee_uid",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        company = self.context["request"].user.get_active_company()
        employee = validated_data.pop("employee_uid", None)

        # Creating address
        validated_data["company"] = company
        address = Address.objects.create(**validated_data)

        # Creating address connector
        address_connector_kind = AddressConnectorKindCoices.COMPANY
        if employee:
            address_connector_kind = AddressConnectorKindCoices.EMPLOYEE

        AddressConnector.objects.create(
            company=company,
            address=address,
            employee=employee,
            kind=address_connector_kind,
        )
        return validated_data


class PrivateWeAddressDetailsSerializer(ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "uid",
            "street",
            "city",
            "province",
            "postal_code",
            "full_address",
            "is_shipping",
            "shipping_by",
            "shipping_date",
            "status",
            "country",
            "is_work_address",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
