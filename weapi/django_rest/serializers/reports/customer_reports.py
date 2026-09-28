from rest_framework.serializers import ModelSerializer

from customerio.models import Customer

class PrivateWeCustomerBalanceSheetSummaryReportSerializer(ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "currency",
            "first_name",
            "middle_name",
            "last_name",
            "image",
            "opening_balance",
            "created_at",
            "updated_at"
        ]
        read_only_fields = fields