from django.core.management.base import BaseCommand

from subscriptionio.models import PlanMigrationJob
from subscriptionio.services.plan_migration_service import PlanMigrationService


class Command(BaseCommand):
    help = "Execute a subscription plan migration job by UID."

    def add_arguments(self, parser):
        parser.add_argument("job_uid", type=str)

    def handle(self, *args, **options):
        job = PlanMigrationJob.objects.get(uid=options["job_uid"])
        job = PlanMigrationService.execute_job(job)
        self.stdout.write(
            self.style.SUCCESS(
                f"Migration {job.uid} finished with status={job.status} "
                f"migrated={job.migrated_count} failed={job.failed_count} "
                f"skipped={job.skipped_count}"
            )
        )
