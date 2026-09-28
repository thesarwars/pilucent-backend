import logging

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)
from datamigrationio.models import DataMigrationImpactLine

logger = logging.getLogger(__name__)


class LocationImpactService:
    """
    Locations have no GL impact (has_gl_impact=False, is_posting_transaction=False).
    This service advances the job status and returns a summary count — no
    DataMigrationImpactLine rows are created.
    """

    @staticmethod
    def generate(job, company) -> dict:
        # Clear any stale impact lines from a previous run
        DataMigrationImpactLine.objects.filter(job=job).delete()

        importable_statuses = [
            MigrationRowStatusChoices.READY,
            MigrationRowStatusChoices.WARNING,
        ]
        total_transactions = job.rows.filter(status__in=importable_statuses).count()

        job.status = MigrationStatusChoices.IMPACT_REVIEWED
        job.current_step = MigrationStepChoices.CONFIRM_IMPORT
        job.save(update_fields=["status", "current_step", "updated_at"])

        logger.info(
            "[LOCATION IMPACT] job_uid=%s | importable locations=%d",
            job.uid,
            total_transactions,
        )

        return {
            "job_uid": str(job.uid),
            "impact_level": "None",
            "total_transactions": total_transactions,
            "total_value": 0,
            "affected_reports": [],
            "lines": [],
        }
