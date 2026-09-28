from rest_framework.serializers import ModelSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

from currencyio.models import Currency


class PrivateWeCurrencyListSerializer(ModelSerializer):

    class Meta:
        model = Currency
        fields = [
            "uid",
            "kind",
            "status",
            "exchange_rate",
            "date",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().create(validated_data)


class PrivateWeCurrencyDetailsSerializer(ModelSerializer):

    class Meta:
        model = Currency
        fields = [
            "uid",
            "title",
            "kind",
            "status",
            "exchange_rate",
            "date",
            "description",
            "created_at",
            "updated_at",
        ]
    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
