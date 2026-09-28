import logging
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now

from subscriptionio.choices import (
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
    SubscriptionInvoiceStatusChoices,
)
from subscriptionio.models import SubscriptionInvoice
from subscriptionio.services.subscription_event_service import SubscriptionEventService

logger = logging.getLogger("subscriptionio.admin_invoice")
stripe.api_key = settings.STRIPE_SECRET_KEY


class AdminInvoiceService:
    @classmethod
    def get_invoices_queryset(
        cls,
        *,
        search: str | None = None,
        status: str | None = None,
        company_uid: str | None = None,
    ):
        qs = SubscriptionInvoice.objects.select_related(
            "company", "company_subscription"
        ).order_by("-created_at")

        if search:
            qs = qs.filter(
                Q(company__name__icontains=search)
                | Q(stripe_invoice_id__icontains=search)
                | Q(uid__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        if company_uid:
            qs = qs.filter(company__uid=company_uid)
        return qs

    @classmethod
    def get_invoices_summary(cls, qs) -> dict[str, str]:
        paid_total = (
            qs.filter(status=SubscriptionInvoiceStatusChoices.PAID).aggregate(
                total=Sum("total")
            )["total"]
            or Decimal("0")
        )
        outstanding_total = (
            qs.filter(
                status__in=[
                    SubscriptionInvoiceStatusChoices.OPEN,
                    SubscriptionInvoiceStatusChoices.DRAFT,
                ]
            ).aggregate(total=Sum("total"))["total"]
            or Decimal("0")
        )
        failed_total = (
            qs.filter(status=SubscriptionInvoiceStatusChoices.FAILED).aggregate(
                total=Sum("total")
            )["total"]
            or Decimal("0")
        )
        return {
            "collected_total": str(paid_total.quantize(Decimal("0.01"))),
            "outstanding_total": str(outstanding_total.quantize(Decimal("0.01"))),
            "failed_total": str(failed_total.quantize(Decimal("0.01"))),
        }

    @classmethod
    def serialize_invoices(cls, invoices) -> list[dict[str, Any]]:
        return [cls._serialize_invoice(item) for item in invoices]

    @classmethod
    def list_invoices(
        cls,
        *,
        search: str | None = None,
        status: str | None = None,
        company_uid: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        qs = cls.get_invoices_queryset(
            search=search,
            status=status,
            company_uid=company_uid,
        )
        invoices = list(qs[:limit])
        return {
            "summary": cls.get_invoices_summary(qs),
            "results": cls.serialize_invoices(invoices),
        }

    @classmethod
    def _serialize_invoice(cls, invoice: SubscriptionInvoice) -> dict[str, Any]:
        return {
            "uid": str(invoice.uid),
            "company_uid": str(invoice.company.uid),
            "company_name": invoice.company.name,
            "status": invoice.status,
            "currency": invoice.currency,
            "subtotal": str(invoice.subtotal),
            "discount_total": str(invoice.discount_total),
            "tax_total": str(invoice.tax_total),
            "total": str(invoice.total),
            "period_start": invoice.period_start,
            "period_end": invoice.period_end,
            "hosted_invoice_url": invoice.hosted_invoice_url,
            "stripe_invoice_id": invoice.stripe_invoice_id,
            "is_manual": invoice.is_manual,
            "billing_reason": invoice.billing_reason,
            "created_at": invoice.created_at,
        }

    @classmethod
    def get_invoice_detail(cls, invoice: SubscriptionInvoice) -> dict[str, Any]:
        data = cls._serialize_invoice(invoice)
        data["lines"] = [
            {
                "uid": str(line.uid),
                "line_type": line.line_type,
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_amount": str(line.unit_amount),
                "amount": str(line.amount),
            }
            for line in invoice.lines.all()
        ]
        data["notes"] = invoice.notes
        return data

    @classmethod
    @transaction.atomic
    def retry_invoice(cls, invoice: SubscriptionInvoice, *, actor=None) -> dict[str, Any]:
        if invoice.status not in {
            SubscriptionInvoiceStatusChoices.FAILED,
            SubscriptionInvoiceStatusChoices.OPEN,
        }:
            raise ValueError("Only failed or open invoices can be retried.")

        if invoice.stripe_invoice_id:
            try:
                stripe.Invoice.pay(invoice.stripe_invoice_id)
            except stripe.error.StripeError as exc:
                logger.exception("Stripe invoice retry failed uid=%s", invoice.uid)
                raise ValueError(
                    exc.user_message if hasattr(exc, "user_message") else str(exc)
                ) from exc

        invoice.status = SubscriptionInvoiceStatusChoices.PAID
        invoice.save(update_fields=["status", "updated_at"])

        if invoice.company_subscription_id:
            SubscriptionEventService.record(
                company=invoice.company,
                company_subscription=invoice.company_subscription,
                event_type=SubscriptionEventTypeChoices.PAYMENT_RECOVERED,
                previous_status=invoice.company_subscription.status,
                new_status=invoice.company_subscription.status,
                source=SubscriptionEventSourceChoices.ADMIN,
                actor=actor,
                payload={"invoice_uid": str(invoice.uid), "action": "retry"},
            )

        return cls.get_invoice_detail(invoice)

    @classmethod
    @transaction.atomic
    def refund_invoice(
        cls,
        invoice: SubscriptionInvoice,
        *,
        actor=None,
        reason: str = "",
    ) -> dict[str, Any]:
        if invoice.status != SubscriptionInvoiceStatusChoices.PAID:
            raise ValueError("Only paid invoices can be refunded.")

        if invoice.stripe_invoice_id:
            try:
                stripe_invoice = stripe.Invoice.retrieve(invoice.stripe_invoice_id)
                payment_intent = stripe_invoice.get("payment_intent")
                if payment_intent:
                    stripe.Refund.create(payment_intent=payment_intent)
            except stripe.error.StripeError as exc:
                logger.exception("Stripe refund failed uid=%s", invoice.uid)
                raise ValueError(
                    exc.user_message if hasattr(exc, "user_message") else str(exc)
                ) from exc

        invoice.status = SubscriptionInvoiceStatusChoices.VOID
        note = reason or "Refunded by admin"
        invoice.notes = f"{invoice.notes}\n{note} ({now().isoformat()})".strip()
        invoice.save(update_fields=["status", "notes", "updated_at"])

        if invoice.company_subscription_id:
            SubscriptionEventService.record(
                company=invoice.company,
                company_subscription=invoice.company_subscription,
                event_type=SubscriptionEventTypeChoices.PAYMENT_FAILED,
                previous_status=invoice.company_subscription.status,
                new_status=invoice.company_subscription.status,
                source=SubscriptionEventSourceChoices.ADMIN,
                actor=actor,
                payload={
                    "invoice_uid": str(invoice.uid),
                    "action": "refund",
                    "reason": reason,
                },
            )

        return cls.get_invoice_detail(invoice)
