from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q

from subscriptionio.choices import LimitMetricChoices
from subscriptionio.models import SubscriptionBillableMetric


DEFAULT_METRICS = [
    {
        "code": LimitMetricChoices.EMPLOYEE,
        "title": "Active Employees",
        "unit_label": "employee",
        "default_enforcement_mode": "AUTO_OVERAGE",
        "default_overage_unit_price": "6.000",
        "display_order": 1,
    },
    {
        "code": LimitMetricChoices.USER,
        "title": "Login Users",
        "unit_label": "user",
        "default_enforcement_mode": "SOFT_WARNING",
        "default_overage_unit_price": "9.000",
        "display_order": 2,
    },
    {
        "code": LimitMetricChoices.BRANCH,
        "title": "Branches",
        "unit_label": "branch",
        "default_enforcement_mode": "HARD_BLOCK",
        "default_overage_unit_price": "0",
        "display_order": 3,
    },
    {
        "code": LimitMetricChoices.PAYROLL_RUN,
        "title": "Payroll Runs",
        "unit_label": "run",
        "default_enforcement_mode": "AUTO_OVERAGE",
        "default_overage_unit_price": "2.000",
        "display_order": 4,
    },
    {
        "code": LimitMetricChoices.STORAGE,
        "title": "Storage",
        "unit_label": "GB",
        "default_enforcement_mode": "SOFT_WARNING",
        "default_overage_unit_price": "15.000",
        "display_order": 5,
    },
    {
        "code": LimitMetricChoices.AI_CREDIT,
        "title": "AI Credits",
        "unit_label": "credit",
        "default_enforcement_mode": "GRACE_OVERAGE",
        "default_overage_unit_price": "25.000",
        "display_order": 6,
    },
]


class AdminMetricService:
    @classmethod
    def ensure_defaults(cls):
        for item in DEFAULT_METRICS:
            SubscriptionBillableMetric.objects.get_or_create(
                code=item["code"],
                defaults={
                    "title": item["title"],
                    "unit_label": item["unit_label"],
                    "default_enforcement_mode": item["default_enforcement_mode"],
                    "default_overage_unit_price": item["default_overage_unit_price"],
                    "display_order": item["display_order"],
                },
            )

    @classmethod
    def _serialize_metric(cls, metric: SubscriptionBillableMetric) -> dict[str, Any]:
        return {
            "uid": str(metric.uid),
            "code": metric.code,
            "title": metric.title,
            "unit_label": metric.unit_label,
            "description": metric.description,
            "default_enforcement_mode": metric.default_enforcement_mode,
            "default_overage_unit_price": str(metric.default_overage_unit_price),
            "display_order": metric.display_order,
            "is_active": metric.is_active,
            "created_at": metric.created_at,
            "updated_at": metric.updated_at,
        }

    @classmethod
    def get_metrics_queryset(cls, *, include_inactive: bool = False):
        cls.ensure_defaults()
        queryset = SubscriptionBillableMetric.objects.all()
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("display_order", "code")

    @classmethod
    def serialize_metrics(cls, metrics) -> list[dict[str, Any]]:
        return [cls._serialize_metric(item) for item in metrics]

    @classmethod
    def list_metrics(cls, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        return cls.serialize_metrics(cls.get_metrics_queryset(include_inactive=include_inactive))

    @classmethod
    def get_metric(cls, metric: SubscriptionBillableMetric) -> dict[str, Any]:
        return cls._serialize_metric(metric)

    @classmethod
    @transaction.atomic
    def create_metric(cls, payload: dict[str, Any]) -> dict[str, Any]:
        code = (payload.get("code") or "").strip().upper()
        if not code:
            raise ValueError("code is required.")
        if SubscriptionBillableMetric.objects.filter(code=code).exists():
            raise ValueError("A metric with this code already exists.")

        metric = SubscriptionBillableMetric.objects.create(
            code=code,
            title=payload.get("title") or code.replace("_", " ").title(),
            unit_label=payload.get("unit_label", ""),
            description=payload.get("description", ""),
            default_enforcement_mode=payload.get("default_enforcement_mode", "SOFT_WARNING"),
            default_overage_unit_price=payload.get("default_overage_unit_price", 0),
            display_order=int(payload.get("display_order", 0)),
            is_active=payload.get("is_active", True),
        )
        return cls.get_metric(metric)

    @classmethod
    @transaction.atomic
    def update_metric(cls, metric: SubscriptionBillableMetric, payload: dict[str, Any]) -> dict[str, Any]:
        field_map = {
            "title": "title",
            "unit_label": "unit_label",
            "description": "description",
            "default_enforcement_mode": "default_enforcement_mode",
            "default_overage_unit_price": "default_overage_unit_price",
            "display_order": "display_order",
            "is_active": "is_active",
        }
        update_fields = ["updated_at"]
        for key, field in field_map.items():
            if key not in payload:
                continue
            setattr(metric, field, payload[key])
            update_fields.append(field)
        metric.save(update_fields=update_fields)
        return cls.get_metric(metric)

    @classmethod
    @transaction.atomic
    def archive_metric(cls, metric: SubscriptionBillableMetric) -> dict[str, str]:
        metric.is_active = False
        metric.save(update_fields=["is_active", "updated_at"])
        return {"status": "archived", "message": "Metric archived."}

    @classmethod
    def list_enforcement_modes(cls) -> list[dict[str, str]]:
        from subscriptionio.choices import LimitEnforcementModeChoices

        descriptions = {
            "HARD_BLOCK": "Block the action when the limit is exceeded.",
            "SOFT_WARNING": "Allow the action but warn the tenant.",
            "AUTO_OVERAGE": "Bill overage automatically when usage exceeds included quantity.",
            "MANUAL_APPROVAL": "Require admin approval before overage is allowed.",
            "GRACE_OVERAGE": "Allow temporary grace usage before overage billing applies.",
        }
        return [
            {
                "code": choice.value,
                "label": choice.label,
                "description": descriptions.get(choice.value, ""),
            }
            for choice in LimitEnforcementModeChoices
        ]
