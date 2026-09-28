from rest_framework.serializers import ModelSerializer

from ...models import Currency, CurrencyConnector


class CurrencyBaseSerializer(ModelSerializer):
    class Meta:
        model = Currency
        fields = ["kind", "exchange_rate", "date"]
        read_only_fields = fields


class PrivateCurrencySlimSerializer(CurrencyBaseSerializer):

    class Meta:
        model = CurrencyBaseSerializer.Meta.model
        fields = ["uid"] + CurrencyBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicCurrencySlimSerializer(CurrencyBaseSerializer):

    class Meta:
        model = CurrencyBaseSerializer.Meta.model
        fields = ["slug"] + CurrencyBaseSerializer.Meta.fields
        read_only_fields = fields
