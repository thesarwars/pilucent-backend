from decimal import Decimal

from django.db.models import Count, Sum, DecimalField
from django.db.models.functions import Coalesce

from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import transactions

from salesio.models import Sale
from salesio.choices import SalesStatusChoices
from purchaseio.models import Purchase
from purchaseio.choices import PurchaseStatus


ZERO = Decimal("0.00")


class PrivateWeDashboardApprovalCenterView(DashboardCardView):
    """Card 18 — Approval Center.

    Returns draft documents awaiting approval (invoices, bills) plus a recent
    transactions list. Error/restricted states are still emitted as envelopes
    by the base view.
    """

    card_key = "approval_center"
    action_route = "/approvals"
    DEFAULT_TXN_LIMIT = 10

    @staticmethod
    def _summary(queryset):
        agg = queryset.aggregate(
            count=Count("id"),
            amount=Coalesce(Sum("total"), ZERO, output_field=DecimalField()),
        )
        return agg["count"], float(agg["amount"])

    def get_card_data(self, request, filters):
        company = filters.company

        invoice_count, invoice_amount = self._summary(
            Sale.objects.filter(
                company=company, is_invoice=True, status__in=[SalesStatusChoices.PAID, SalesStatusChoices.ACCEPTED]
            )
        )
        bill_count, bill_amount = self._summary(
            Purchase.objects.filter(
                company=company, is_bill=True, status=PurchaseStatus.ACCEPTED
            )
        )

        approval = [
            {
                "count": str(invoice_count),
                "label": "Invoices",
                "amount": f"${invoice_amount:,.2f}",
            },
            {
                "count": str(bill_count),
                "label": "Bills",
                "amount": f"${bill_amount:,.2f}",
            },
        ]

        return {
            "approval": approval,
            "transactions": transactions.recent_transactions(
                company, limit=self.DEFAULT_TXN_LIMIT
            ),
        }
