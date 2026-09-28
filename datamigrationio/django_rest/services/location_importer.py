import logging

from django.db import transaction
from django.utils import timezone

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from wirehouseio.models import Warehouse
from wirehouseio.choicess import WarehouseKindChoices, WarehouseStatusChoices
from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices

logger = logging.getLogger(__name__)


class LocationMigrationImporter:
    """
    Imports each row as a standalone Warehouse record (+ optional Address).
    Mirrors PrivateWeWarehouseListSerializer.create() logic.
    """

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(
            f"[LOCATION IMPORTER] run() started | job_uid={job.uid} "
            f"| importable rows={len(rows)}"
        )

        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "location_import_started"}
        )

        # Track whether a MAIN warehouse has already been created in this run
        # to prevent creating multiple MAIN warehouses in one import.
        main_created_this_run = False

        for row in rows:
            nd = row.normalized_data or {}
            title = nd.get("title", "")

            print(f"[LOCATION IMPORTER] Processing row uid={row.uid} title='{title}'")
            try:
                with transaction.atomic():
                    short_name = nd.get("short_name") or None
                    full_address = nd.get("full_address") or None
                    remark = nd.get("remark") or None
                    kind = nd.get("kind") or WarehouseKindChoices.TEMPORARY

                    # Guard: only one MAIN warehouse per company
                    if kind == WarehouseKindChoices.MAIN:
                        main_exists = (
                            main_created_this_run
                            or Warehouse.objects.filter(
                                company=company,
                                kind=WarehouseKindChoices.MAIN,
                            )
                            .exclude(status=WarehouseStatusChoices.REMOVED)
                            .exists()
                        )
                        if main_exists:
                            kind = WarehouseKindChoices.TEMPORARY
                            logger.warning(
                                "[LOCATION IMPORTER] MAIN warehouse already exists for "
                                "company=%s; importing '%s' as TEMPORARY instead.",
                                company.id,
                                title,
                            )
                        else:
                            main_created_this_run = True

                    warehouse = Warehouse.objects.create(
                        title=title,
                        short_name=short_name,
                        remark=remark,
                        kind=kind,
                        status=WarehouseStatusChoices.ACTIVE,
                        company=company,
                    )

                    if full_address:
                        AddressConnector.objects.create(
                            kind=AddressConnectorKindCoices.WAREHOUSE,
                            warehouse=warehouse,
                            address=Address.objects.create(
                                full_address=full_address,
                                company=company,
                                status=AddressStatusChoices.ACTIVE,
                            ),
                        )

                    row.status = MigrationRowStatusChoices.IMPORTED
                    row.linked_record_uid = str(warehouse.uid)
                    row.linked_record_type = "warehouse"
                    row.message = "Successfully imported."
                    row.save(
                        update_fields=[
                            "status",
                            "linked_record_uid",
                            "linked_record_type",
                            "message",
                            "updated_at",
                        ]
                    )

                    imported += 1
                    MigrationAuditService.log(
                        job,
                        user,
                        CrudAction.CREATED,
                        {
                            "action": "location_imported",
                            "title": title,
                            "warehouse_uid": str(warehouse.uid),
                        },
                    )

            except Exception as e:
                print(f"[LOCATION IMPORTER] FAILED row={row.uid} title='{title}' error={e}")
                logger.exception(
                    "Location migration importer failed for row %s (title='%s'): %s",
                    row.uid,
                    title,
                    e,
                )
                failed += 1
                row.status = MigrationRowStatusChoices.FAILED
                row.message = str(e)
                row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "location_import_failed",
                        "row_uid": str(row.uid),
                        "title": title,
                        "error": str(e),
                    },
                )

        job.imported_rows = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED
        ).count()
        job.failed_rows = job.rows.filter(
            status=MigrationRowStatusChoices.FAILED
        ).count()
        job.skipped_rows = job.rows.filter(
            status=MigrationRowStatusChoices.SKIPPED
        ).count()
        job.completed_at = timezone.now()

        if imported > 0 and failed == 0:
            job.status = MigrationStatusChoices.COMPLETED
        elif imported > 0 and failed > 0:
            job.status = MigrationStatusChoices.PARTIALLY_COMPLETED
        else:
            job.status = MigrationStatusChoices.FAILED

        job.save(
            update_fields=[
                "imported_rows",
                "failed_rows",
                "skipped_rows",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        print(
            f"[LOCATION IMPORTER] DONE | imported={imported} failed={failed} "
            f"skipped={job.skipped_rows} job_status={job.status}"
        )
        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "location_import_completed",
                "imported": imported,
                "failed": failed,
            },
        )
