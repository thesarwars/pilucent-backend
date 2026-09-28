import logging

from common.django_rest.helpers.crud_logger import crud_log, CrudAction

logger = logging.getLogger(__name__)


class MigrationAuditService:
    """
    Thin wrapper around crud_log() for data migration audit events.
    Uses the existing django-auditlog based system.
    """

    @staticmethod
    def log(job, user, action, details=None):
        """
        Log a migration audit event.

        action: CrudAction constant (e.g. CrudAction.CREATED, CrudAction.UPDATED)
        details: dict with event-specific context
        """
        extra = details or {}
        extra.setdefault("job_uid", str(job.uid))
        extra.setdefault("data_type", job.data_type)
        extra.setdefault("company_id", job.company_id)
        crud_log(logger, action, job, actor=user, extra=extra)
