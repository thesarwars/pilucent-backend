from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.timezone import make_aware, now

from accounts.models import User
from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    LimitMetricChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
    SubscriptionInvoiceLineTypeChoices,
    SubscriptionInvoiceStatusChoices,
)
from subscriptionio.models import (
    CompanySubscription,
    SubscriptionEvent,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
    UsageCounter,
)
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.plan_version_service import PlanVersionService
from subscriptionio.services.usage_service import UsageService


class Command(BaseCommand):
    help = (
        "Populate subscription v2 demo history (invoices, events, usage) "
        "for the last N months on a company account."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="nazirul@yahoo.com",
            help="Account email (falls back to partial match if exact not found).",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=3,
            help="Number of past billing months to seed (default: 3).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace existing seeded invoices/events for the target periods.",
        )

    def _resolve_user(self, email: str) -> User:
        user = User.objects.filter(email__iexact=email).first()
        if user:
            return user

        local_part = email.split("@", 1)[0]
        user = User.objects.filter(email__icontains=local_part).order_by("id").first()
        if user:
            self.stdout.write(
                self.style.WARNING(
                    f"Exact email '{email}' not found; using '{user.email}'."
                )
            )
            return user

        raise CommandError(f"No user found for email '{email}'.")

    def _ensure_aware(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value
        return make_aware(value)

    def _month_bounds(self, anchor: datetime, months_ago: int):
        if anchor.tzinfo is not None:
            anchor = anchor.replace(tzinfo=None)
        month_start = (anchor.replace(day=1) - relativedelta(months=months_ago)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        last_day = monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(
            day=last_day, hour=23, minute=59, second=59, microsecond=0
        )
        return month_start, month_end

    def _stamp(self, instance, created_at: datetime):
        type(instance).objects.filter(pk=instance.pk).update(
            created_at=created_at,
            updated_at=created_at,
        )

    def _ensure_subscription(self, company, company_subscription: CompanySubscription):
        subscription = company_subscription.subscription_price.subscription
        if not company_subscription.plan_version_id:
            plan_version = PlanVersionService.ensure_initial_version(subscription)
            company_subscription.plan_version = plan_version
            company_subscription.save(update_fields=["plan_version", "updated_at"])

        if company_subscription.status not in {
            CompanySubscriptionStatusChoices.ACTIVE,
            CompanySubscriptionStatusChoices.TRIALING,
        }:
            company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
            company_subscription.save(update_fields=["status", "updated_at"])

        current_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_end = (
            current_start + relativedelta(months=1) - timedelta(seconds=1)
        )
        company_subscription.current_period_start = current_start
        company_subscription.current_period_end = current_end
        company_subscription.start_date = current_start
        company_subscription.renew_date = current_end
        company_subscription.cancel_at_period_end = False
        company_subscription.canceled_at = None
        company_subscription.dunning_started_at = None
        company_subscription.grace_ends_at = None
        company_subscription.suspend_ends_at = None
        company_subscription.failed_payment_count = 0
        company_subscription.save(
            update_fields=[
                "current_period_start",
                "current_period_end",
                "start_date",
                "renew_date",
                "cancel_at_period_end",
                "canceled_at",
                "dunning_started_at",
                "grace_ends_at",
                "suspend_ends_at",
                "failed_payment_count",
                "updated_at",
            ]
        )
        EntitlementService.invalidate(company.id)

    def _create_invoice(
        self,
        *,
        company,
        company_subscription,
        period_start: datetime,
        period_end: datetime,
        base_amount: Decimal,
        overage_amount: Decimal,
        month_index: int,
    ) -> SubscriptionInvoice:
        subtotal = base_amount + overage_amount
        tax_total = (subtotal * Decimal("0.085")).quantize(Decimal("0.001"))
        total = subtotal + tax_total
        invoice = SubscriptionInvoice.objects.create(
            company=company,
            company_subscription=company_subscription,
            subscription_price=company_subscription.subscription_price,
            status=SubscriptionInvoiceStatusChoices.PAID,
            currency=company_subscription.subscription_price.currency,
            subtotal=subtotal,
            discount_total=Decimal("0"),
            tax_total=tax_total,
            total=total,
            period_start=period_start,
            period_end=period_end,
            hosted_invoice_url=f"https://invoice.stripe.com/demo/{company_subscription.uid}/{month_index}",
            billing_reason="subscription_cycle",
            stripe_invoice_id=f"in_demo_{company.id}_{period_start.strftime('%Y%m')}",
        )

        SubscriptionInvoiceLine.objects.create(
            invoice=invoice,
            line_type=SubscriptionInvoiceLineTypeChoices.BASE,
            description=f"{company_subscription.subscription_price.subscription.title} — base plan",
            quantity=Decimal("1"),
            unit_amount=base_amount,
            amount=base_amount,
        )
        if overage_amount > 0:
            SubscriptionInvoiceLine.objects.create(
                invoice=invoice,
                line_type=SubscriptionInvoiceLineTypeChoices.OVERAGE,
                description="Employee overage",
                quantity=Decimal(str(2 + month_index)),
                unit_amount=Decimal("6"),
                amount=overage_amount,
            )
        SubscriptionInvoiceLine.objects.create(
            invoice=invoice,
            line_type=SubscriptionInvoiceLineTypeChoices.TAX,
            description="Sales tax (8.5%)",
            quantity=Decimal("1"),
            unit_amount=tax_total,
            amount=tax_total,
        )

        self._stamp(invoice, period_end)
        return invoice

    def _create_events(
        self,
        *,
        company,
        company_subscription,
        anchor: datetime,
        months: int,
    ) -> int:
        created = 0
        checkout_at = anchor - relativedelta(months=months)
        checkout_at = self._ensure_aware(checkout_at)

        if not SubscriptionEvent.objects.filter(
            company=company,
            event_type=SubscriptionEventTypeChoices.CHECKOUT_COMPLETED,
        ).exists():
            event = SubscriptionEvent.objects.create(
                company=company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.CHECKOUT_COMPLETED,
                previous_status=CompanySubscriptionStatusChoices.PENDING,
                new_status=CompanySubscriptionStatusChoices.ACTIVE,
                source=SubscriptionEventSourceChoices.API,
                payload={"seeded": True},
                title="Checkout Completed",
            )
            self._stamp(event, checkout_at)
            created += 1

        for month_index in range(months, 0, -1):
            event_at, _ = self._month_bounds(anchor, month_index)
            event_at = self._ensure_aware(event_at)
            stripe_id = f"evt_demo_payment_{company.id}_{event_at.strftime('%Y%m')}"
            if SubscriptionEvent.objects.filter(stripe_event_id=stripe_id).exists():
                continue
            event = SubscriptionEvent.objects.create(
                company=company,
                company_subscription=company_subscription,
                event_type=SubscriptionEventTypeChoices.PAYMENT_RECOVERED,
                previous_status=CompanySubscriptionStatusChoices.ACTIVE,
                new_status=CompanySubscriptionStatusChoices.ACTIVE,
                source=SubscriptionEventSourceChoices.WEBHOOK,
                payload={
                    "seeded": True,
                    "invoice_period": event_at.strftime("%Y-%m"),
                },
                stripe_event_id=stripe_id,
                title="Payment Recovered",
            )
            self._stamp(event, event_at + timedelta(days=2))
            created += 1

        return created

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"]
        months = max(1, options["months"])
        force = options["force"]

        user = self._resolve_user(email)
        company = user.get_active_company()
        if not company:
            raise CommandError(f"User '{user.email}' has no active company.")

        company_subscription = EntitlementService.get_company_subscription(company)
        if not company_subscription:
            raise CommandError(
                f"Company '{company.id}' has no CompanySubscription. "
                "Create a subscription first."
            )

        self._ensure_subscription(company, company_subscription)

        anchor = now()
        base_amount = company_subscription.subscription_price.price
        if base_amount <= 0:
            base_amount = Decimal("79.000")

        invoices_created = 0
        for month_index in range(months, 0, -1):
            period_start, period_end = self._month_bounds(anchor, month_index)
            stripe_invoice_id = (
                f"in_demo_{company.id}_{period_start.strftime('%Y%m')}"
            )
            existing = SubscriptionInvoice.objects.filter(
                stripe_invoice_id=stripe_invoice_id
            ).first()
            if existing and not force:
                continue
            if existing and force:
                existing.lines.all().delete()
                existing.delete()

            overage_amount = Decimal(str(6 * (2 + (months - month_index))))
            self._create_invoice(
                company=company,
                company_subscription=company_subscription,
                period_start=self._ensure_aware(period_start),
                period_end=self._ensure_aware(period_end),
                base_amount=base_amount,
                overage_amount=overage_amount,
                month_index=month_index,
            )
            invoices_created += 1

        if force:
            SubscriptionEvent.objects.filter(
                company=company, payload__seeded=True
            ).delete()

        events_created = self._create_events(
            company=company,
            company_subscription=company_subscription,
            anchor=anchor,
            months=months,
        )

        usage = UsageService.snapshot_company_usage(company)
        for metric_code, quantity in usage.items():
            UsageCounter.objects.filter(
                company=company, metric_code=metric_code
            ).update(source="seed")

        self.stdout.write(
            self.style.SUCCESS(
                f"Populated subscription v2 history for '{user.email}' "
                f"(company_id={company.id}): "
                f"{invoices_created} invoice(s), {events_created} event(s), "
                f"usage={usage}."
            )
        )
