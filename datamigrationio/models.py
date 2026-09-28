from django.db import models
from autoslug import AutoSlugField

from common.models import BaseModelWithUID
from datamigrationio.django_rest.helpers.slug_helpers import (
    get_data_migrations_jobs_slug,
    get_data_migration_row_slug,
    get_data_migration_field_mapping_slug,
    get_data_migration_validation_issue_slug,
    get_data_migration_impact_line_slug,
)
from datamigrationio.choices import (
    MigrationDataTypeChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
    MigrationRowStatusChoices,
    MigrationSeverityChoices,
    MigrationIssueTypeChoices,
    MigrationDuplicateHandlingChoices,
)


class DataMigrationJob(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_data_migrations_jobs_slug, unique=True, db_index=True
    )
    data_type = models.CharField(
        max_length=50,
        choices=MigrationDataTypeChoices.choices,
        default=MigrationDataTypeChoices.INVOICES,
    )
    file = models.FileField(upload_to="data_migrations/files/", null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(max_length=20, blank=True)
    status = models.CharField(
        max_length=50,
        choices=MigrationStatusChoices.choices,
        default=MigrationStatusChoices.DRAFT,
    )
    current_step = models.CharField(
        max_length=50,
        choices=MigrationStepChoices.choices,
        default=MigrationStepChoices.SELECT_DATA_TYPE,
    )
    # Row counters
    total_rows = models.PositiveIntegerField(default=0)
    total_columns = models.PositiveIntegerField(default=0)
    ready_rows = models.PositiveIntegerField(default=0)
    warning_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    partially_imported_rows = models.PositiveIntegerField(default=0)
    # Import settings
    duplicate_handling = models.CharField(
        max_length=50,
        choices=MigrationDuplicateHandlingChoices.choices,
        default=MigrationDuplicateHandlingChoices.SKIP_DUPLICATES,
    )
    date_format = models.CharField(max_length=20, default="MM/DD/YYYY")
    currency = models.CharField(max_length=10, default="USD")
    decimal_format = models.CharField(max_length=20, default="1,234.56")
    has_header_row = models.BooleanField(default=True)
    # Tracking
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_migration_jobs",
    )
    confirmed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_migration_jobs",
    )
    company = models.ForeignKey(
        "companyio.Company",
        on_delete=models.CASCADE,
        related_name="data_migration_jobs",
    )

    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"DataMigrationJob({self.data_type}, {self.status}, company={self.company_id})"


class DataMigrationRow(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_data_migration_row_slug, unique=False, db_index=True
    )
    row_number = models.IntegerField()
    raw_data = models.JSONField(default=dict)  # original — never mutated
    mapped_data = models.JSONField(default=dict)  # written by FieldMapperService
    normalized_data = models.JSONField(
        default=dict
    )  # written by InvoiceValidatorService
    status = models.CharField(
        max_length=20,
        choices=MigrationRowStatusChoices.choices,
        default=MigrationRowStatusChoices.PENDING,
    )
    error_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    linked_record_uid = models.CharField(max_length=50, null=True, blank=True)
    linked_record_type = models.CharField(max_length=50, null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    job = models.ForeignKey(
        DataMigrationJob,
        on_delete=models.CASCADE,
        related_name="rows",
    )

    def __str__(self):
        return f"DataMigrationRow(job={self.job_id}, row={self.row_number}, status={self.status})"


class DataMigrationFieldMapping(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_data_migration_field_mapping_slug, unique=False, db_index=True
    )
    source_column = models.CharField(max_length=100)
    target_field = models.CharField(max_length=100)
    is_required = models.BooleanField(default=False)
    affects_accounting = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="mapped")
    job = models.ForeignKey(
        DataMigrationJob,
        on_delete=models.CASCADE,
        related_name="field_mappings",
    )

    def __str__(self):
        return f"{self.source_column} → {self.target_field}"


class DataMigrationValidationIssue(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_data_migration_validation_issue_slug,
        unique=False,
        db_index=True,
    )
    row = models.ForeignKey(
        DataMigrationRow,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    issue_type = models.CharField(
        max_length=50,
        choices=MigrationIssueTypeChoices.choices,
    )
    severity = models.CharField(
        max_length=20,
        choices=MigrationSeverityChoices.choices,
    )
    description = models.TextField()
    suggested_fix = models.TextField(null=True, blank=True)
    fix_payload = models.JSONField(default=dict)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_migration_issues",
    )
    job = models.ForeignKey(
        DataMigrationJob,
        on_delete=models.CASCADE,
        related_name="validation_issues",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.severity}: {self.issue_type} (row={self.row.row_number})"


class DataMigrationImpactLine(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_data_migration_impact_line_slug, unique=False, db_index=True
    )
    transaction_type = models.CharField(max_length=50)
    account_title = models.CharField(max_length=100, null=True, blank=True)
    debit = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    credit = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    customer_name = models.CharField(max_length=200, null=True, blank=True)
    tax = models.CharField(max_length=100, null=True, blank=True)
    location = models.CharField(max_length=100, null=True, blank=True)
    report_impact = models.CharField(max_length=100, null=True, blank=True)
    job = models.ForeignKey(
        DataMigrationJob,
        on_delete=models.CASCADE,
        related_name="impact_lines",
    )
    row = models.ForeignKey(
        DataMigrationRow,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="impact_lines",
    )
    customer = models.ForeignKey(
        "customerio.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    account = models.ForeignKey(
        "accounts.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"ImpactLine({self.transaction_type}, DR={self.debit}, CR={self.credit})"
