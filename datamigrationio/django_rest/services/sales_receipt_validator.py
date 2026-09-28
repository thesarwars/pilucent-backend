from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from datamigrationio.models import DataMigrationValidationIssue
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
from salesio.choices import SaleReceptKindChoices

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


class SalesReceiptValidatorService:
    @staticmethod
    def validate_job(job, company):
        """
        Validate all rows for a sales-receipt migration job.
        Mirrors invoice validation but uses receipt_number / receipt_date and
        optional deposit account resolution.
        """

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
            SalesReceiptValidatorService.validate_row(
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

        # --- Receipt number ---
        receipt_number = mapped_data.get("receipt_number", "").strip()
        if not receipt_number:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Receipt number is required.",
                    "suggested_fix": "Provide a receipt number.",
                }
            )

        # --- Receipt date ---
        receipt_date_raw = mapped_data.get("receipt_date", "").strip()
        receipt_date = parse_date(receipt_date_raw, job.date_format)

        if not receipt_date_raw:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Receipt date is required.",
                    "suggested_fix": "Provide a valid receipt date.",
                }
            )
        elif receipt_date is None:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.INVALID_DATE,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": f"Receipt date '{receipt_date_raw}' could not be parsed with format {job.date_format}.",
                    "suggested_fix": f"Use date format {job.date_format}.",
                }
            )
        else:
            normalized_data["receipt_date"] = str(receipt_date)

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

        # --- Product validation ---
        product_name = mapped_data.get("product_service", "").strip()
        product_uid_str = mapped_data.get("product_uid", "").strip()
        income_account_name = mapped_data.get("income_account", "").strip()
        resolved_product = None
        resolved_income_account = None

        if product_uid_str:
            resolved_product = (
                Product.objects.filter(
                    uid=product_uid_str,
                    company=company,
                )
                .exclude(status=ProductStatusChoices.REMOVED)
                .first()
            )
            if not resolved_product:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.PRODUCT_NOT_FOUND,
                        "severity": MigrationSeverityChoices.ERROR,
                        "description": f"Product with UID '{product_uid_str}' does not exist in this company.",
                        "suggested_fix": "Map a valid product UID or product name.",
                    }
                )
            else:
                normalized_data["product_uid"] = str(resolved_product.uid)
                normalized_data["product_id"] = resolved_product.id
                if not resolved_product.income_account:
                    issues.append(
                        {
                            "issue_type": MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
                            "severity": MigrationSeverityChoices.ERROR,
                            "description": f"Product '{resolved_product.title}' exists but has no income account assigned.",
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
        elif not resolved_product and not income_account_name:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
                    "severity": MigrationSeverityChoices.ERROR,
                    "description": "Either a product/service or an income account is required.",
                    "suggested_fix": "Provide a product name, product UID, or income account.",
                }
            )

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

        # --- Tax validation ---
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

        tax_uid_str = mapped_data.get("tax_uid", "").strip()
        if tax_uid_str and not normalized_data.get("tax_uid"):
            resolved_tax = AgencyTax.objects.filter(
                uid=tax_uid_str,
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
                        "description": f"Tax UID '{tax_uid_str}' was not found in this company.",
                        "suggested_fix": "Map a valid tax UID or leave blank.",
                    }
                )

        # --- Warehouse ---
        warehouse_name = mapped_data.get("warehouse", "").strip()
        warehouse_uid_str = mapped_data.get("warehouse_uid", "").strip()
        if warehouse_uid_str:
            resolved_wh = Warehouse.objects.filter(
                uid=warehouse_uid_str,
                company=company,
            ).first()
            if resolved_wh:
                normalized_data["warehouse_uid"] = str(resolved_wh.uid)
                normalized_data["warehouse_id"] = resolved_wh.id
            else:
                issues.append(
                    {
                        "issue_type": MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND,
                        "severity": MigrationSeverityChoices.WARNING,
                        "description": f"Location UID '{warehouse_uid_str}' was not found.",
                        "suggested_fix": "Map a valid location UID or leave blank.",
                    }
                )
        elif warehouse_name:
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

        # --- Term (optional) ---
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

        # --- Deposit account (optional; fallback Undeposited Funds at import) ---
        deposit_account_name = mapped_data.get("deposit_account", "").strip()
        deposit_account_uid_str = mapped_data.get("deposit_account_uid", "").strip()
        resolved_deposit = None
        if deposit_account_uid_str:
            resolved_deposit = ChartOfAccount.objects.filter(
                uid=deposit_account_uid_str,
                company=company,
            ).first()
        if not resolved_deposit and deposit_account_name:
            resolved_deposit = ChartOfAccount.objects.filter(
                title__iexact=deposit_account_name,
                company=company,
            ).first()
        if resolved_deposit:
            normalized_data["deposit_account_id"] = resolved_deposit.id
            normalized_data["deposit_account_uid"] = str(resolved_deposit.uid)
        elif deposit_account_uid_str or deposit_account_name:
            issues.append(
                {
                    "issue_type": MigrationIssueTypeChoices.DEPOSIT_ACCOUNT_NOT_FOUND,
                    "severity": MigrationSeverityChoices.WARNING,
                    "description": "Deposit account not found; Undeposited Funds will be used at import.",
                    "suggested_fix": "Map a valid deposit account name or UID, or leave blank to use Undeposited Funds.",
                }
            )

        # --- Duplicate receipt ---
        if resolved_customer and receipt_number:
            is_duplicate = Sale.objects.filter(
                company=company,
                customer_id=resolved_customer.id,
                is_sale_receipt=True,
                kind=SaleReceptKindChoices.SALE,
            ).filter(
                Q(invoice_id=receipt_number)
                | Q(tracking_number=receipt_number)
                | Q(reference_number=receipt_number)
            ).exists()

            if is_duplicate:
                if (
                    job.duplicate_handling
                    == MigrationDuplicateHandlingChoices.SKIP_DUPLICATES
                ):
                    issues.append(
                        {
                            "issue_type": MigrationIssueTypeChoices.DUPLICATE_SALE_RECEIPT,
                            "severity": MigrationSeverityChoices.DUPLICATE,
                            "description": f"Receipt '{receipt_number}' already exists for this customer.",
                            "suggested_fix": "Skip duplicate or update the existing receipt manually.",
                        }
                    )

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
