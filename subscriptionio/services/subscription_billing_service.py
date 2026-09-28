from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils.timezone import make_aware

from paymentio.choices import PaymentInformationStatusChoices

from subscriptionio.choices import (
    SubscriptionInvoiceLineTypeChoices,
    SubscriptionInvoiceStatusChoices,
)
from subscriptionio.models import (
    CompanySubscription,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
)
from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.credit_service import CreditService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.lifecycle_service import LifecycleService
from subscriptionio.services.plan_change_service import PlanChangeService
from subscriptionio.services.usage_service import UsageService


class SubscriptionBillingService:
    STRIPE_STATUS_MAP = {
        "draft": SubscriptionInvoiceStatusChoices.DRAFT,
        "open": SubscriptionInvoiceStatusChoices.OPEN,
        "paid": SubscriptionInvoiceStatusChoices.PAID,
        "uncollectible": SubscriptionInvoiceStatusChoices.FAILED,
        "void": SubscriptionInvoiceStatusChoices.VOID,
    }

    @classmethod
    def _as_aware_datetime(cls, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else make_aware(value)
        return make_aware(datetime.fromtimestamp(value))

    @classmethod
    def sync_stripe_subscription_period(
        cls, company_subscription: CompanySubscription, stripe_subscription
    ):
        period_start = cls._as_aware_datetime(
            getattr(stripe_subscription, "current_period_start", None)
            or stripe_subscription.get("current_period_start")
        )
        period_end = cls._as_aware_datetime(
            getattr(stripe_subscription, "current_period_end", None)
            or stripe_subscription.get("current_period_end")
        )

        update_fields = ["updated_at"]
        if period_start:
            company_subscription.current_period_start = period_start
            company_subscription.start_date = period_start
            update_fields.extend(["current_period_start", "start_date"])
        if period_end:
            company_subscription.current_period_end = period_end
            company_subscription.renew_date = period_end
            update_fields.extend(["current_period_end", "renew_date"])

        if len(update_fields) > 1:
            company_subscription.save(update_fields=update_fields)
            EntitlementService.invalidate(company_subscription.company_id)

    @classmethod
    def _map_stripe_line_type(cls, stripe_line: dict) -> str:
        description = (stripe_line.get("description") or "").lower()
        if "discount" in description or stripe_line.get("amount", 0) < 0:
            return SubscriptionInvoiceLineTypeChoices.DISCOUNT
        if "tax" in description:
            return SubscriptionInvoiceLineTypeChoices.TAX
        if "add-on" in description or "addon" in description:
            return SubscriptionInvoiceLineTypeChoices.ADDON
        if "overage" in description or "employee" in description:
            return SubscriptionInvoiceLineTypeChoices.OVERAGE
        return SubscriptionInvoiceLineTypeChoices.BASE

    @classmethod
    @transaction.atomic
    def upsert_invoice_from_stripe(
        cls,
        *,
        company_subscription: CompanySubscription,
        stripe_invoice: dict,
        payment_information=None,
    ) -> SubscriptionInvoice:
        stripe_invoice_id = stripe_invoice.get("id")
        invoice, _ = SubscriptionInvoice.objects.get_or_create(
            stripe_invoice_id=stripe_invoice_id,
            defaults={
                "company": company_subscription.company,
                "company_subscription": company_subscription,
                "subscription_price": company_subscription.subscription_price,
                "payment_information": payment_information,
            },
        )

        status = cls.STRIPE_STATUS_MAP.get(
            stripe_invoice.get("status"),
            SubscriptionInvoiceStatusChoices.OPEN,
        )
        if payment_information and (
            payment_information.status == PaymentInformationStatusChoices.SUCCEEDED
            or stripe_invoice.get("paid")
        ):
            status = SubscriptionInvoiceStatusChoices.PAID

        period = (stripe_invoice.get("lines") or {}).get("data") or []
        period_start = None
        period_end = None
        if period:
            period_data = period[0].get("period") or {}
            period_start = cls._as_aware_datetime(period_data.get("start"))
            period_end = cls._as_aware_datetime(period_data.get("end"))

        invoice.status = status
        invoice.currency = (stripe_invoice.get("currency") or "usd").upper()
        invoice.subtotal = Decimal(stripe_invoice.get("subtotal", 0)) / Decimal("100")
        discount_amounts = stripe_invoice.get("total_discount_amounts") or []
        invoice.discount_total = sum(
            Decimal(item.get("amount", 0)) for item in discount_amounts
        ) / Decimal("100")
        invoice.tax_total = Decimal(stripe_invoice.get("tax", 0) or 0) / Decimal("100")
        invoice.total = Decimal(stripe_invoice.get("amount_paid", 0) or stripe_invoice.get("total", 0)) / Decimal("100")
        invoice.period_start = period_start
        invoice.period_end = period_end
        invoice.hosted_invoice_url = stripe_invoice.get("hosted_invoice_url")
        invoice.billing_reason = stripe_invoice.get("billing_reason")
        invoice.payment_information = payment_information
        invoice.company_subscription = company_subscription
        invoice.subscription_price = company_subscription.subscription_price
        invoice.save()

        invoice.lines.all().delete()
        for stripe_line in period:
            amount = Decimal(stripe_line.get("amount", 0)) / Decimal("100")
            quantity = Decimal(stripe_line.get("quantity", 1) or 1)
            unit_amount = amount / quantity if quantity else amount
            SubscriptionInvoiceLine.objects.create(
                invoice=invoice,
                line_type=cls._map_stripe_line_type(stripe_line),
                description=stripe_line.get("description") or "Subscription charge",
                quantity=quantity,
                unit_amount=unit_amount,
                amount=amount,
                metadata={"stripe_line_id": stripe_line.get("id")},
            )

        return invoice

    @classmethod
    def get_current_subscription_payload(cls, company) -> dict:
        company_subscription = EntitlementService.get_company_subscription(company)
        usage = UsageService.get_company_usage(company)
        entitlements = EntitlementService.get_entitlements(company)

        if not company_subscription:
            return {
                "has_subscription": False,
                "status": None,
                "usage": usage,
                "limits": entitlements.get("limits", {}),
                "plan": None,
                "billing_period": None,
                "preview": None,
            }

        subscription_price = company_subscription.subscription_price
        subscription = subscription_price.subscription
        preview = BillingPreviewService.preview(
            company,
            subscription_price=subscription_price,
        )
        from subscriptionio.services.addon_service import AddOnService

        addons = AddOnService.list_for_company(company)
        credit_balance = CreditService.get_available_balance(company)
        scheduled_change = PlanChangeService.get_scheduled_change(company)

        return {
            "has_subscription": True,
            "status": company_subscription.status,
            "usage": usage,
            "limits": entitlements.get("limits", {}),
            "available_credit_balance": str(credit_balance.quantize(Decimal("0.01"))),
            "plan": {
                "uid": str(subscription.uid),
                "title": subscription.title,
                "price_uid": str(subscription_price.uid),
                "billing_frequency": subscription_price.billing_frequency,
                "currency": subscription.currency,
                "plan_version": entitlements.get("plan_version"),
            },
            "billing_period": {
                "start": company_subscription.current_period_start
                or company_subscription.start_date,
                "end": company_subscription.current_period_end
                or company_subscription.renew_date,
                "stripe_subscription_id": company_subscription.stripe_subscription_id,
            },
            "preview": cls._serialize_preview(preview) if preview else None,
            "addons": addons,
            "scheduled_plan_change": scheduled_change,
            "lifecycle": LifecycleService.get_lifecycle_state(company),
        }

    @classmethod
    def _serialize_preview(cls, preview) -> dict:
        return {
            "subscription_price_uid": preview.subscription_price_uid,
            "plan_title": preview.plan_title,
            "billing_frequency": preview.billing_frequency,
            "currency": preview.currency,
            "usage": preview.usage,
            "limits": preview.limits,
            "subtotal": str(preview.subtotal),
            "discount_total": str(preview.discount_total),
            "overage_total": str(preview.overage_total),
            "addon_total": str(getattr(preview, "addon_total", 0)),
            "credit_total": str(getattr(preview, "credit_total", 0)),
            "available_credit_balance": str(
                getattr(preview, "available_credit_balance", 0)
            ),
            "proration_total": str(getattr(preview, "proration_total", 0)),
            "tax_total": str(preview.tax_total),
            "total": str(preview.total),
            "lines": [
                {
                    "line_type": line.line_type,
                    "description": line.description,
                    "quantity": str(line.quantity),
                    "unit_amount": str(line.unit_amount),
                    "amount": str(line.amount),
                    "metadata": line.metadata,
                }
                for line in preview.lines
            ],
        }
