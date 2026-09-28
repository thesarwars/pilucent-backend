from rest_framework.serializers import ModelSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

from termio.models import Term


class PrivateWeTermListSerializer(ModelSerializer):
    class Meta:
        model = Term
        fields = ["uid", "title", "days", "is_active", "status"]
        read_only_fields = ["uid", "status"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)
    
    @set_auditlog_actor
    def create(self, validated_data):
        return super().create(validated_data)


class PrivateWeTermDetailsSerializer(ModelSerializer):
    class Meta:
        model = Term
        fields = [
            "uid",
            "title",
            "days",
            "is_active",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "status", "created_at", "updated_at"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)