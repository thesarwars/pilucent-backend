from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.location_validator import LocationValidatorService
from datamigrationio.django_rest.services.location_impact import LocationImpactService
from datamigrationio.django_rest.services.location_rollback import LocationMigrationRollbackService
from datamigrationio.tasks import process_location_migration


COLUMN_ALIAS_MAP = {
    "location name": "title",
    "name": "title",
    "warehouse name": "title",
    "location": "title",
    "short name": "short_name",
    "location code": "short_name",
    "code": "short_name",
    "short code": "short_name",
    "address": "full_address",
    "full address": "full_address",
    "street address": "full_address",
    "kind": "kind",
    "type": "kind",
    "warehouse type": "kind",
    "location type": "kind",
    "remark": "remark",
    "notes": "remark",
    "description": "remark",
    "remarks": "remark",
}

REQUIRED_TARGET_FIELDS = {"title"}


@MigrationHandlerRegistry.register
class LocationsMigrationHandler(BaseMigrationHandler):
    data_type = "locations"
    label = "Locations"
    category = "Settings"
    description = "Import warehouse and location data."
    has_gl_impact = False
    is_posting_transaction = False
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Location Name",
        "Short Name",
        "Address",
        "Kind",
        "Remark",
    ]

    TEMPLATE_SAMPLE_ROW = [
        "Main Warehouse",
        "MAIN-WH",
        "123 Business Ave, Suite 100",
        "TEMPORARY",
        "Primary storage location",
    ]

    @classmethod
    def get_template_headers(cls) -> list:
        return cls.TEMPLATE_HEADERS

    @classmethod
    def get_template_sample_row(cls) -> list:
        return cls.TEMPLATE_SAMPLE_ROW

    @classmethod
    def get_field_aliases(cls) -> dict:
        return COLUMN_ALIAS_MAP

    @classmethod
    def get_target_fields(cls) -> list:
        return sorted(set(COLUMN_ALIAS_MAP.values()))

    @classmethod
    def get_required_target_fields(cls) -> set:
        return REQUIRED_TARGET_FIELDS

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return set()

    @classmethod
    def validate(cls, job, company) -> dict:
        return LocationValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return LocationImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_location_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            print(
                f"[HANDLER] Running location import synchronously (DEBUG mode) "
                f"for job_uid={job.uid}"
            )
            process_location_migration.apply(
                args=[str(job.uid), user.id],
                kwargs={"send_email": send_email},
            )
            message = "Import completed synchronously."

        return {
            "implemented": True,
            "job_uid": str(job.uid),
            "status": job.status,
            "message": message,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:
        return LocationMigrationRollbackService.run(job, user, reason=reason)
