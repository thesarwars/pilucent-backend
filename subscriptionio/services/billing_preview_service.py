from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from common.choices import DiscountKind

from subscriptionio.choices import LimitMetricChoices
from subscriptionio.choices import PlanVersionStatusChoices
from subscriptionio.models import PlanLimit, PlanVersion, SubscriptionPrice
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.credit_service import CreditService
from subscriptionio.services.enterprise_pricing_service import EnterprisePricingService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.proration_service import ProrationService
from subscriptionio.services.usage_service import UsageService


@dataclass
class BillingLineItem:
    line_type: str
    description: str
    quantity: Decimal
    unit_amount: Decimal
    amount: Decimal
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BillingPreviewResult:
    subscription_price_uid: str | None
    plan_title: str | None
    billing_frequency: str | None
    currency: str
    usage: dict[str, int]
    limits: dict[str, Any]
    lines: list[BillingLineItem]
    subtotal: Decimal
    discount_total: Decimal
    overage_total: Decimal
    addon_total: Decimal
    credit_total: Decimal
    available_credit_balance: Decimal
    proration_total: Decimal
    tax_total: Decimal
    total: Decimal


class BillingPreviewService:
    @classmethod
    def _resolve_subscription_price(
        cls,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
    ):
        if subscription_price:
            return subscription_price

        if subscription_price_slug:
            return SubscriptionPrice.objects.filter(slug=subscription_price_slug).first()

        if plan_title and billing_frequency:
            return SubscriptionPrice.objects.filter(
                subscription__title=plan_title,
                billing_frequency=billing_frequency,
            ).first()

        return None

    @classmethod
    def _apply_price_discount(cls, subscription_price) -> tuple[Decimal, Decimal]:
        base_amount = Decimal(subscription_price.price or 0)
        discount_value = Decimal(subscription_price.discount or 0)
        if discount_value <= 0:
            return base_amount, Decimal("0")

        if subscription_price.discount_kind == DiscountKind.PERCENTAGE:
            discount_amount = (base_amount * discount_value) / Decimal("100")
        else:
            discount_amount = discount_value

        discount_amount = min(discount_amount, base_amount)
        return base_amount, discount_amount

    @classmethod
    def _get_target_plan_version(cls, subscription, company_subscription):
        if (
            company_subscription
            and company_subscription.subscription_price.subscription_id
            == subscription.id
        ):
            return EntitlementService._ensure_plan_version(company_subscription)

        return (
            PlanVersion.objects.filter(
                subscription=subscription,
                status=PlanVersionStatusChoices.PUBLISHED,
            )
            .order_by("-version_no")
            .first()
        )

    @classmethod
    def _get_plan_limit(
        cls, plan_version, metric_code: str
    ) -> PlanLimit | None:
        if not plan_version:
            return None
        return plan_version.limits.filter(metric_code=metric_code).first()

    @classmethod
    def _build_overage_line(
        cls,
        *,
        metric_code: str,
        label: str,
        usage_count: int,
        plan_limit: PlanLimit | None,
        fallback_included: int = 0,
    ) -> BillingLineItem | None:
        included = (
            plan_limit.included_quantity
            if plan_limit
            else fallback_included
        )
        unit_price = (
            Decimal(plan_limit.overage_unit_price or 0)
            if plan_limit
            else Decimal("0")
        )
        overage_units = max(0, usage_count - included)
        if overage_units <= 0 or unit_price <= 0:
            return None

        amount = Decimal(overage_units) * unit_price
        return BillingLineItem(
            line_type="OVERAGE",
            description=f"{label} overage ({overage_units} x {unit_price})",
            quantity=Decimal(overage_units),
            unit_amount=unit_price,
            amount=amount,
            metadata={
                "metric_code": metric_code,
                "included_quantity": included,
                "usage_count": usage_count,
            },
        )

    @classmethod
    def preview(
        cls,
        company,
        *,
        subscription_price=None,
        subscription_price_slug=None,
        plan_title=None,
        billing_frequency=None,
        employee_count: int | None = None,
        user_count: int | None = None,
        tax_rate: Decimal | None = None,
        coupon_code: str | None = None,
        currency: str | None = None,
        addon_uids: list | None = None,
        addon_codes: list | None = None,
        addon_quantities: dict | None = None,
        apply_credits: bool = True,
    ) -> BillingPreviewResult | None:
        resolved = EnterprisePricingService.resolve_pricing(
            company,
            subscription_price=subscription_price,
            subscription_price_slug=subscription_price_slug,
            plan_title=plan_title,
            billing_frequency=billing_frequency,
            currency=currency,
        )
        if not resolved:
            return None

        subscription_price = resolved.subscription_price
        subscription = subscription_price.subscription
        company_subscription = EntitlementService.get_company_subscription(company)
        usage = UsageService.get_company_usage(company)

        if employee_count is not None:
            usage[LimitMetricChoices.EMPLOYEE] = employee_count
        if user_count is not None:
            usage[LimitMetricChoices.USER] = user_count

        plan_version = cls._get_target_plan_version(subscription, company_subscription)
        if resolved.plan_version_id and plan_version is None:
            plan_version = PlanVersion.objects.filter(id=resolved.plan_version_id).first()
        limits = {}
        if plan_version:
            for plan_limit in plan_version.limits.all():
                limits[plan_limit.metric_code] = {
                    "included_quantity": plan_limit.included_quantity,
                    "overage_unit_price": str(plan_limit.overage_unit_price),
                    "enforcement_mode": plan_limit.enforcement_mode,
                }
        else:
            limits = EntitlementService.get_limits(company)

        if resolved.employee_limit_override is not None:
            limits[LimitMetricChoices.EMPLOYEE] = {
                "included_quantity": resolved.employee_limit_override,
                "enforcement_mode": limits.get(LimitMetricChoices.EMPLOYEE, {}).get(
                    "enforcement_mode"
                ),
            }
        if resolved.user_limit_override is not None:
            limits[LimitMetricChoices.USER] = {
                "included_quantity": resolved.user_limit_override,
                "enforcement_mode": limits.get(LimitMetricChoices.USER, {}).get(
                    "enforcement_mode"
                ),
            }

        base_amount = resolved.base_price
        discount_amount = Decimal("0")
        if resolved.discount > 0:
            if resolved.discount_kind == DiscountKind.PERCENTAGE:
                discount_amount = (base_amount * resolved.discount) / Decimal("100")
            else:
                discount_amount = resolved.discount
            discount_amount = min(discount_amount, base_amount)
        coupon_discount = Decimal("0")
        coupon_result = None
        if coupon_code:
            coupon_result = CouponService.validate(
                coupon_code,
                company=company,
                subscription_price=subscription_price,
                existing_plan_discount=discount_amount,
            )
            if not coupon_result.valid:
                raise ValueError(coupon_result.message)

        lines: list[BillingLineItem] = [
            BillingLineItem(
                line_type="BASE",
                description=f"{subscription.title} ({subscription_price.billing_frequency})",
                quantity=Decimal("1"),
                unit_amount=base_amount,
                amount=base_amount,
            )
        ]

        if discount_amount > 0:
            lines.append(
                BillingLineItem(
                    line_type="DISCOUNT",
                    description="Plan discount",
                    quantity=Decimal("1"),
                    unit_amount=-discount_amount,
                    amount=-discount_amount,
                    metadata={
                        "discount_kind": resolved.discount_kind,
                        "contract_applied": resolved.contract_applied,
                    },
                )
            )

        employee_limit = cls._get_plan_limit(
            plan_version, LimitMetricChoices.EMPLOYEE
        )
        employee_overage = cls._build_overage_line(
            metric_code=LimitMetricChoices.EMPLOYEE,
            label="Employee",
            usage_count=usage[LimitMetricChoices.EMPLOYEE],
            plan_limit=employee_limit,
            fallback_included=subscription.employee_limit,
        )
        if employee_overage:
            lines.append(employee_overage)

        user_limit = cls._get_plan_limit(plan_version, LimitMetricChoices.USER)
        user_overage = cls._build_overage_line(
            metric_code=LimitMetricChoices.USER,
            label="User",
            usage_count=usage[LimitMetricChoices.USER],
            plan_limit=user_limit,
            fallback_included=subscription.user_limit,
        )
        if user_overage:
            lines.append(user_overage)

        addon_total = Decimal("0")
        if addon_uids or addon_codes:
            from subscriptionio.services.addon_service import AddOnService

            resolved_addons = AddOnService.resolve_addons(
                company,
                addon_uids=addon_uids,
                addon_codes=addon_codes,
                quantities=addon_quantities,
                target_subscription=subscription,
                target_plan_version=plan_version,
            )
            addon_lines, addon_total = AddOnService.build_preview_lines(resolved_addons)
            lines.extend(addon_lines)

        proration_total = Decimal("0")
        if (
            company_subscription
            and company_subscription.subscription_price_id != subscription_price.id
        ):
            proration = ProrationService.calculate_plan_change_proration(
                company,
                target_subscription_price=subscription_price,
            )
            if proration.get("applies"):
                proration_total = Decimal(proration["proration_amount"])
                if proration_total != 0:
                    lines.append(
                        BillingLineItem(
                            line_type="PRORATION",
                            description="Plan change proration",
                            quantity=Decimal("1"),
                            unit_amount=proration_total,
                            amount=proration_total,
                            metadata={
                                "remaining_fraction": proration["remaining_fraction"],
                                "current_period_amount": proration["current_period_amount"],
                                "target_period_amount": proration["target_period_amount"],
                            },
                        )
                    )

        subtotal = base_amount
        overage_total = sum(
            (line.amount for line in lines if line.line_type == "OVERAGE"),
            Decimal("0"),
        )

        if coupon_result and coupon_result.coupon:
            coupon_discount = CouponService.calculate_discount(
                coupon_result.coupon,
                base_amount=base_amount - discount_amount,
                overage_total=overage_total,
            )
            if coupon_discount > 0:
                lines.append(
                    BillingLineItem(
                        line_type="DISCOUNT",
                        description=f"Coupon {coupon_result.coupon.code}",
                        quantity=Decimal("1"),
                        unit_amount=-coupon_discount,
                        amount=-coupon_discount,
                        metadata={"coupon_code": coupon_result.coupon.code},
                    )
                )

        taxable_base = (
            subtotal
            - discount_amount
            - coupon_discount
            + overage_total
            + addon_total
            + proration_total
        )
        tax_total = Decimal("0")
        if tax_rate and tax_rate > 0:
            tax_total = (taxable_base * tax_rate) / Decimal("100")
            lines.append(
                BillingLineItem(
                    line_type="TAX",
                    description=f"Tax ({tax_rate}%)",
                    quantity=Decimal("1"),
                    unit_amount=tax_total,
                    amount=tax_total,
                )
            )

        amount_before_credits = taxable_base + tax_total
        available_credit_balance = CreditService.get_available_balance(company)
        credit_total = Decimal("0")
        if apply_credits and amount_before_credits > 0 and available_credit_balance > 0:
            credit_application = CreditService.calculate_application(
                company, amount_before_credits
            )
            credit_total = credit_application["credit_total"]
            if credit_total > 0:
                lines.append(
                    BillingLineItem(
                        line_type="CREDIT",
                        description="Account credit",
                        quantity=Decimal("1"),
                        unit_amount=-credit_total,
                        amount=-credit_total,
                        metadata={
                            "allocations": credit_application["allocations"],
                        },
                    )
                )

        total = max(Decimal("0"), amount_before_credits - credit_total)

        return BillingPreviewResult(
            subscription_price_uid=str(subscription_price.uid),
            plan_title=subscription.title,
            billing_frequency=subscription_price.billing_frequency,
            currency=resolved.currency,
            usage=usage,
            limits=limits,
            lines=lines,
            subtotal=subtotal,
            discount_total=discount_amount + coupon_discount,
            overage_total=overage_total,
            addon_total=addon_total,
            credit_total=credit_total,
            available_credit_balance=available_credit_balance,
            proration_total=proration_total,
            tax_total=tax_total,
            total=total,
        )
