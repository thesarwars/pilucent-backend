"""Fire every recurring template that is due.

Runnable today against the existing docker-compose, with no new infrastructure:

    docker compose exec app python manage.py run_recurring

Schedule it from host cron (once a day is enough for daily-or-slower templates;
the catch-up window means a missed run is picked up on the next one). The same
work is also exposed as ``recurringio.tasks.run_recurring_templates`` for when a
celery beat process exists.
"""

from django.core.management.base import BaseCommand

from companyio.models import Company
from recurringio.services import runner


class Command(BaseCommand):
    help = "Generate documents for all due recurring templates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help="Limit the run to one company uid (default: every company).",
        )
        parser.add_argument(
            "--catch-up-days",
            type=int,
            default=runner.DEFAULT_CATCH_UP_DAYS,
            help=(
                "How far back a missed occurrence is still fired. Older ones are "
                f"recorded as SKIPPED. Default {runner.DEFAULT_CATCH_UP_DAYS}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what is due without generating anything.",
        )

    def handle(self, *args, **options):
        company = None
        if options["company"]:
            company = Company.objects.filter(uid=options["company"]).first()
            if company is None:
                self.stderr.write(f"No company with uid {options['company']!r}.")
                return

        if options["dry_run"]:
            due = runner.due_templates(company)
            self.stdout.write(f"{due.count()} template(s) with a next run date:")
            for template in due:
                self.stdout.write(
                    f"  {template.uid}  {template.txn_type:<15} "
                    f"next={template.next_run_date}  {template.name}"
                )
            return

        summary = runner.run_due(company, catch_up_days=options["catch_up_days"])
        self.stdout.write(self.style.SUCCESS(f"Recurring run complete: {summary}"))
