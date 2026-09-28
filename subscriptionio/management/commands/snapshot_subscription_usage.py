from django.core.management.base import BaseCommand

from subscriptionio.services.usage_service import UsageService


class Command(BaseCommand):
    help = "Snapshot current employee/user usage counters for all companies."

    def handle(self, *args, **options):
        count = UsageService.snapshot_all_companies()
        self.stdout.write(
            self.style.SUCCESS(f"Snapshotted usage counters for {count} companies.")
        )
