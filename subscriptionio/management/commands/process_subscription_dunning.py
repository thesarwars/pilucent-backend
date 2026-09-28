from django.core.management.base import BaseCommand

from subscriptionio.services.dunning_service import DunningService


class Command(BaseCommand):
    help = "Advance past-due subscriptions through grace, suspended, and expired states."

    def handle(self, *args, **options):
        stats = DunningService.process_dunning()
        self.stdout.write(
            self.style.SUCCESS(
                "Dunning processed: "
                f"grace={stats['grace']} "
                f"suspended={stats['suspended']} "
                f"expired={stats['expired']}"
            )
        )
