from rest_framework.serializers import ModelSerializer, SerializerMethodField

from customerio.models import Customer

from salesio.models import Sale

from termio.django_rest.serializers.common import PrivateTermSlimSerializer

from wirehouseio.django_rest.serializers.common import PrivateWarehouseSlimSerializer


class PrivateWeSaleReportListSerializer(ModelSerializer):
    terms = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
    )
    warehouse = PrivateWarehouseSlimSerializer(read_only=True)

    class Meta:
        model = Sale
        fields = [
            "uid",
            "is_invoice",
            "terms",
            "warehouse",
            "due_date",
            "due_total",
            "created_at",
            "updated_at",
        ]


class PrivateWeOpenInvoiceReportListSerializer(ModelSerializer):
    invoices = SerializerMethodField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "uid",
            "first_name",
            "middle_name",
            "last_name",
            "invoices",
            "created_at",
            "updated_at",
        ]

    def get_invoices(self, instance):
        return PrivateWeSaleReportListSerializer(
            instance.sale_set.filter(is_invoice=True), many=True
        ).data
    
class PrivateWeOpenInvoiceReportDetailsSerializer(ModelSerializer):
    invoices = SerializerMethodField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "uid",
            "first_name",
            "middle_name",
            
            "last_name",
            "invoices",
            "created_at",
            "updated_at",
        ]

    def get_invoices(self, instance):
        return PrivateWeSaleReportListSerializer(
            instance.sale_set.filter(is_invoice=True), many=True
        ).data

