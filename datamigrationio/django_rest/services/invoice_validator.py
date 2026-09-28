import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from datamigrationio.models import (
    DataMigrationRow,
    DataMigrationValidationIssue,
)
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationSeverityChoices,
    MigrationIssueTypeChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
    MigrationDuplicateHandlingChoices,
)
from datamigrationio.django_rest.services.field_mapper import FieldMapperService
from datamigrationio.django_rest.services.migration_job_counters import (
    increment_row_status_counter,
)

from customerio.models import Customer
from customerio.choices import CustomerStatusChoices
from productio.models import Product
from productio.choices import ProductStatusChoices
from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from wirehouseio.models import Warehouse
from termio.models import Term
from salesio.models import Sale

logger = logging.getLogger(__name__)

DATE_FORMAT_MAP = {
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM-DD-YYYY": "%m-%d-%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
}


def parse_date(value, date_format):
    fmt = DATE_FORMAT_MAP.get(date_format, "%m/%d/%Y")
    try:
        return datetime.strptime(str(value).strip(), fmt).date()
    except (ValueError, TypeError):
        return None


def parse_decimal(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        cleaned = str(value).replace(",", "").strip()
        return Decimal(cleaned)
    except InvalidOperation:
        return None


class InvoiceValidatorService:
    @staticmethod
    def validate_job(job, company):
        """
        Validate all rows for a job. Company-scoped lookups only.
        Deletes old unresolved issues and recreates them on each run.
        Updates job counters and status after validation.
        """

        mappings = list(job.field_mappings.all())
        rows = job.rows.all()

        # Delete all existing unresolved validation issues for this job
        DataMigrationValidationIssue.objects.filter(job=job, is_resolved=False).delete()

        counters = {
            "ready": 0,
            "warning": 0,
            "error": 0,
            "duplicate": 0,
            "skipped": 0,
        }

        for row in rows:
            InvoiceValidatorService.validate_row(
                row, job, company, mappings, counters=counters
            )

        job.ready_rows = counters["ready"]
        job.warning_rows = counters["warning"]
        job.error_rows = counters["error"]
        job.duplicate_rows = counters["duplicate"]
        job.skipped_rows = counters["skipped"]
        job.status = MigrationStatusChoices.VALIDATED
        job.current_step = MigrationStepChoices.REVIEW_IMPACT
        job.save(
            update_fields=[
                "ready_rows",
                "warning_rows",
                "error_rows",
                "duplicate_rows",
                "skipped_rows",
                "status",
                "current_step",
                "updated_at",
            ]
        )

        return {
            "job_uid": str(job.uid),
            "total_rows": job.total_rows,
            "ready_rows": job.ready_rows,
            "warning_rows": job.warning_rows,
            "error_rows": job.error_rows,
            "duplicate_rows": job.duplicate_rows,
            "skipped_rows": job.skipped_rows,
        }

    @staticmethod
    def validate_row(
        row, job, company, mappings, counters=None, remap_from_raw=True
    ):
        row.issues.filter(is_resolved=False).delete()

        if remap_from_raw:
            mapped_data = FieldMapperService.apply_mapping_to_row(
                row.raw_data, mappings
            )
            row.mapped_data = mapped_data
        else:
            mapped_data = dict(row.mapped_data or {})

        normalized_data = {}
        issues = []

        # --- Customer validation ---
        customer_name = mapped_data.get("customer", "").strip()
        customer_email = mapped_data.get("customer_email", "").strip()
        resolved_customer = None

        if customer_email:
            resolved_customer = (
                Customer.objects.filter(
                    email__iexact=customer_email,
                    company=company,
                )
                .exclude(status=CustomerStatusChoices.REMOVED)
                .first()
            )

        if not resolved_customer and customer_name:
            name_parts = customer_name.split()
            first_part = name_parts[0] if name_parts else ""
            last_part = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            name_filter = (
                Q(display_name__iexact=customer_name)
                | Q(company_name__iexact=customer_name)
                | Q(first_name__iexact=customer_name)
                | Q(last_name__iexact=customer_name)
            )
            if first_part and last_part:
                name_filter |= Q(
                    first_name__iexact=first_part,
                    last_name__iexact=last_part,
                )

            resolved_customer = (
                Customer.objects.filter(name_filter, company=company)
                .exclude(status=CustomerStatusChoices.REMOVED)
                .first()
            )

        if resolved_customer:
            normalized_data["customer_uid"] = str(resolved_customer.uid)
            normalized_data["customer_id"] = resolved_customer.id
            normalized_data["customer_name"] = (
                resolved_customer.display_name
                or resolved_customer.company_name
                or customer_name
            )
            normalized_data["customer_email"] = (
                resolved_customer.email or customer_email
            )
        elif not customer_name and not customer_email:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Customer name or email is required.",
                    "suggested_fix": "Provide a customer name or email in the mapped data.",
                }
            )
        else:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.CUSTOMER_NOT_FOUND,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Customer '{customer_name or customer_email}' does not exist in this company.",
                    "suggested_fix": "Map this row to an existing customer before import.",
                }
            )

        # --- Invoice number validation ---
        invoice_number = mapped_data.get("invoice_number", "").strip()
        if not invoice_number:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Invoice number is required.",
                    "suggested_fix": "Provide an invoice number.",
                }
            )

        # --- Date validation ---
        invoice_date_raw = mapped_data.get("invoice_date", "").strip()
        due_date_raw = mapped_data.get("due_date", "").strip()
        invoice_date = parse_date(invoice_date_raw, job.date_format)
        due_date = parse_date(due_date_raw, job.date_format)

        if not invoice_date_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Invoice date is required.",
                    "suggested_fix": "Provide a valid invoice date.",
                }
            )
        elif invoice_date is None:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Invoice date '{invoice_date_raw}' could not be parsed with format {job.date_format}.",
                    "suggested_fix": f"Use date format {job.date_format}.",
                }
            )
        else:
            normalized_data["invoice_date"] = str(invoice_date)

        if not due_date_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Due date is required.",
                    "suggested_fix": "Provide a valid due date.",
                }
            )
        elif due_date is None:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Due date '{due_date_raw}' could not be parsed with format {job.date_format}.",
                    "suggested_fix": f"Use date format {job.date_format}.",
                }
            )
        else:
            normalized_data["due_date"] = str(due_date)

        if invoice_date and due_date and due_date < invoice_date:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Due date cannot be before invoice date.",
                    "suggested_fix": "Correct the due date.",
                }
            )

        # --- Amount validation ---
        line_amount_raw = mapped_data.get("line_amount", "").strip()
        line_amount = parse_decimal(line_amount_raw)

        if not line_amount_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Line amount is required.",
                    "suggested_fix": "Provide a valid line amount.",
                }
            )
        elif line_amount is None:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_AMOUNT,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Line amount '{line_amount_raw}' is not a valid number.",
                    "suggested_fix": "Use a numeric value for the amount.",
                }
            )
        elif line_amount < 0:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_AMOUNT,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Line amount must be zero or greater.",
                    "suggested_fix": "Provide a non-negative amount.",
                }
            )
        else:
            normalized_data["line_amount"] = str(line_amount)

        # Quantity / unit price cross-check (warning only)
        qty_raw = mapped_data.get("quantity", "").strip()
        unit_price_raw = mapped_data.get("unit_price", "").strip()
        qty = parse_decimal(qty_raw)
        unit_price = parse_decimal(unit_price_raw)

        if qty is not None and qty <= 0:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_AMOUNT,
                    "severity": MigrationSeverityChoices.WARNING,
                    "description": "Quantity must be greater than zero.",
                    "suggested_fix": "Provide a positive quantity value.",
                }
            )
        if qty and unit_price and line_amount:
            calculated = qty * unit_price
            if abs(calculated - line_amount) > Decimal("0.01"):
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.AMOUNT_MISMATCH,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Qty ({qty}) × Unit Price ({unit_price}) = {calculated}, but Amount is {line_amount}.",
                        "suggested_fix": "Check quantity, unit price, or amount for consistency.",
                    }
                )

        if qty:
            normalized_data["quantity"] = str(qty)
        if unit_price:
            normalized_data["unit_price"] = str(unit_price)

        # --- Product validation ---
        product_name = mapped_data.get("product_service", "").strip()
        income_account_name = mapped_data.get("income_account", "").strip()
        resolved_product = None
        resolved_income_account = None

        if product_name:
            resolved_product = (
                Product.objects.filter(
                    title__iexact=product_name,
                    company=company,
                )
                .exclude(status=ProductStatusChoices.REMOVED)
                .first()
            )

            if resolved_product:
                normalized_data["product_uid"] = str(resolved_product.uid)
                normalized_data["product_id"] = resolved_product.id
                if not resolved_product.income_account:
                    issues.append(
                        {
                            "issue_type": MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
                            "severity": MigrationSeverityChoices.ERROR,
                            "description": f"Product '{product_name}' exists but has no income account assigned.",
                            "suggested_fix": "Assign an income account to this product or map an income account manually.",
                        }
                    )
                else:
                    normalized_data["income_account_id"] = (
                        resolved_product.income_account.id
                    )
                    normalized_data["income_account_uid"] = str(
                        resolved_product.income_account.uid
                    )
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.PRODUCT_NOT_FOUND,
                        "severity": MigrationSeverityChoices.ERROR,
                        "description": f"Product '{product_name}' does not exist in this company.",
                        "suggested_fix": "Map this row to an existing product.",
                    }
                )
        elif not income_account_name:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Either a product/service or an income account is required.",
                    "suggested_fix": "Provide a product name or income account.",
                }
            )

        # --- Income account override ---
        if income_account_name:
            resolved_income_account = ChartOfAccount.objects.filter(
                title__iexact=income_account_name,
                company=company,
            ).first()
            if resolved_income_account:
                normalized_data["income_account_id"] = resolved_income_account.id
                normalized_data["income_account_uid"] = str(
                    resolved_income_account.uid
                )
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.INCOME_ACCOUNT_NOT_FOUND,
                        "severity": MigrationSeverityChoices.ERROR,
                        "description": f"Income account '{income_account_name}' does not exist in this company.",
                        "suggested_fix": "Map a valid income account.",
                    }
                )

        # --- Tax validation (warning if not found) ---
        tax_code = mapped_data.get("tax_code", "").strip()
        if tax_code:
            resolved_tax = AgencyTax.objects.filter(
                Q(title__iexact=tax_code),
                company=company,
            ).first()
            if resolved_tax:
                normalized_data["tax_uid"] = str(resolved_tax.uid)
                normalized_data["tax_id"] = resolved_tax.id
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.TAX_NOT_FOUND,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Tax '{tax_code}' was not found in this company.",
                        "suggested_fix": "Map a valid tax code or leave blank.",
                    }
                )

        # --- Warehouse/location validation (warning if not found) ---
        warehouse_name = mapped_data.get("warehouse", "").strip()
        if warehouse_name:
            resolved_warehouse = Warehouse.objects.filter(
                title__iexact=warehouse_name,
                company=company,
            ).first()
            if resolved_warehouse:
                normalized_data["warehouse_uid"] = str(resolved_warehouse.uid)
                normalized_data["warehouse_id"] = resolved_warehouse.id
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Location/Warehouse '{warehouse_name}' was not found in this company.",
                        "suggested_fix": "Map a valid location/warehouse or leave blank.",
                    }
                )

        # --- Term validation (warning if not found) ---
        term_name = mapped_data.get("term", "").strip()
        if term_name:
            resolved_term = Term.objects.filter(
                title__iexact=term_name,
                company=company,
            ).first()
            if resolved_term:
                normalized_data["term_uid"] = str(resolved_term.uid)
                normalized_data["term_id"] = resolved_term.id
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.TERM_NOT_FOUND,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Payment term '{term_name}' was not found.",
                        "suggested_fix": "Map a valid payment term or leave blank.",
                    }
                )

        # --- Duplicate invoice check ---
        is_duplicate = False
        if resolved_customer and invoice_number:
            is_duplicate = (
                Sale.objects.filter(
                    company=company,
                    customer_id=resolved_customer.id,
                    is_invoice=True,
                )
                .filter(
                    Q(invoice_id=invoice_number)
                    | Q(tracking_number=invoice_number)
                    | Q(reference_number=invoice_number)
                )
                .exists()
            )

            if is_duplicate:
                if (
                    job.duplicate_handling
                    == MigrationDuplicateHandlingChoices.SKIP_DUPLICATES
                ):
                    issues.append(
                        {
                            "issue_type": MigrationIssueTypeChoices.DUPLICATE_INVOICE,
                            "severity": MigrationSeverityChoices.DUPLICATE,
                            "description": f"Invoice '{invoice_number}' already exists for this customer.",
                            "suggested_fix": "Skip duplicate or update the existing invoice manually.",
                        }
                    )

        # --- Determine row status ---
        has_error = any(
            i["severity"] == MigrationSeverityChoices.ERROR for i in issues
        )
        has_duplicate = any(
            i["severity"] == MigrationSeverityChoices.DUPLICATE for i in issues
        )
        has_warning = any(
            i["severity"] == MigrationSeverityChoices.WARNING for i in issues
        )

        if has_duplicate:
            row.status = MigrationRowStatusChoices.SKIPPED
        elif has_error:
            row.status = MigrationRowStatusChoices.ERROR
        elif has_warning:
            row.status = MigrationRowStatusChoices.WARNING
        else:
            row.status = MigrationRowStatusChoices.READY

        row.error_count = sum(
            1 for i in issues if i["severity"] == MigrationSeverityChoices.ERROR
        )
        row.warning_count = sum(
            1 for i in issues if i["severity"] == MigrationSeverityChoices.WARNING
        )
        row.duplicate_count = sum(
            1 for i in issues if i["severity"] == MigrationSeverityChoices.DUPLICATE
        )
        row.normalized_data = normalized_data
        row.save(
            update_fields=[
                "status",
                "error_count",
                "warning_count",
                "duplicate_count",
                "mapped_data",
                "normalized_data",
                "updated_at",
            ]
        )

        # Bulk-create issues for this row
        issue_objs = [
            DataMigrationValidationIssue(
                job=job,
                row=row,
                issue_type=i["issue_type"],
                severity=i["severity"],
                description=i["description"],
                suggested_fix=i.get("suggested_fix", ""),
            )
            for i in issues
        ]
        if issue_objs:
            DataMigrationValidationIssue.objects.bulk_create(issue_objs)

        if counters is not None:
            increment_row_status_counter(counters, row)

        return row
