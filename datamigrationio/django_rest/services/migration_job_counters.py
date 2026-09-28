from datamigrationio.choices import MigrationRowStatusChoices


def refresh_job_row_counters(job):
    """Recompute job row status counters from persisted row statuses."""
    rows = job.rows.all()
    job.ready_rows = rows.filter(status=MigrationRowStatusChoices.READY).count()
    job.warning_rows = rows.filter(status=MigrationRowStatusChoices.WARNING).count()
    job.error_rows = rows.filter(status=MigrationRowStatusChoices.ERROR).count()
    job.duplicate_rows = rows.filter(
        status__in=(
            MigrationRowStatusChoices.DUPLICATE,
            MigrationRowStatusChoices.SKIPPED,
        )
    ).count()
    job.skipped_rows = rows.filter(status=MigrationRowStatusChoices.SKIPPED).count()
    job.save(
        update_fields=[
            "ready_rows",
            "warning_rows",
            "error_rows",
            "duplicate_rows",
            "skipped_rows",
            "updated_at",
        ]
    )


def increment_row_status_counter(counters, row):
    if row.status == MigrationRowStatusChoices.READY:
        counters["ready"] += 1
    elif row.status == MigrationRowStatusChoices.WARNING:
        counters["warning"] += 1
    elif row.status == MigrationRowStatusChoices.ERROR:
        counters["error"] += 1
    elif row.status in (
        MigrationRowStatusChoices.DUPLICATE,
        MigrationRowStatusChoices.SKIPPED,
    ):
        counters["duplicate"] += 1
        counters["skipped"] += 1
