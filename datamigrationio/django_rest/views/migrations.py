import logging

from rest_framework.generics import ListCreateAPIView, RetrieveAPIView, GenericAPIView
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.generics import get_object_or_404

from django.utils import timezone

from datamigrationio.models import (
    DataMigrationJob,
    DataMigrationRow,
    DataMigrationFieldMapping,
    DataMigrationValidationIssue,
)
from datamigrationio.choices import (
    MigrationStatusChoices,
    MigrationStepChoices,
    MigrationRowStatusChoices,
)
from datamigrationio.django_rest.serializers.common import (
    DataMigrationJobListSerializer,
    DataMigrationJobCreateSerializer,
    DataMigrationJobDetailSerializer,
    DataMigrationUploadSerializer,
    DataMigrationMappingSerializer,
    DataMigrationFieldMappingSerializer,
    DataMigrationConfirmSerializer,
    DataMigrationRollbackSerializer,
    DataMigrationRowFixSerializer,
    DataMigrationValidationIssueSerializer,
    DataMigrationRowSlimSerializer,
    DataMigrationRowPreviewSerializer,
    DataMigrationImpactLineSerializer,
)
from datamigrationio.django_rest.services.file_parser import FileParserService
from datamigrationio.django_rest.services.field_mapper import FieldMapperService
from datamigrationio.django_rest.services.error_report import ErrorReportService
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from datamigrationio.django_rest.services.workflow_control import (
    MigrationDryRunService,
    MigrationReconciliationService,
    MigrationRollbackService,
    get_row_reference,
)
from datamigrationio.django_rest.services.row_fix import RowFixService
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from common.django_rest.helpers.crud_logger import CrudAction


logger = logging.getLogger(__name__)


class PrivateDataMigrationListCreate(ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return DataMigrationJobCreateSerializer
        return DataMigrationJobListSerializer

    def get_queryset(self):
        company = self.request.user.get_active_company()
        return DataMigrationJob.objects.filter(company=company)

    def create(self, request, *args, **kwargs):
        serializer = DataMigrationJobCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        job = serializer.save()

        data = serializer.validated_data
        file_obj = data.get("file")
        json_data = data.get("json_data")

        if not file_obj and not json_data:
            return Response(
                DataMigrationJobDetailSerializer(job).data,
                status=status.HTTP_201_CREATED,
            )

        # Update job settings
        job.date_format = data.get("date_format", "MM/DD/YYYY")
        job.currency = data.get("currency", "USD")
        job.decimal_format = data.get("decimal_format", "1,234.56")
        job.duplicate_handling = data.get("duplicate_handling", "skip_duplicates")
        job.has_header_row = data.get("has_header_row", True)

        # Parse file or JSON
        if file_obj:
            parsed = FileParserService.parse(
                file_obj, file_obj.name, job.has_header_row
            )
            file_obj.seek(0)
            job.file = file_obj
            job.file_name = file_obj.name
        else:
            parsed = FileParserService.parse_json_payload(json_data)
            job.file_name = "payload.json"

        job.file_type = parsed["file_type"]
        job.total_rows = parsed["total_rows"]
        job.total_columns = len(parsed["columns"])
        job.status = MigrationStatusChoices.UPLOADED
        job.current_step = MigrationStepChoices.MAP_FIELDS
        job.save()

        DataMigrationRow.objects.bulk_create([
            DataMigrationRow(job=job, row_number=i + 1, raw_data=row)
            for i, row in enumerate(parsed["rows"])
        ])

        handler = MigrationHandlerRegistry.get(job.data_type)
        aliases = handler.get_field_aliases() if handler else {}
        FieldMapperService.auto_map(job, aliases=aliases)

        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {
                "action": "file_uploaded",
                "file_type": parsed["file_type"],
                "total_rows": parsed["total_rows"],
            },
        )

        return Response(
            {
                "job_uid": str(job.uid),
                "total_rows": job.total_rows,
                "total_columns": job.total_columns,
                "file_type": job.file_type,
                "columns": parsed["columns"],
            },
            status=status.HTTP_201_CREATED,
        )


