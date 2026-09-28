from rest_framework.serializers import ModelSerializer

from customerio.models import Customer


class CustomerBaseSerializer(ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "currency",
            "first_name",
            "middle_name",
            "last_name",
            "image",
            "email",
            "company_name",
            "company_email",
        ]
        read_only_fields = fields


class PrivateCustomerSlimSerializer(CustomerBaseSerializer):
    class Meta:
        model = CustomerBaseSerializer.Meta.model
        fields = ["uid"] + CustomerBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCustomerSlimSerializer(CustomerBaseSerializer):
    class Meta:
        model = CustomerBaseSerializer.Meta.model
        fields = ["slug"] + CustomerBaseSerializer.Meta.fields
        read_only_fields = fields


class CustomerMinimalSerializer(ModelSerializer):
    class Meta:
        model = Customer
        fields = ["uid", "first_name", "last_name",]