from dataclasses import dataclass
from decimal import Decimal

from django.db import models
from django.utils.timezone import now

from common.choices import DiscountKind

from subscriptionio.choices import SubscriptionContractStatusChoices
from subscriptionio.models import SubscriptionContract, SubscriptionPrice


@dataclass
class ResolvedPricing:
    subscription_price: SubscriptionPrice
    currency: str
    base_price: Decimal
    discount: Decimal
    discount_kind: str
    contract_applied: bool
    contract_uid: str | None = None
    is_manual_billing: bool = False
    employee_limit_override: int | None = None
    user_limit_override: int | None = None
    plan_version_id: int | None = None


class EnterprisePricingService:
    @classmethod
    def get_active_contract(cls, company) -> SubscriptionContract | None:
        if not company:
            return None
        current = now()
        return (
            SubscriptionContract.objects.filter(
                company=company,
                status=SubscriptionContractStatusChoices.ACTIVE,
                contract_start__lte=current,
            )
            .filter(models.Q(contract_end__isnull=True) | models.Q(contract_end__gte=current))
            .select_related(
                "subscription_price__subscription",
                "plan_version",
            )
            .order_by("-contract_start")
            .first()
        )

    @classmethod
    def resolve_subscription_price(
        cls,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        currency: str | None = None,
    ) -> SubscriptionPrice | None:
        if subscription_price:
            return subscription_price

        qs = SubscriptionPrice.objects.filter(is_active=True).select_related(
            "subscription"
        )
        if subscription_price_slug:
            return qs.filter(slug=subscription_price_slug).first()

        if plan_title and billing_frequency:
            filters = {
                "subscription__title": plan_title,
                "billing_frequency": billing_frequency,
            }
            if currency:
                filters["currency"] = currency
            price = qs.filter(**filters).first()
            if price:
                return price
            if currency:
                return qs.filter(
                    subscription__title=plan_title,
                    billing_frequency=billing_frequency,
                    subscription__currency=currency,
                ).first()
        return None

    @classmethod
    def resolve_pricing(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        currency: str | None = None,
    ) -> ResolvedPricing | None:
        contract = cls.get_active_contract(company)

        if contract and contract.subscription_price:
            subscription_price = contract.subscription_price
        else:
            subscription_price = cls.resolve_subscription_price(
                subscription_price=subscription_price,
                subscription_price_slug=subscription_price_slug,
                plan_title=plan_title,
                billing_frequency=billing_frequency,
                currency=currency or (contract.currency if contract else None),
            )

        if not subscription_price:
            return None

        resolved_currency = (
            currency
            or (contract.currency if contract else None)
            or subscription_price.currency
            or subscription_price.subscription.currency
        )
        base_price = Decimal(subscription_price.price or 0)
        discount = Decimal(subscription_price.discount or 0)
        discount_kind = subscription_price.discount_kind

        contract_applied = False
        contract_uid = None
        is_manual_billing = False
        employee_limit_override = None
        user_limit_override = None
        plan_version_id = None

        if contract:
            contract_applied = True
            contract_uid = str(contract.uid)
            is_manual_billing = contract.is_manual_billing
            employee_limit_override = contract.employee_limit_override
            user_limit_override = contract.user_limit_override
            plan_version_id = contract.plan_version_id
            if contract.custom_price is not None:
                base_price = Decimal(contract.custom_price)
            if contract.custom_discount is not None:
                discount = Decimal(contract.custom_discount)
                discount_kind = contract.discount_kind

        return ResolvedPricing(
            subscription_price=subscription_price,
            currency=resolved_currency,
            base_price=base_price,
            discount=discount,
            discount_kind=discount_kind,
            contract_applied=contract_applied,
            contract_uid=contract_uid,
            is_manual_billing=is_manual_billing,
            employee_limit_override=employee_limit_override,
            user_limit_override=user_limit_override,
            plan_version_id=plan_version_id,
        )
