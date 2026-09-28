from rest_framework.serializers import ModelSerializer
from accounts.models import ChartOfAccount



class PrivateWeCashFlowListSerializer(ModelSerializer):

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "opening_balance",
            "kind",
            "created_at",
            "updated_at",
        ]

