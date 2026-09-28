from rest_framework.serializers import ModelSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

from brandio.models import Brand


class PrivateWeBrandListSerializer(ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "uid",
            "title",
            "kind",
            "status",
            "description",
        ]

        read_only_fields = ["uid", "created_at", "updated_at"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().create(validated_data)


class PrivateWeBrandDetailsSerializer(ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "uid",
            "title",
            "kind",
            "status",
            "description",
        ]

        read_only_fields = ["uid", "created_at", "updated_at"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().create(validated_data)
