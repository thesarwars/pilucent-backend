"""Nightly economic-nexus recompute.

Recomputes every state's status for each company from its recorded sales. This is
the v1 source of truth (no incremental sale-event path yet). Run from the prod
host crontab, e.g. nightly off-peak:

    python manage.py recompute_economic_nexus [--company <uid>]

Connections are closed per company because the RDS instance has a small
connection ceiling; a failure in one company is logged and does not abort the run.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from companyio.models import Company
from nexusio.services.recompute import recompute_company

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recompute economic-nexus status for all companies (or one)."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Limit to a single company uid.")

    def handle(self, *args, **options):
        companies = Company.objects.all()
        if options.get("company"):
            companies = companies.filter(uid=options["company"])

        done = failed = 0
        for company in companies.iterator():
            close_old_connections()
            try:
                result = recompute_company(company)
                done += 1
                unattributed = result["unattributed"]["gross"]
                if unattributed:
                    logger.info(
                        "nexus: company %s has %s unattributed sales (no US state)",
                        company.uid,
                        unattributed,
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "nexus: recompute failed for company %s", company.uid
                )

        self.stdout.write(
            self.style.SUCCESS(f"Nexus recompute: {done} companies, {failed} failed.")
        )
