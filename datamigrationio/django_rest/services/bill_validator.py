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

from supplierio.models import Supplier
from supplierio.choices import SupplierStatusChoices
from productio.models import Product
from productio.choices import ProductStatusChoices
from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices
from agencyio.models import AgencyTax
from wirehouseio.models import Warehouse
from purchaseio.models import Purchase

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


class BillValidatorService:
    @staticmethod
    def validate_job(job, company):
        mappings = list(job.field_mappings.all())
        rows = job.rows.all()

        DataMigrationValidationIssue.objects.filter(job=job, is_resolved=False).delete()

        counters = {
            "ready": 0,
            "warning": 0,
            "error": 0,
            "duplicate": 0,
            "skipped": 0,
        }

        for row in rows:
            BillValidatorService.validate_row(
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
    def validate_row(row, job, company, mappings, counters=None, remap_from_raw=True):
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

        # --- Vendor validation ---
        vendor_name = mapped_data.get("vendor", "").strip()
        vendor_email = mapped_data.get("vendor_email", "").strip()
        resolved_supplier = None

        if vendor_email:
            resolved_supplier = (
                Supplier.objects.filter(
                    email__iexact=vendor_email,
                    company=company,
                )
                .exclude(status=SupplierStatusChoices.REMOVED)
                .first()
            )

        if not resolved_supplier and vendor_name:
            name_parts = vendor_name.split()
            first_part = name_parts[0] if name_parts else ""
            last_part = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            name_filter = (
                Q(display_name__iexact=vendor_name)
                | Q(company_name__iexact=vendor_name)
                | Q(first_name__iexact=vendor_name)
                | Q(last_name__iexact=vendor_name)
            )
            if first_part and last_part:
                name_filter |= Q(
                    first_name__iexact=first_part,
                    last_name__iexact=last_part,
                )

            resolved_supplier = (
                Supplier.objects.filter(name_filter, company=company)
                .exclude(status=SupplierStatusChoices.REMOVED)
                .first()
            )

        if resolved_supplier:
            normalized_data["supplier_uid"] = str(resolved_supplier.uid)
            normalized_data["supplier_id"] = resolved_supplier.id
            normalized_data["supplier_name"] = (
                resolved_supplier.display_name
                or resolved_supplier.company_name
                or vendor_name
            )
            normalized_data["supplier_email"] = resolved_supplier.email or vendor_email
        elif not vendor_name and not vendor_email:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Vendor name or email is required.",
                    "suggested_fix": "Provide a vendor name or email in the mapped data.",
                }
            )
        else:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.VENDOR_NOT_FOUND,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Vendor '{vendor_name or vendor_email}' does not exist in this company.",
                    "suggested_fix": "Map this row to an existing vendor before import.",
                }
            )

        # --- Bill number validation ---
        bill_number = mapped_data.get("bill_number", "").strip()
        if not bill_number:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Bill number is required.",
                    "suggested_fix": "Provide a bill number.",
                }
            )

        # --- Date validation ---
        bill_date_raw = mapped_data.get("bill_date", "").strip()
        due_date_raw = mapped_data.get("due_date", "").strip()
        bill_date = parse_date(bill_date_raw, job.date_format)
        due_date = parse_date(due_date_raw, job.date_format) if due_date_raw else None

        if not bill_date_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Bill date is required.",
                    "suggested_fix": "Provide a valid bill date.",
                }
            )
        elif bill_date is None:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Bill date '{bill_date_raw}' could not be parsed with format {job.date_format}.",
                    "suggested_fix": f"Use date format {job.date_format}.",
                }
            )
        else:
            normalized_data["bill_date"] = str(bill_date)

        if due_date_raw:
            if due_date is None:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Due date '{due_date_raw}' could not be parsed with format {job.date_format}.",
                        "suggested_fix": f"Use date format {job.date_format} or leave blank.",
                    }
                )
            elif bill_date and due_date < bill_date:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": "Due date cannot be before bill date.",
                        "suggested_fix": "Correct the due date.",
                    }
                )
            else:
                normalized_data["due_date"] = str(due_date)

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

        # --- Line type branching (product vs expense) ---
        line_type = mapped_data.get("line_type", "").strip().lower()
        if not line_type:
            line_type = "expense"

        product_uid_raw = mapped_data.get("product_uid", "").strip()
        product_name = mapped_data.get("product_service", "").strip()
        expense_account_name = mapped_data.get("expense_account", "").strip()
        expense_account_uid_raw = mapped_data.get("expense_account_uid", "").strip()
        resolved_product = None
        resolved_expense_account = None

        if line_type == "product":
            normalized_data["line_kind"] = "PRODUCT"

            if product_uid_raw:
                resolved_product = (
                    Product.objects.filter(uid=product_uid_raw, company=company)
                    .exclude(status=ProductStatusChoices.REMOVED)
                    .first()
                )

            if not resolved_product and product_name:
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
            elif product_name or product_uid_raw:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.PRODUCT_NOT_FOUND,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Product '{product_name or product_uid_raw}' does not exist in this company.",
                        "suggested_fix": "Map this row to an existing product or leave blank for a description-only line.",
                    }
                )
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": "No product provided for this product line.",
                        "suggested_fix": "Provide a product name or set Line Type to expense with an expense account.",
                    }
                )
        else:
            normalized_data["line_kind"] = "EXPENSE"

            if expense_account_uid_raw:
                resolved_expense_account = ChartOfAccount.objects.filter(
                    uid=expense_account_uid_raw,
                    company=company,
                    status=ChartOfAccountStatusChoices.ACTIVE,
                ).first()

            if not resolved_expense_account and expense_account_name:
                resolved_expense_account = ChartOfAccount.objects.filter(
                    title__iexact=expense_account_name,
                    company=company,
                    status=ChartOfAccountStatusChoices.ACTIVE,
                ).first()

            if resolved_expense_account:
                normalized_data["expense_account_id"] = resolved_expense_account.id
                normalized_data["expense_account_uid"] = str(
                    resolved_expense_account.uid
                )
            elif expense_account_name or expense_account_uid_raw:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.EXPENSE_ACCOUNT_NOT_FOUND,
                        "severity": MigrationSeverityChoices.ERROR,
                        "description": f"Expense account '{expense_account_name or expense_account_uid_raw}' does not exist in this company.",
                        "suggested_fix": "Map a valid expense account.",
                    }
                )
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": "Expense line type requires an expense account.",
                        "suggested_fix": "Provide an expense account name or UID.",
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

        # --- Warehouse validation (warning if not found) ---
        warehouse_name = mapped_data.get("warehouse", "").strip()
        warehouse_uid_raw = mapped_data.get("warehouse_uid", "").strip()
        resolved_warehouse = None

        if warehouse_uid_raw:
            resolved_warehouse = Warehouse.objects.filter(
                uid=warehouse_uid_raw,
                company=company,
            ).first()

        if not resolved_warehouse and warehouse_name:
            resolved_warehouse = Warehouse.objects.filter(
                title__iexact=warehouse_name,
                company=company,
            ).first()

        if resolved_warehouse:
            normalized_data["warehouse_uid"] = str(resolved_warehouse.uid)
            normalized_data["warehouse_id"] = resolved_warehouse.id
        elif warehouse_name or warehouse_uid_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND,
                    "severity": MigrationSeverityChoices.WARNING,
                    "description": f"Location/Warehouse '{warehouse_name or warehouse_uid_raw}' was not found in this company.",
                    "suggested_fix": "Map a valid location/warehouse or leave blank.",
                }
            )

        # --- Duplicate bill check ---
        if resolved_supplier and bill_number:
            is_duplicate = (
                Purchase.objects.filter(
                    company=company,
                    supplier_id=resolved_supplier.id,
                    is_bill=True,
                )
                .filter(
                    Q(purchase_id=bill_number)
                    | Q(tracking_number=bill_number)
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
                            "issue_type": MigrationIssueTypeChoices.DUPLICATE_BILL,
                            "severity": MigrationSeverityChoices.DUPLICATE,
                            "description": f"Bill '{bill_number}' already exists for this vendor.",
                            "suggested_fix": "Skip duplicate or update the existing bill manually.",
                        }
                    )

        # --- Determine row status ---
        has_error = any(i["severity"] == MigrationSeverityChoices.ERROR for i in issues)
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
