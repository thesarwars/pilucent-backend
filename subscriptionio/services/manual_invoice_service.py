from decimal import Decimal

from django.db import transaction
from django.utils.timezone import now

from subscriptionio.choices import (
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
    SubscriptionInvoiceLineTypeChoices,
    SubscriptionInvoiceStatusChoices,
)
from subscriptionio.models import SubscriptionInvoice, SubscriptionInvoiceLine
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


class ManualInvoiceService:
    @classmethod
    @transaction.atomic
    def create_invoice(
        cls,
        *,
        company,
        lines: list[dict],
        currency: str,
        notes: str = "",
        period_start=None,
        period_end=None,
        actor=None,
        mark_paid: bool = False,
    ) -> SubscriptionInvoice:
        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            raise ValueError("Company does not have an active subscription record.")

        subtotal = Decimal("0")
        invoice_lines = []
        for line in lines:
            line_type = line.get("line_type", SubscriptionInvoiceLineTypeChoices.BASE)
            description = line.get("description", "Manual charge")
            quantity = Decimal(str(line.get("quantity", 1)))
            unit_amount = Decimal(str(line.get("unit_amount", 0)))
            amount = quantity * unit_amount
            subtotal += amount
            invoice_lines.append(
                {
                    "line_type": line_type,
                    "description": description,
                    "quantity": quantity,
                    "unit_amount": unit_amount,
                    "amount": amount,
                    "metadata": line.get("metadata", {}),
                }
            )

        invoice = SubscriptionInvoice.objects.create(
            company=company,
            company_subscription=company_subscription,
            subscription_price=company_subscription.subscription_price,
            status=(
                SubscriptionInvoiceStatusChoices.PAID
                if mark_paid
                else SubscriptionInvoiceStatusChoices.OPEN
            ),
            currency=currency,
            subtotal=subtotal,
            total=subtotal,
            period_start=period_start,
            period_end=period_end,
            is_manual=True,
            notes=notes,
            billing_reason="manual",
            title=f"Manual invoice {now().date()}",
        )

        for line_data in invoice_lines:
            SubscriptionInvoiceLine.objects.create(invoice=invoice, **line_data)

        SubscriptionEventService.record(
            company=company,
            company_subscription=company_subscription,
            event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
            source=SubscriptionEventSourceChoices.ADMIN,
            actor=actor,
            payload={
                "action": "manual_invoice_created",
                "invoice_uid": str(invoice.uid),
                "total": str(subtotal),
            },
        )
        return invoice
