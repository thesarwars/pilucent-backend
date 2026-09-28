from rest_framework.fields import DecimalField, SerializerMethodField

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from journalio.models import JournalEntryConnector


class PrivateWePayrollCostReportListSerializer(PrivateChartOfAccountSlimSerializer):
    last_balance = SerializerMethodField(read_only=True)

    class Meta:
        model = PrivateChartOfAccountSlimSerializer.Meta.model
        fields = PrivateChartOfAccountSlimSerializer.Meta.fields + ["last_balance"]

    def get_last_balance(self, instance):
        request = self.context["request"]
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        dates = [start_date, end_date] if start_date and end_date else None
        return instance.get_last_balance(dates)
