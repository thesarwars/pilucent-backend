from rest_framework.generics import ListAPIView, RetrieveAPIView, get_object_or_404

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from customerio.models import Customer

from ..serializers.sale_reports import (
    PrivateWeOpenInvoiceReportListSerializer,
    PrivateWeOpenInvoiceReportDetailsSerializer,
)


class PrivateWeOpenInvoiceReportList(ListAPIView):
    serializer_class = PrivateWeOpenInvoiceReportListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return Customer.objects.get_status_active().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeOpenInvoiceReportDetails(RetrieveAPIView):
    serializer_class = PrivateWeOpenInvoiceReportDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            Customer.objects.get_status_active().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid"),
            )
        )
