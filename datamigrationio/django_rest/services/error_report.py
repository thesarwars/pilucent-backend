import csv
import io
import json

from django.http import HttpResponse

from datamigrationio.models import DataMigrationRow
from datamigrationio.django_rest.services.workflow_control import get_row_reference


class ErrorReportService:
    HEADERS = [
        "Row Number",
        "Data Type",
        "Primary Reference",
        "Party",
        "Status",
        "Issue Type",
        "Severity",
        "Error Message",
        "Suggested Fix",
        "Mapped Data",
        "Normalized Data",
        "Original Data",
    ]

    @staticmethod
    def generate_csv_response(job):
        """
        Generate a CSV error report for all rows with issues.
        Returns HttpResponse with text/csv content type.
        """
        rows = (
            DataMigrationRow.objects.filter(job=job)
            .prefetch_related("issues")
            .order_by("row_number")
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(ErrorReportService.HEADERS)

        for row in rows:
            issues = list(row.issues.all())
            reference, party = get_row_reference(row)

            if not issues:
                writer.writerow(
                    [
                        row.row_number,
                        job.data_type,
                        reference,
                        party,
                        row.status,
                        "",
                        "",
                        "",
                        "",
                        json.dumps(row.mapped_data or {}),
                        json.dumps(row.normalized_data or {}),
                        json.dumps(row.raw_data),
                    ]
                )
            else:
                for issue in issues:
                    writer.writerow(
                        [
                            row.row_number,
                            job.data_type,
                            reference,
                            party,
                            row.status,
                            issue.issue_type,
                            issue.severity,
                            issue.description,
                            issue.suggested_fix or "",
                            json.dumps(row.mapped_data or {}),
                            json.dumps(row.normalized_data or {}),
                            json.dumps(row.raw_data),
                        ]
                    )

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="error-report-{job.uid}.csv"'
        )
        return response

    INVOICE_TEMPLATE_HEADERS = [
        "Customer Name",
        "Customer Email",
        "Invoice Number",
        "Invoice Date",
        "Due Date",
        "Product Name",
        "Description",
        "Quantity",
        "Unit Price",
        "Amount",
        "Tax Code",
        "Account Name",
        "Location",
        "Currency",
        "Currency Rate",
        "Memo",
        "Billing Address",
        "Shipping Address",
        "Shipping By",
        "Shipping Date",
        "Term",
        "Reference Number",
    ]

    INVOICE_SAMPLE_ROW = [
        "Acme Corp",
        "acme@example.com",
        "INV-001",
        "01/15/2026",
        "02/15/2026",
        "Website Design",
        "Landing page design",
        "1",
        "500.00",
        "500.00",
        "",
        "",
        "",
        "USD",
        "1",
        "",
        "123 Main Street",
        "",
        "",
        "",
        "",
        "",
    ]

    @staticmethod
    def generate_template_response(headers=None, sample_row=None, filename="invoice-import-template.csv"):
        if headers is None:
            headers = ErrorReportService.INVOICE_TEMPLATE_HEADERS
            if sample_row is None:
                sample_row = ErrorReportService.INVOICE_SAMPLE_ROW

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)

        if sample_row:
            writer.writerow(sample_row)

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