class PrivateDataMigrationDetail(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationJobDetailSerializer

    def get_object(self):
        return get_object_or_404(
            DataMigrationJob,
            uid=self.kwargs["uid"],
            company=self.request.user.get_active_company(),
        )


class PrivateDataMigrationDataTypes(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MigrationHandlerRegistry.get_all_metadata())


class PrivateDataMigrationUpload(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationUploadSerializer

    def handle_upload(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        serializer = DataMigrationUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Delete existing rows before re-upload
        job.rows.all().delete()
        job.field_mappings.all().delete()
        job.validation_issues.all().delete()
        job.impact_lines.all().delete()

        # Update job settings
        job.date_format = data.get("date_format", "MM/DD/YYYY")
        job.currency = data.get("currency", "USD")
        job.decimal_format = data.get("decimal_format", "1,234.56")
        job.duplicate_handling = data.get("duplicate_handling", "skip_duplicates")
        job.has_header_row = data.get("has_header_row", True)

        # Parse file or JSON
        file_obj = data.get("file")
        json_data = data.get("json_data")

        if file_obj:
            parsed = FileParserService.parse(
                file_obj, file_obj.name, job.has_header_row
            )
            file_obj.seek(0)
            job.file = file_obj
            job.file_name = file_obj.name
        else:
            parsed = FileParserService.parse_json_payload(json_data)
            job.file_name = "payload.json"

        job.file_type = parsed["file_type"]
        job.total_rows = parsed["total_rows"]
        job.total_columns = len(parsed["columns"])
        job.status = MigrationStatusChoices.UPLOADED
        job.current_step = MigrationStepChoices.MAP_FIELDS
        job.save()

        # Bulk create rows
        DataMigrationRow.objects.bulk_create([
            DataMigrationRow(job=job, row_number=i + 1, raw_data=row)
            for i, row in enumerate(parsed["rows"])
        ])

        handler = MigrationHandlerRegistry.get(job.data_type)
        aliases = handler.get_field_aliases() if handler else {}
        FieldMapperService.auto_map(job, aliases=aliases)

        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {
                "action": "file_uploaded",
                "file_type": parsed["file_type"],
                "total_rows": parsed["total_rows"],
            },
        )

        return Response(
            {
                "job_uid": str(job.uid),
                "total_rows": job.total_rows,
                "total_columns": job.total_columns,
                "file_type": job.file_type,
                "columns": parsed["columns"],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, uid):
        return self.handle_upload(request, uid)

    def put(self, request, uid):
        return self.handle_upload(request, uid)


class PrivateDataMigrationPreview(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        preview_rows = job.rows.order_by("row_number")

        return Response(
            {
                "job_uid": str(job.uid),
                "total_rows": job.total_rows,
                "total_columns": job.total_columns,
                "file_type": job.file_type,
                "preview_rows": DataMigrationRowPreviewSerializer(
                    preview_rows, many=True
                ).data,
            }
        )


class PrivateDataMigrationAutoMap(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )

        handler = MigrationHandlerRegistry.get(job.data_type)
        aliases = handler.get_field_aliases() if handler else {}
        created = FieldMapperService.auto_map(job, aliases=aliases)

        MigrationAuditService.log(
            job, request.user, CrudAction.UPDATED, {"action": "fields_auto_mapped"}
        )

        return Response(
            {
                "job_uid": str(job.uid),
                "mappings": DataMigrationFieldMappingSerializer(
                    created, many=True
                ).data,
            }
        )


class PrivateDataMigrationMapping(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationMappingSerializer

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        serializer = DataMigrationMappingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        FieldMapperService.save_mappings(job, serializer.validated_data["mappings"])

        MigrationAuditService.log(
            job, request.user, CrudAction.UPDATED, {"action": "fields_mapped"}
        )

        mappings = job.field_mappings.all()
        return Response(
            {
                "job_uid": str(job.uid),
                "mappings": DataMigrationFieldMappingSerializer(
                    mappings, many=True
                ).data,
            }
        )


class PrivateDataMigrationValidate(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        company = request.user.get_active_company()

        handler = MigrationHandlerRegistry.get(job.data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {job.data_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = handler.validate(job, company)

        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {"action": "validation_completed"},
        )

        return Response(result)


class PrivateDataMigrationValidationIssues(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        issues = (
            DataMigrationValidationIssue.objects.filter(job=job)
            .select_related("row")
            .order_by("row__row_number", "severity")
        )

        return Response(
            {
                "job_uid": str(job.uid),
                "count": issues.count(),
                "issues": DataMigrationValidationIssueSerializer(
                    issues, many=True
                ).data,
            }
        )


class PrivateDataMigrationRowFix(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationRowFixSerializer

    def post(self, request, uid, row_uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        row = get_object_or_404(DataMigrationRow, uid=row_uid, job=job)
        serializer = DataMigrationRowFixSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        field = serializer.validated_data["field"]
        value = serializer.validated_data["value"]
        apply_to_similar = serializer.validated_data.get(
            "apply_to_similar_records", False
        )
        company = request.user.get_active_company()

        result = RowFixService.apply_fix(
            job=job,
            row=row,
            company=company,
            field=field,
            value=value,
            user=request.user,
            apply_to_similar=apply_to_similar,
        )

        row_data = DataMigrationRowSlimSerializer(result["row"]).data
        payload = {
            **row_data,
            "fixed": result["fixed"],
            "message": result["message"],
            "field": result["field"],
        }
        if result.get("suggested_fix"):
            payload["suggested_fix"] = result["suggested_fix"]
        if result.get("similar_rows_fixed"):
            payload["similar_rows_fixed"] = result["similar_rows_fixed"]

        if not result["fixed"]:
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        return Response(payload, status=status.HTTP_200_OK)


class PrivateDataMigrationReviewImpact(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        company = request.user.get_active_company()

        handler = MigrationHandlerRegistry.get(job.data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {job.data_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = handler.review_impact(job, company)

        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {
                "action": "impact_reviewed",
                "total_transactions": result.get("total_transactions"),
            },
        )

        return Response(result)


class PrivateDataMigrationDryRun(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        company = request.user.get_active_company()

        handler = MigrationHandlerRegistry.get(job.data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {job.data_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = MigrationDryRunService.run(job, company, handler)
        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {"action": "dry_run_completed", "can_commit": result.get("can_commit")},
        )
        return Response(result)


class PrivateDataMigrationConfirm(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationConfirmSerializer

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        serializer = DataMigrationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        skip_error_rows = serializer.validated_data.get("skip_error_rows", True)
        send_email = serializer.validated_data.get("send_email", False)
        approval_note = serializer.validated_data.get("approval_note", "")
        idempotency_key = serializer.validated_data.get("idempotency_key", "")

        handler = MigrationHandlerRegistry.get(job.data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {job.data_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not handler.import_available:
            return Response(
                {
                    "message": f"Import is not implemented yet for this migration type.",
                    "data_type": job.data_type,
                    "import_available": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if job.status in [
            MigrationStatusChoices.CONFIRMED,
            MigrationStatusChoices.IN_PROGRESS,
            MigrationStatusChoices.COMPLETED,
            MigrationStatusChoices.PARTIALLY_COMPLETED,
        ]:
            return Response(
                {
                    "job_uid": str(job.uid),
                    "status": job.status,
                    "message": "Import has already been confirmed or processed.",
                    "idempotency_key": idempotency_key,
                },
                status=status.HTTP_200_OK,
            )

        # Pre-import checks (only run for importable types)
        if job.status != MigrationStatusChoices.IMPACT_REVIEWED:
            return Response(
                {
                    "message": "Accounting impact must be reviewed before confirming import."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not skip_error_rows and job.error_rows > 0:
            return Response(
                {
                    "message": f"There are {job.error_rows} rows with errors. "
                    "Set skip_error_rows=true to import only valid rows."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = MigrationStatusChoices.CONFIRMED
        job.confirmed_by = request.user
        job.confirmed_at = timezone.now()
        job.current_step = MigrationStepChoices.RESULTS_AUDIT
        job.save(
            update_fields=[
                "status",
                "confirmed_by",
                "confirmed_at",
                "current_step",
                "updated_at",
            ]
        )

        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {
                "action": "import_confirmed",
                "approval_note": approval_note,
                "idempotency_key": idempotency_key,
            },
        )

        result = handler.confirm_import(job, request.user, options={"send_email": send_email})
        return Response(result)


class PrivateDataMigrationReconciliation(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        return Response(MigrationReconciliationService.build_summary(job))


class PrivateDataMigrationRollback(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataMigrationRollbackSerializer

    def post(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        serializer = DataMigrationRollbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        handler = MigrationHandlerRegistry.get(job.data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {job.data_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = MigrationRollbackService.run(
            job,
            request.user,
            handler,
            reason=serializer.validated_data["reason"],
        )
        MigrationAuditService.log(
            job,
            request.user,
            CrudAction.UPDATED,
            {
                "action": "rollback_requested",
                "reason": serializer.validated_data["reason"],
                "implemented": result.get("implemented"),
                "idempotency_key": serializer.validated_data.get("idempotency_key", ""),
            },
        )

        if not result.get("implemented"):
            response_status = status.HTTP_501_NOT_IMPLEMENTED
        elif result.get("errors"):
            response_status = status.HTTP_207_MULTI_STATUS
        else:
            response_status = status.HTTP_200_OK
        return Response(result, status=response_status)


class PrivateDataMigrationResults(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        rows = job.rows.all().order_by("row_number")

        return Response(
            {
                "job_uid": str(job.uid),
                "status": job.status,
                "imported": job.imported_rows,
                "failed": job.failed_rows,
                "skipped": job.skipped_rows,
                "partially_imported": job.partially_imported_rows,
                "completed_at": job.completed_at,
                "details": [
                    {
                        "row_number": r.row_number,
                        "reference": get_row_reference(r)[0],
                        "party": get_row_reference(r)[1],
                        "status": r.status,
                        "message": r.message,
                        "linked_record_uid": r.linked_record_uid,
                    }
                    for r in rows
                ],
            }
        )


class PrivateDataMigrationErrorReport(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )
        return ErrorReportService.generate_csv_response(job)


class PrivateDataMigrationAuditLogs(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        job = get_object_or_404(
            DataMigrationJob, uid=uid, company=request.user.get_active_company()
        )

        try:
            from auditlog.models import LogEntry
            from django.contrib.contenttypes.models import ContentType

            content_type = ContentType.objects.get_for_model(DataMigrationJob)
            logs = LogEntry.objects.filter(
                content_type=content_type,
                object_id=str(job.pk),
            ).order_by("-timestamp")[:100]

            log_data = [
                {
                    "timestamp": log.timestamp,
                    "actor": str(log.actor) if log.actor else None,
                    "action": log.get_action_display(),
                    "changes": log.changes,
                }
                for log in logs
            ]
        except Exception:
            log_data = []

        return Response(
            {
                "job_uid": str(job.uid),
                "logs": log_data,
            }
        )


class PrivateDataMigrationTemplateDownload(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, data_type="invoices"):
        handler = MigrationHandlerRegistry.get(data_type)
        if not handler:
            return Response(
                {"message": f"Unknown data type: {data_type}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        custom_response = handler.generate_template_response()
        if custom_response:
            return custom_response
        headers = handler.get_template_headers()
        if not headers:
            return Response(
                {"message": f"No template available for {handler.label}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        sample_row = handler.get_template_sample_row()
        return ErrorReportService.generate_template_response(
            headers=headers,
            sample_row=sample_row or None,
            filename=f"{data_type}-import-template.csv",
        )
