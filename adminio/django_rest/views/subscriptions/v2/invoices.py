from rest_framework import generics, response, status, views
from rest_framework.generics import get_object_or_404

from adminio.django_rest.mixins.subscription_pagination import AdminSubscriptionPaginationMixin
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import SubscriptionInvoice
from subscriptionio.services.admin_invoice_service import AdminInvoiceService


class AdminSubscriptionInvoiceList(AdminSubscriptionPaginationMixin, generics.ListAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return AdminInvoiceService.get_invoices_queryset(
            search=self.request.query_params.get("search"),
            status=self.request.query_params.get("status"),
            company_uid=self.request.query_params.get("company_uid"),
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        return self.paginated_list_response(
            queryset,
            AdminInvoiceService.serialize_invoices,
            summary=AdminInvoiceService.get_invoices_summary(queryset),
        )


class AdminSubscriptionInvoiceDetail(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid):
        invoice = get_object_or_404(
            SubscriptionInvoice.objects.prefetch_related("lines"),
            uid=uid,
        )
        return response.Response(AdminInvoiceService.get_invoice_detail(invoice))


class AdminSubscriptionInvoiceRetry(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid):
        invoice = get_object_or_404(SubscriptionInvoice, uid=uid)
        try:
            result = AdminInvoiceService.retry_invoice(
                invoice,
                actor=request.user.get_employee(),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)


class AdminSubscriptionInvoiceRefund(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid):
        invoice = get_object_or_404(SubscriptionInvoice, uid=uid)
        try:
            result = AdminInvoiceService.refund_invoice(
                invoice,
                actor=request.user.get_employee(),
                reason=request.data.get("reason", ""),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(result)
