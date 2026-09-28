from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now

from subscriptionio.models import SubscriptionCredit


class CreditService:
    @classmethod
    def get_active_credits(cls, company):
        return (
            SubscriptionCredit.objects.filter(
                company=company,
                is_active=True,
                balance__gt=0,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now()))
            .order_by("created_at", "id")
        )

    @classmethod
    def get_available_balance(cls, company) -> Decimal:
        total = cls.get_active_credits(company).aggregate(total=Sum("balance"))["total"]
        return Decimal(total or 0)

    @classmethod
    def calculate_application(
        cls,
        company,
        amount_due: Decimal,
    ) -> dict[str, Any]:
        amount_due = max(Decimal("0"), amount_due)
        available = cls.get_available_balance(company)
        credit_total = min(available, amount_due)

        allocations: list[dict[str, str]] = []
        remaining_to_apply = credit_total
        for credit in cls.get_active_credits(company):
            if remaining_to_apply <= 0:
                break
            applied = min(credit.balance, remaining_to_apply)
            allocations.append(
                {
                    "credit_uid": str(credit.uid),
                    "source": credit.source,
                    "amount": str(applied.quantize(Decimal("0.01"))),
                }
            )
            remaining_to_apply -= applied

        return {
            "available_balance": str(available.quantize(Decimal("0.01"))),
            "credit_total": credit_total,
            "amount_due": max(Decimal("0"), amount_due - credit_total),
            "allocations": allocations,
        }

    @classmethod
    @transaction.atomic
    def apply_credits(
        cls,
        company,
        amount: Decimal,
        *,
        source_ref: str = "",
    ) -> Decimal:
        amount = max(Decimal("0"), amount)
        if amount <= 0:
            return Decimal("0")

        applied_total = Decimal("0")
        remaining = amount
        for credit in cls.get_active_credits(company).select_for_update():
            if remaining <= 0:
                break
            deduction = min(credit.balance, remaining)
            credit.balance -= deduction
            if credit.balance <= 0:
                credit.balance = Decimal("0")
                credit.is_active = False
            update_fields = ["balance", "is_active", "updated_at"]
            if source_ref and not credit.source_ref:
                credit.source_ref = source_ref
                update_fields.append("source_ref")
            credit.save(update_fields=update_fields)
            applied_total += deduction
            remaining -= deduction

        return applied_total
