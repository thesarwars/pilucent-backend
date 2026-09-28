from rest_framework.serializers import ModelSerializer, CharField

from ...models import SubscriptionPrice


class SubscriptionPriceSerializer(ModelSerializer):
    class Meta:
        model = SubscriptionPrice
        fields = ["billing_frequency", "price", "discount", "discount_kind"]
        read_only_fields = fields


class PrivateSubscriptionPriceSlimSerializer(SubscriptionPriceSerializer):
    class Meta:
        model = SubscriptionPriceSerializer.Meta.model
        fields = ["uid"] + SubscriptionPriceSerializer.Meta.fields
        read_only_fields = fields


class PublicSubscriptionPriceSlimSerializer(SubscriptionPriceSerializer):
    class Meta:
        model = SubscriptionPriceSerializer.Meta.model
        fields = ["slug"] + SubscriptionPriceSerializer.Meta.fields
        read_only_fields = fields
