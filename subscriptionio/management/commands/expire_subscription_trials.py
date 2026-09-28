from django.core.management.base import BaseCommand

from subscriptionio.services.trial_service import TrialService


class Command(BaseCommand):
    help = "Expire company subscriptions whose trial period has ended."

    def handle(self, *args, **options):
        expired_count = TrialService.expire_due_trials()
        self.stdout.write(
            self.style.SUCCESS(f"Expired {expired_count} trial subscription(s).")
        )
