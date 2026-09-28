import logging

from datamigrationio.models import DataMigrationFieldMapping
from datamigrationio.choices import MigrationStatusChoices, MigrationStepChoices

logger = logging.getLogger(__name__)


class FieldMapperService:
    """Handler-driven field mapping.

    Aliases and required / accounting target-field sets are sourced from the
    handler registered for `job.data_type`. The legacy invoice-specific
    constants now live on `InvoiceMigrationHandler`.
    """

    @staticmethod
    def _get_handler(job):
        try:
            from datamigrationio.django_rest.handlers.registry import (
                MigrationHandlerRegistry,
            )

            return MigrationHandlerRegistry.get(job.data_type)
        except Exception:
            return None

    @staticmethod
    def get_field_sets(job, required_fields=None, accounting_fields=None):
        if required_fields is not None and accounting_fields is not None:
            return set(required_fields), set(accounting_fields)

        handler = FieldMapperService._get_handler(job)
        if handler:
            required = set(handler.get_required_target_fields())
            accounting = set(handler.get_accounting_target_fields())
            return required, accounting

        return set(), set()

    @staticmethod
    def _resolve_aliases(job, aliases):
        if aliases is not None:
            return aliases
        handler = FieldMapperService._get_handler(job)
        if handler:
            return handler.get_field_aliases()
        return {}

    @staticmethod
    def auto_map(job, aliases=None, required_fields=None, accounting_fields=None):
        """
        Auto-map source columns from the first row's raw_data keys to target fields
        using alias matching. Deletes existing mappings and creates fresh ones.
        Returns the created DataMigrationFieldMapping queryset.

        aliases: optional {source_alias_lowercased: target_field}. Falls back
        to the handler's `get_field_aliases()` for the job's data_type.
        """
        first_row = job.rows.first()
        if not first_row:
            return []

        columns = list(first_row.raw_data.keys())
        alias_map = FieldMapperService._resolve_aliases(job, aliases)
        required_targets, accounting_targets = FieldMapperService.get_field_sets(
            job, required_fields=required_fields, accounting_fields=accounting_fields
        )

        # Delete old mappings
        job.field_mappings.all().delete()

        mappings_to_create = []
        for col in columns:
            normalised = col.strip().lower()
            target = alias_map.get(normalised)
            if not target:
                continue

            is_required = target in required_targets
            affects_accounting = target in accounting_targets

            mappings_to_create.append(
                DataMigrationFieldMapping(
                    job=job,
                    source_column=col,
                    target_field=target,
                    is_required=is_required,
                    affects_accounting=affects_accounting,
                    status="mapped",
                )
            )

        created = DataMigrationFieldMapping.objects.bulk_create(mappings_to_create)

        job.status = MigrationStatusChoices.MAPPED
        job.current_step = MigrationStepChoices.PREVIEW_DATA
        job.save(update_fields=["status", "current_step", "updated_at"])

        return created

    @staticmethod
    def save_mappings(job, mappings_data, required_fields=None, accounting_fields=None):
        """
        Save manually provided mappings.
        mappings_data: list of {"source_column": str, "target_field": str}
        """
        job.field_mappings.all().delete()
        required_targets, accounting_targets = FieldMapperService.get_field_sets(
            job, required_fields=required_fields, accounting_fields=accounting_fields
        )

        mappings_to_create = []
        for item in mappings_data:
            source = item.get("source_column", "").strip()
            target = item.get("target_field", "").strip()
            if not source or not target:
                continue

            is_required = target in required_targets
            affects_accounting = target in accounting_targets

            mappings_to_create.append(
                DataMigrationFieldMapping(
                    job=job,
                    source_column=source,
                    target_field=target,
                    is_required=is_required,
                    affects_accounting=affects_accounting,
                    status="mapped",
                )
            )

        DataMigrationFieldMapping.objects.bulk_create(mappings_to_create)

        job.status = MigrationStatusChoices.MAPPED
        job.current_step = MigrationStepChoices.PREVIEW_DATA
        job.save(update_fields=["status", "current_step", "updated_at"])

    @staticmethod
    def apply_mapping_to_row(raw_data, mappings):
        """
        Apply a list of DataMigrationFieldMapping objects to raw_data.
        Returns mapped_data dict: {target_field: value}.
        """
        mapping_lookup = {m.source_column: m.target_field for m in mappings}
        mapped = {}
        for col, val in raw_data.items():
            target = mapping_lookup.get(col)
            if target:
                mapped[target] = val
        return mapped
