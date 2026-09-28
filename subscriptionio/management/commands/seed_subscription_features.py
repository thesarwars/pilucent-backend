from django.core.management.base import BaseCommand
from django.db import transaction

from subscriptionio.feature_catalog import FEATURE_CATALOG
from subscriptionio.models import Subscription, SubscriptionFeature, SubscriptionModule
from subscriptionio.services.plan_version_service import PlanVersionService


class Command(BaseCommand):
    help = "Seed subscription module/feature catalogue and initial plan versions."

    @transaction.atomic
    def handle(self, *args, **options):
        modules_created = 0
        features_created = 0

        for group in FEATURE_CATALOG:
            module_data = group["module"]
            module, created = SubscriptionModule.objects.update_or_create(
                code=module_data["code"],
                defaults={
                    "title": module_data["name"],
                    "display_order": module_data.get("display_order", 0),
                    "is_active": True,
                },
            )
            if created:
                modules_created += 1

            for feature_data in group["features"]:
                _, created = SubscriptionFeature.objects.update_or_create(
                    code=feature_data["code"],
                    defaults={
                        "module": module,
                        "title": feature_data["name"],
                        "legacy_field": feature_data.get("legacy_field"),
                        "permission_codenames": feature_data.get(
                            "permission_codenames", []
                        ),
                        "menu_key": feature_data.get("menu_key"),
                        "is_active": True,
                    },
                )
                if created:
                    features_created += 1

        versions_created = 0
        for subscription in Subscription.objects.all():
            if not subscription.plan_versions.exists():
                PlanVersionService.ensure_initial_version(subscription)
                versions_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded modules (+{modules_created}), features (+{features_created}), "
                f"plan versions (+{versions_created})."
            )
        )
