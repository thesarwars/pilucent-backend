from rest_framework.serializers import (
    ModelSerializer,
    Serializer,
    CharField,
    ChoiceField,
    BooleanField,
    FileField,
    ListField,
    UUIDField,
)

from datamigrationio.models import (
    DataMigrationJob,
    DataMigrationRow,
    DataMigrationFieldMapping,
    DataMigrationValidationIssue,
    DataMigrationImpactLine,
)
from datamigrationio.choices import (
    MigrationDataTypeChoices,
    MigrationDuplicateHandlingChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction
from common.django_rest.helpers.decorators import set_auditlog_actor
from rest_framework.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Job serializers
# ---------------------------------------------------------------------------


class DataMigrationJobListSerializer(ModelSerializer):
    class Meta:
        model = DataMigrationJob
        fields = [
            "uid",
            "data_type",
            "file_name",
            "file_type",
            "status",
            "current_step",
            "total_rows",
            "ready_rows",
            "warning_rows",
            "error_rows",
            "duplicate_rows",
            "skipped_rows",
            "imported_rows",
            "failed_rows",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DataMigrationJobCreateSerializer(Serializer):
    data_type = ChoiceField(choices=MigrationDataTypeChoices.choices)
    file = FileField(required=False)
    json_data = ListField(required=False, allow_empty=False)
    date_format = CharField(default="MM/DD/YYYY", required=False)
    currency = CharField(default="USD", required=False, max_length=10)
    decimal_format = CharField(default="1,234.56", required=False)
    duplicate_handling = ChoiceField(
        choices=MigrationDuplicateHandlingChoices.choices,
        default=MigrationDuplicateHandlingChoices.SKIP_DUPLICATES,
        required=False,
    )
    has_header_row = BooleanField(default=True, required=False)

    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        job = DataMigrationJob.objects.create(
            company=company,
            data_type=validated_data["data_type"],
            status=MigrationStatusChoices.DRAFT,
            current_step=MigrationStepChoices.UPLOAD_FILE,
        )
        MigrationAuditService.log(
            job, user, CrudAction.CREATED, {"action": "job_created"}
        )
        return job


class DataMigrationJobDetailSerializer(ModelSerializer):
    class Meta:
        model = DataMigrationJob
        fields = [
            "uid",
            "data_type",
            "file_name",
            "file_type",
            "status",
            "current_step",
            "total_rows",
            "total_columns",
            "ready_rows",
            "warning_rows",
            "error_rows",
            "duplicate_rows",
            "skipped_rows",
            "imported_rows",
            "failed_rows",
            "partially_imported_rows",
            "duplicate_handling",
            "date_format",
            "currency",
            "decimal_format",
            "has_header_row",
            "confirmed_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DataMigrationUploadSerializer(Serializer):
    file = FileField(required=False)
    json_data = ListField(required=False, allow_empty=False)
    date_format = CharField(default="MM/DD/YYYY", required=False)
    currency = CharField(default="USD", required=False, max_length=10)
    decimal_format = CharField(default="1,234.56", required=False)
    duplicate_handling = ChoiceField(
        choices=MigrationDuplicateHandlingChoices.choices,
        default=MigrationDuplicateHandlingChoices.SKIP_DUPLICATES,
        required=False,
    )
    has_header_row = BooleanField(default=True, required=False)

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("json_data"):

            raise ValidationError(
                {"message": "Either a file or json_data must be provided."}
            )
        return attrs


class DataMigrationFieldMappingItemSerializer(Serializer):
    source_column = CharField()
    target_field = CharField()


class DataMigrationMappingSerializer(Serializer):
    mappings = DataMigrationFieldMappingItemSerializer(many=True)


class DataMigrationFieldMappingSerializer(ModelSerializer):
    class Meta:
        model = DataMigrationFieldMapping
        fields = [
            "uid",
            "source_column",
            "target_field",
            "is_required",
            "affects_accounting",
            "status",
        ]
        read_only_fields = fields



class DataMigrationRowFixSerializer(Serializer):
    field = CharField()
    value = CharField(allow_blank=True)
    apply_to_similar_records = BooleanField(default=False, required=False)



class DataMigrationConfirmSerializer(Serializer):
    understood_financial_impact = BooleanField()
    skip_error_rows = BooleanField(default=True, required=False)
    send_email = BooleanField(default=False, required=False)
    approval_note = CharField(required=False, allow_blank=True)
    idempotency_key = CharField(required=False, allow_blank=True)

    def validate_understood_financial_impact(self, value):
        if not value:

            raise ValidationError(
                "You must acknowledge the financial impact before confirming import."
            )
        return value


class DataMigrationRollbackSerializer(Serializer):
    reason = CharField()
    idempotency_key = CharField(required=False, allow_blank=True)

class DataMigrationValidationIssueSerializer(ModelSerializer):
    row_uid = UUIDField(source="row.uid", read_only=True)

    class Meta:
        model = DataMigrationValidationIssue
        fields = [
            "uid",
            "row_uid",
            "issue_type",
            "severity",
            "description",
            "suggested_fix",
            "is_resolved",
            "resolved_at",
            "created_at",
        ]
        read_only_fields = fields


class DataMigrationImpactLineSerializer(ModelSerializer):
    class Meta:
        model = DataMigrationImpactLine
        fields = [
            "uid",
            "transaction_type",
            "account_title",
            "debit",
            "credit",
            "customer_name",
            "tax",
            "location",
            "report_impact",
        ]
        read_only_fields = fields


class DataMigrationRowSlimSerializer(ModelSerializer):
    issues = DataMigrationValidationIssueSerializer(many=True, read_only=True)

    class Meta:
        model = DataMigrationRow
        fields = [
            "uid",
            "row_number",
            "raw_data",
            "mapped_data",
            "normalized_data",
            "status",
            "error_count",
            "warning_count",
            "duplicate_count",
            "linked_record_uid",
            "linked_record_type",
            "message",
            "issues",
        ]
        read_only_fields = fields


class DataMigrationRowPreviewSerializer(ModelSerializer):
    class Meta:
        model = DataMigrationRow
        fields = ["row_number", "uid", "raw_data"]
        read_only_fields = fields
