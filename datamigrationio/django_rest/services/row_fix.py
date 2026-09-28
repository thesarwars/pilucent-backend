import uuid
from datetime import datetime
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from customerio.models import Customer
from customerio.choices import CustomerStatusChoices
from categoryio.models import Category
from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices

from supplierio.models import Supplier
from supplierio.choices import SupplierStatusChoices
from productio.models import Product
from paymentio.models import PaymentMethod
from paymentio.choices import PaymentMethodStatusChoices
from productio.choices import ProductStatusChoices
from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices
from agencyio.models import AgencyTax
from wirehouseio.models import Warehouse
from termio.models import Term

from datamigrationio.models import DataMigrationRow
from datamigrationio.choices import MigrationIssueTypeChoices, MigrationSeverityChoices
from datamigrationio.django_rest.services.invoice_validator import (
    InvoiceValidatorService,
)
from datamigrationio.django_rest.services.estimate_validator import (
    EstimateValidatorService,
)
from datamigrationio.django_rest.services.sales_receipt_validator import (
    SalesReceiptValidatorService,
)
from datamigrationio.django_rest.services.purchase_order_validator import (
    PurchaseOrderValidatorService,
)
from datamigrationio.django_rest.services.bill_validator import (
    BillValidatorService,
)
from datamigrationio.django_rest.services.check_validator import (
    CheckValidatorService,
)
from datamigrationio.django_rest.services.expense_validator import (
    ExpenseValidatorService,
)
from datamigrationio.django_rest.services.chart_of_account_validator import (
    ChartOfAccountValidatorService,
)
from datamigrationio.django_rest.services.employee_validator import (
    EmployeeValidatorService,
    EMAIL_RE,
    _parse_date as _employee_parse_date,
)
from companyio.choices import CompanyDepartmentStatusChoices, CompanyDesignationStatusChoices
from companyio.models import CompanyDepartment, CompanyDesignation
from employeeio.choices import EmployeeKindChoices
from datamigrationio.django_rest.services.migration_job_counters import (
    refresh_job_row_counters,
)
from datamigrationio.django_rest.services.expense_validator import (
    parse_date,
)

VALIDATOR_BY_DATA_TYPE = {
    "invoices": InvoiceValidatorService,
    "estimates": EstimateValidatorService,
    "sales_receipts": SalesReceiptValidatorService,
    "purchase_orders": PurchaseOrderValidatorService,
    "bills": BillValidatorService,
    "checks": CheckValidatorService,
    "expenses": ExpenseValidatorService,
    "chart_of_accounts": ChartOfAccountValidatorService,
    "employees": EmployeeValidatorService,
}

FIELD_ISSUE_TYPES = {
    # UID variants — customer
    "customer_uid": [MigrationIssueTypeChoices.CUSTOMER_NOT_FOUND],
    # UID variants — vendor/supplier
    "vendor_uid": [MigrationIssueTypeChoices.VENDOR_NOT_FOUND],
    # UID variants — product
    "product_uid": [
        MigrationIssueTypeChoices.PRODUCT_NOT_FOUND,
        MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
    ],
    # UID variants — accounts
    "income_account_uid": [
        MigrationIssueTypeChoices.INCOME_ACCOUNT_NOT_FOUND,
        MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
    ],
    "expense_account_uid": [MigrationIssueTypeChoices.EXPENSE_ACCOUNT_NOT_FOUND],
    "bank_account_uid": [MigrationIssueTypeChoices.BANK_ACCOUNT_NOT_FOUND],
    "tax_uid": [MigrationIssueTypeChoices.TAX_NOT_FOUND],
    "warehouse_uid": [MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND],
    "term_uid": [MigrationIssueTypeChoices.TERM_NOT_FOUND],
    "deposit_account_uid": [MigrationIssueTypeChoices.DEPOSIT_ACCOUNT_NOT_FOUND],
    # Amount mismatch (qty × unit_price ≠ line_amount)
    "amount_mismatch": [MigrationIssueTypeChoices.AMOUNT_MISMATCH],
    # Name / title variants — customer
    "customer": [MigrationIssueTypeChoices.CUSTOMER_NOT_FOUND],
    # Name / title variants — vendor/supplier
    "vendor": [
        MigrationIssueTypeChoices.VENDOR_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "vendor_email": [
        MigrationIssueTypeChoices.VENDOR_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    # Name / title variants — product
    "product_service": [
        MigrationIssueTypeChoices.PRODUCT_NOT_FOUND,
        MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    # Name / title variants — accounts
    "income_account": [
        MigrationIssueTypeChoices.INCOME_ACCOUNT_NOT_FOUND,
        MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING,
    ],
    "expense_account": [
        MigrationIssueTypeChoices.EXPENSE_ACCOUNT_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "bank_account": [
        MigrationIssueTypeChoices.BANK_ACCOUNT_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "payment_account": [
        MigrationIssueTypeChoices.PAYMENT_ACCOUNT_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "payment_account_uid": [MigrationIssueTypeChoices.PAYMENT_ACCOUNT_NOT_FOUND],
    "tax_code": [MigrationIssueTypeChoices.TAX_NOT_FOUND],
    "warehouse": [MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND],
    "term": [MigrationIssueTypeChoices.TERM_NOT_FOUND],
    "deposit_account": [MigrationIssueTypeChoices.DEPOSIT_ACCOUNT_NOT_FOUND],
    # Duplicate fields
    "duplicate_invoice": [MigrationIssueTypeChoices.DUPLICATE_INVOICE],
    "duplicate_sale_receipt": [MigrationIssueTypeChoices.DUPLICATE_SALE_RECEIPT],
    "duplicate_estimate": [MigrationIssueTypeChoices.DUPLICATE_ESTIMATE],
    "duplicate_purchase_order": [MigrationIssueTypeChoices.DUPLICATE_PURCHASE_ORDER],
    "duplicate_bill": [MigrationIssueTypeChoices.DUPLICATE_BILL],
    "duplicate_check": [MigrationIssueTypeChoices.DUPLICATE_CHECK],
    "duplicate_expense": [MigrationIssueTypeChoices.DUPLICATE_EXPENSE],
    "duplicate_chart_of_account": [
        MigrationIssueTypeChoices.DUPLICATE_CHART_OF_ACCOUNT
    ],
    # Issue-type fields (when frontend sends issue_type as field name)
    "invalid_date": [MigrationIssueTypeChoices.INVALID_DATE],
    "invalid_amount": [MigrationIssueTypeChoices.INVALID_AMOUNT],
    "customer_not_found": [MigrationIssueTypeChoices.CUSTOMER_NOT_FOUND],
    "vendor_not_found": [MigrationIssueTypeChoices.VENDOR_NOT_FOUND],
    "product_not_found": [MigrationIssueTypeChoices.PRODUCT_NOT_FOUND],
    "product_income_account_missing": [
        MigrationIssueTypeChoices.PRODUCT_INCOME_ACCOUNT_MISSING
    ],
    "income_account_not_found": [MigrationIssueTypeChoices.INCOME_ACCOUNT_NOT_FOUND],
    "expense_account_not_found": [MigrationIssueTypeChoices.EXPENSE_ACCOUNT_NOT_FOUND],
    "bank_account_not_found": [MigrationIssueTypeChoices.BANK_ACCOUNT_NOT_FOUND],
    "deposit_account_not_found": [MigrationIssueTypeChoices.DEPOSIT_ACCOUNT_NOT_FOUND],
    "tax_not_found": [MigrationIssueTypeChoices.TAX_NOT_FOUND],
    "warehouse_not_found": [MigrationIssueTypeChoices.WAREHOUSE_NOT_FOUND],
    "term_not_found": [MigrationIssueTypeChoices.TERM_NOT_FOUND],
    "payment_account_not_found": [MigrationIssueTypeChoices.PAYMENT_ACCOUNT_NOT_FOUND],
    "account_type_not_found": [MigrationIssueTypeChoices.ACCOUNT_TYPE_NOT_FOUND],
    "detail_type_not_found": [MigrationIssueTypeChoices.DETAIL_TYPE_NOT_FOUND],
    "missing_required_field": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    # Date fields — invoices / estimates / sales receipts
    "invoice_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "due_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "estimate_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "expiry_date": [MigrationIssueTypeChoices.INVALID_DATE],
    "receipt_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    # Date fields — purchase orders / bills / checks
    "purchase_order_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "bill_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "check_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "expense_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    # Chart of accounts type fields
    "account_type": [
        MigrationIssueTypeChoices.ACCOUNT_TYPE_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "detail_type": [
        MigrationIssueTypeChoices.DETAIL_TYPE_NOT_FOUND,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "opening_balance": [MigrationIssueTypeChoices.INVALID_AMOUNT],
    # Amount / number fields
    "line_amount": [
        MigrationIssueTypeChoices.INVALID_AMOUNT,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
        MigrationIssueTypeChoices.AMOUNT_MISMATCH,
    ],
    "invoice_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "estimate_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "receipt_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "purchase_order_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "bill_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "check_number": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    # Employee fields
    "email": [
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
        MigrationIssueTypeChoices.DUPLICATE_EMPLOYEE,
    ],
    "first_name": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "last_name": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "department": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "department_uid": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "designation": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "designation_uid": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "joining_date": [
        MigrationIssueTypeChoices.INVALID_DATE,
        MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD,
    ],
    "date_of_birth": [MigrationIssueTypeChoices.INVALID_DATE],
    "employment_type": [MigrationIssueTypeChoices.MISSING_REQUIRED_FIELD],
    "duplicate_employee": [MigrationIssueTypeChoices.DUPLICATE_EMPLOYEE],
}


class RowFixService:
    @staticmethod
    def _is_valid_uuid(value):
        try:
            uuid.UUID(str(value))
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def resolve_missing_field_targets(row):
        """Return all possible target fields from unresolved missing_required_field issues."""
        DESCRIPTION_TO_FIELD = {
            "vendor name": "vendor",
            "vendor": "vendor",
            "customer name": "customer",
            "customer": "customer",
            "bill number": "bill_number",
            "bill date": "bill_date",
            "invoice number": "invoice_number",
            "invoice date": "invoice_date",
            "receipt number": "receipt_number",
            "receipt date": "receipt_date",
            "estimate number": "estimate_number",
            "estimate date": "estimate_date",
            "purchase order number": "purchase_order_number",
            "purchase order date": "purchase_order_date",
            "check number": "check_number",
            "check date": "check_date",
            "expense date": "expense_date",
            "line amount": "line_amount",
            "product": "product_service",
            "expense account": "expense_account",
            "account type": "account_type",
            "detail type": "detail_type",
            # Employee
            "first name": "first_name",
            "last name": "last_name",
            "email": "email",
            "department": "department",
            "designation": "designation",
            "joining date": "joining_date",
            "date of birth": "date_of_birth",
        }
        targets = []
        issues = row.issues.filter(
            is_resolved=False, issue_type="missing_required_field"
        )
        for issue in issues:
            desc_lower = issue.description.lower()
            for prefix, target_field in DESCRIPTION_TO_FIELD.items():
                if desc_lower.startswith(prefix):
                    if target_field not in targets:
                        targets.append(target_field)
                    break
        return targets

    @staticmethod
    def apply_fix(job, row, company, field, value, user, apply_to_similar=False):
        validator = VALIDATOR_BY_DATA_TYPE.get(job.data_type)
        if not validator:
            return {
                "fixed": False,
                "message": f"Row fix is not supported for data type '{job.data_type}'.",
                "field": field,
                "row": row,
            }

        value_str = "" if value is None else str(value).strip()
        if not value_str:
            return {
                "fixed": False,
                "message": "A non-empty value is required.",
                "field": field,
                "row": row,
            }

        # Determine which mapped_data key to use for similarity matching.
        # Name-based fields already equal the mapped_data key; UID fields
        # need the suffix stripped.
        FIELD_TO_MAPPED_KEY = {
            "customer_uid": "customer",
            "vendor_uid": "vendor",
            "product_uid": "product_service",
            "income_account_uid": "income_account",
            "expense_account_uid": "expense_account",
            "bank_account_uid": "bank_account",
            "payment_account_uid": "payment_account",
            "tax_uid": "tax_code",
            "warehouse_uid": "warehouse",
            "term_uid": "term",
            "deposit_account_uid": "deposit_account",
            "amount_mismatch": "line_amount",
            "duplicate_sale_receipt": "receipt_number",
            "duplicate_invoice": "invoice_number",
            "duplicate_estimate": "estimate_number",
            "duplicate_purchase_order": "purchase_order_number",
            "duplicate_bill": "bill_number",
            "duplicate_check": "check_number",
            "duplicate_expense": "reference_number",
            "duplicate_chart_of_account": "account_name",
            # Employee
            "duplicate_employee": "email",
            "department_uid": "department",
            "designation_uid": "designation",
        }

        # When field is "missing_required_field" and there are multiple such
        # issues, try each resolved target field until one accepts the value.
        if field == "missing_required_field":
            targets = RowFixService.resolve_missing_field_targets(row)
            if targets:
                first_error = None
                for target_field in targets:
                    row.refresh_from_db()
                    err = RowFixService.apply_field_value(
                        row, target_field, value_str, company
                    )
                    if not err:
                        field = target_field
                        first_error = None
                        break
                    if first_error is None:
                        first_error = err
                if first_error:
                    return {
                        "fixed": False,
                        "message": first_error,
                        "field": field,
                        "row": row,
                    }
            else:
                apply_error = RowFixService.apply_field_value(
                    row, field, value_str, company
                )
                if apply_error:
                    return {
                        "fixed": False,
                        "message": apply_error,
                        "field": field,
                        "row": row,
                    }
        else:
            apply_error = RowFixService.apply_field_value(
                row, field, value_str, company
            )
            if apply_error:
                return {
                    "fixed": False,
                    "message": apply_error,
                    "field": field,
                    "row": row,
                }

        field_to_match = FIELD_TO_MAPPED_KEY.get(field, field)
        original_mapped_value = (row.mapped_data or {}).get(field_to_match, "")

        row.save(update_fields=["mapped_data", "normalized_data", "updated_at"])

        mappings = list(job.field_mappings.all())
        validator.validate_row(
            row, job, company, mappings, counters=None, remap_from_raw=False
        )
        refresh_job_row_counters(job)
        row.refresh_from_db()

        field_issues = RowFixService.field_related_issues(row, field)
        if field_issues.exists():
            issue = field_issues.first()
            return {
                "fixed": False,
                "message": issue.description,
                "field": field,
                "suggested_fix": issue.suggested_fix or "",
                "row": row,
            }

        similar_fixed = []
        if apply_to_similar and original_mapped_value:
            similar_fixed = RowFixService.apply_to_similar_rows(
                job=job,
                source_row=row,
                field=field,
                value=value_str,
                company=company,
                validator=validator,
                mappings=mappings,
                match_mapped_value=original_mapped_value,
                match_mapped_field=field_to_match,
            )

        message = f"'{field}' was updated and validated successfully."
        if similar_fixed:
            message = (
                f"'{field}' was updated successfully for this row and "
                f"{len(similar_fixed)} similar row(s)."
            )

        return {
            "fixed": True,
            "message": message,
            "field": field,
            "similar_rows_fixed": len(similar_fixed),
            "row": row,
        }

    FIELD_DESCRIPTION_PREFIX = {
        "department": "department",
        "department_uid": "department",
        "designation": "designation",
        "designation_uid": "designation",
        "first_name": "first name",
        "last_name": "last name",
        "email": "email",
        "joining_date": "joining date",
        "date_of_birth": "date of birth",
        "employment_type": "employment type",
    }

    @staticmethod
    def field_related_issues(row, field):
        issue_types = FIELD_ISSUE_TYPES.get(field, [])
        qs = row.issues.filter(is_resolved=False)
        if issue_types:
            candidates = qs.filter(issue_type__in=issue_types)
            prefix = RowFixService.FIELD_DESCRIPTION_PREFIX.get(field)
            if prefix:
                candidates = candidates.filter(
                    description__istartswith=prefix
                )
            return candidates
        return qs.filter(severity=MigrationSeverityChoices.ERROR)

    @staticmethod
    def apply_field_value(row, field, value, company):
        """
        Write the corrected value into mapped_data / normalized_data.

        Accepts both UID-style fields (e.g. ``customer_uid``) and
        name/title-style fields (e.g. ``customer``, ``product_service``).
        For reference fields the value is resolved against the database so
        downstream re-validation can succeed; if the lookup fails a plain
        error string is returned.
        """
        # Redirect issue_type names to actual field handlers
        ISSUE_TYPE_TO_FIELD = {
            "customer_not_found": "customer",
            "vendor_not_found": "vendor",
            "product_not_found": "product_service",
            "product_income_account_missing": "income_account",
            "income_account_not_found": "income_account",
            "expense_account_not_found": "expense_account",
            "bank_account_not_found": "bank_account",
            "deposit_account_not_found": "deposit_account",
            "tax_not_found": "tax_code",
            "warehouse_not_found": "warehouse",
            "term_not_found": "term",
            "payment_account_not_found": "payment_account",
            "account_type_not_found": "account_type",
            "detail_type_not_found": "detail_type",
            "duplicate_employee": "email",
        }
        if field in ISSUE_TYPE_TO_FIELD:
            redirect_field = ISSUE_TYPE_TO_FIELD[field]
            if redirect_field:
                field = redirect_field

        mapped = dict(row.mapped_data or {})
        normalized = dict(row.normalized_data or {})

        def resolve_customer(lookup):
            """Try UID first, then e-mail, then name variants."""
            qs = Customer.objects.filter(company=company).exclude(
                status=CustomerStatusChoices.REMOVED
            )
            # Try as UID
            if RowFixService._is_valid_uuid(lookup):
                customer = qs.filter(uid=lookup).first()
                if customer:
                    return customer
            # Try as e-mail
            customer = qs.filter(email__iexact=lookup).first()
            if customer:
                return customer
            # Try name variants
            name_parts = lookup.split()
            first_part = name_parts[0] if name_parts else ""
            last_part = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            name_filter = (
                Q(display_name__iexact=lookup)
                | Q(company_name__iexact=lookup)
                | Q(first_name__iexact=lookup)
                | Q(last_name__iexact=lookup)
            )
            if first_part and last_part:
                name_filter |= Q(
                    first_name__iexact=first_part,
                    last_name__iexact=last_part,
                )
            return qs.filter(name_filter).first()

        def write_customer(customer):
            display = (
                customer.display_name
                or customer.company_name
                or f"{customer.first_name} {customer.last_name}".strip()
            )
            mapped["customer"] = display
            if customer.email:
                mapped["customer_email"] = customer.email
            normalized["customer_uid"] = str(customer.uid)
            normalized["customer_id"] = customer.id
            normalized["customer_name"] = display
            normalized["customer_email"] = customer.email or ""

        def resolve_product(lookup):
            qs = Product.objects.filter(company=company).exclude(
                status=ProductStatusChoices.REMOVED
            )
            if RowFixService._is_valid_uuid(lookup):
                product = qs.filter(uid=lookup).first()
                if product:
                    return product
            return qs.filter(title__iexact=lookup).first()

        def write_product(product):
            mapped["product_service"] = product.title
            mapped["product_uid"] = str(product.uid)
            normalized["product_uid"] = str(product.uid)
            normalized["product_id"] = product.id

        def resolve_vendor(lookup):
            """Try UID first, then e-mail, then name variants."""
            qs = Supplier.objects.filter(company=company).exclude(
                status=SupplierStatusChoices.REMOVED
            )
            if RowFixService._is_valid_uuid(lookup):
                supplier = qs.filter(uid=lookup).first()
                if supplier:
                    return supplier
            supplier = qs.filter(email__iexact=lookup).first()
            if supplier:
                return supplier
            name_parts = lookup.split()
            first_part = name_parts[0] if name_parts else ""
            last_part = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            name_filter = (
                Q(display_name__iexact=lookup)
                | Q(company_name__iexact=lookup)
                | Q(first_name__iexact=lookup)
                | Q(last_name__iexact=lookup)
            )
            if first_part and last_part:
                name_filter |= Q(
                    first_name__iexact=first_part,
                    last_name__iexact=last_part,
                )
            return qs.filter(name_filter).first()

        def write_vendor(supplier):
            display = (
                supplier.display_name
                or supplier.company_name
                or f"{supplier.first_name} {supplier.last_name}".strip()
            )
            mapped["vendor"] = display
            if supplier.email:
                mapped["vendor_email"] = supplier.email
            normalized["supplier_uid"] = str(supplier.uid)
            normalized["supplier_id"] = supplier.id
            normalized["supplier_name"] = display
            normalized["supplier_email"] = supplier.email or ""

        def resolve_account(lookup):
            qs = ChartOfAccount.objects.filter(
                company=company,
                status=ChartOfAccountStatusChoices.ACTIVE,
            )
            if RowFixService._is_valid_uuid(lookup):
                account = qs.filter(uid=lookup).first()
                if account:
                    return account
            return qs.filter(title__iexact=lookup).first()

        # --- customer / customer_uid ---
        if field in ("customer", "customer_uid"):
            customer = resolve_customer(value)
            if not customer:
                return (
                    f"Customer '{value}' does not exist in this company. "
                    "Please provide an exact name, email, or valid UID."
                )
            write_customer(customer)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- vendor / vendor_uid / vendor_email ---
        if field in ("vendor", "vendor_uid", "vendor_email"):
            supplier = resolve_vendor(value)
            if not supplier:
                return (
                    f"Vendor '{value}' does not exist in this company. "
                    "Please provide an exact name, email, or valid UID."
                )
            write_vendor(supplier)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- product_service / product_uid ---
        if field in ("product_service", "product_uid"):
            product = resolve_product(value)
            if not product:
                return (
                    f"Product '{value}' does not exist in this company. "
                    "Please provide an exact product name or valid UID."
                )
            write_product(product)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- income_account / income_account_uid ---
        if field in ("income_account", "income_account_uid"):
            account = resolve_account(value)
            if not account:
                return (
                    f"Income account '{value}' does not exist in this company. "
                    "Please provide an exact account name or valid UID."
                )
            mapped["income_account"] = account.title
            normalized["income_account_uid"] = str(account.uid)
            normalized["income_account_id"] = account.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- expense_account / expense_account_uid ---
        if field in ("expense_account", "expense_account_uid"):
            account = resolve_account(value)
            if not account:
                return (
                    f"Expense account '{value}' does not exist in this company. "
                    "Please provide an exact account name or valid UID."
                )
            mapped["expense_account"] = account.title
            mapped["expense_account_uid"] = str(account.uid)
            normalized["expense_account_uid"] = str(account.uid)
            normalized["expense_account_id"] = account.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- bank_account / bank_account_uid ---
        if field in ("bank_account", "bank_account_uid"):
            account = resolve_account(value)
            if not account:
                return (
                    f"Bank account '{value}' does not exist in this company. "
                    "Please provide an exact account name or valid UID."
                )
            mapped["bank_account"] = account.title
            mapped["bank_account_uid"] = str(account.uid)
            normalized["bank_account_uid"] = str(account.uid)
            normalized["bank_account_id"] = account.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- payment_account / payment_account_uid (expenses) ---
        if field in ("payment_account", "payment_account_uid"):
            account = resolve_account(value)
            if not account:
                return (
                    f"Payment account '{value}' does not exist in this company. "
                    "Please provide an exact account name or valid UID."
                )
            mapped["payment_account"] = account.title
            mapped["payment_account_uid"] = str(account.uid)
            normalized["payment_account_uid"] = str(account.uid)
            normalized["payment_account_id"] = account.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- payment_method (expenses) ---
        if field == "payment_method":

            pm = None
            if RowFixService._is_valid_uuid(value):
                pm = PaymentMethod.objects.filter(
                    uid=value, status=PaymentMethodStatusChoices.ACTIVE
                ).first()
            if not pm:
                pm = PaymentMethod.objects.filter(
                    title__iexact=value, status=PaymentMethodStatusChoices.ACTIVE
                ).first()
            if pm:
                mapped["payment_method"] = pm.title
                normalized["payment_method_id"] = pm.id
                normalized["payment_method_uid"] = str(pm.uid)
            else:
                mapped["payment_method"] = value
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- expense_date (expenses) ---
        if field == "expense_date":

            parsed = parse_date(
                value, row.job.date_format if hasattr(row, "job") else "MM/DD/YYYY"
            )
            if not parsed:
                return (
                    f"'{value}' is not a valid expense date. "
                    "Use the format matching the job's date_format setting."
                )
            mapped["expense_date"] = value
            normalized["expense_date"] = str(parsed)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- tax_code / tax_uid ---
        if field in ("tax_code", "tax_uid"):
            qs = AgencyTax.objects.filter(company=company)
            tax = None
            if RowFixService._is_valid_uuid(value):
                tax = qs.filter(uid=value).first()
            if not tax:
                tax = qs.filter(title__iexact=value).first()
            if not tax:
                return (
                    f"Tax '{value}' was not found in this company. "
                    "Please provide an exact tax name or valid UID."
                )
            mapped["tax_code"] = tax.title
            normalized["tax_uid"] = str(tax.uid)
            normalized["tax_id"] = tax.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- warehouse / warehouse_uid ---
        if field in ("warehouse", "warehouse_uid"):
            qs = Warehouse.objects.filter(company=company)
            warehouse = None
            if RowFixService._is_valid_uuid(value):
                warehouse = qs.filter(uid=value).first()
            if not warehouse:
                warehouse = qs.filter(title__iexact=value).first()
            if not warehouse:
                return (
                    f"Location/warehouse '{value}' was not found in this company. "
                    "Please provide an exact warehouse name or valid UID."
                )
            mapped["warehouse"] = warehouse.title
            normalized["warehouse_uid"] = str(warehouse.uid)
            normalized["warehouse_id"] = warehouse.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- term / term_uid ---
        if field in ("term", "term_uid"):
            qs = Term.objects.filter(company=company)
            term = None
            if RowFixService._is_valid_uuid(value):
                term = qs.filter(uid=value).first()
            if not term:
                term = qs.filter(title__iexact=value).first()
            if not term:
                return (
                    f"Payment term '{value}' was not found. "
                    "Please provide an exact term name or valid UID."
                )
            mapped["term"] = term.title
            normalized["term_uid"] = str(term.uid)
            normalized["term_id"] = term.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- amount_mismatch (update line_amount to resolve qty × unit_price discrepancy) ---
        if field == "amount_mismatch":
            try:
                new_amount = Decimal(value)
            except (InvalidOperation, ValueError):
                return f"'{value}' is not a valid amount."
            mapped["line_amount"] = str(new_amount)
            normalized["line_amount"] = str(new_amount)
            if "amount_mismatch" in mapped:
                del mapped["amount_mismatch"]
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- deposit_account / deposit_account_uid ---
        if field in ("deposit_account", "deposit_account_uid"):
            account = resolve_account(value)
            if not account:
                return (
                    f"Deposit account '{value}' does not exist in this company. "
                    "Please provide an exact account name or valid UID."
                )
            mapped["deposit_account"] = account.title
            mapped["deposit_account_uid"] = str(account.uid)
            normalized["deposit_account_uid"] = str(account.uid)
            normalized["deposit_account_id"] = account.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- invalid_date (issue type as field — resolve to actual date field) ---
        if field == "invalid_date":

            DATE_FORMAT_MAP = {
                "MM/DD/YYYY": "%m/%d/%Y",
                "DD/MM/YYYY": "%d/%m/%Y",
                "YYYY-MM-DD": "%Y-%m-%d",
                "MM-DD-YYYY": "%m-%d-%Y",
                "DD-MM-YYYY": "%d-%m-%Y",
            }
            date_format = row.job.date_format if row.job_id else "MM/DD/YYYY"
            fmt = DATE_FORMAT_MAP.get(date_format, "%m/%d/%Y")

            try:
                parsed = datetime.strptime(value.strip(), fmt).date()
            except (ValueError, TypeError):
                return (
                    f"'{value}' is not a valid date. " f"Use the format {date_format}."
                )

            DATE_FIELD_CANDIDATES = [
                "bill_date",
                "invoice_date",
                "receipt_date",
                "estimate_date",
                "due_date",
                "expiry_date",
                "purchase_order_date",
                "check_date",
                "expense_date",
                "joining_date",
                "date_of_birth",
            ]
            target_field = None
            for candidate in DATE_FIELD_CANDIDATES:
                raw_val = mapped.get(candidate, "").strip()
                if not raw_val:
                    continue
                try:
                    datetime.strptime(raw_val, fmt).date()
                except (ValueError, TypeError):
                    target_field = candidate
                    break

            if not target_field:
                target_field = next(
                    (c for c in DATE_FIELD_CANDIDATES if c in mapped and mapped[c]),
                    None,
                )
            if not target_field:
                return (
                    "Could not determine which date field to fix. "
                    "Please specify the exact field name (e.g. 'bill_date')."
                )

            mapped[target_field] = value
            normalized[target_field] = str(parsed)
            if "invalid_date" in mapped:
                del mapped["invalid_date"]
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- invalid_amount (issue type as field — resolve to actual amount field) ---
        if field == "invalid_amount":
            try:
                new_amount = Decimal(value)
            except (InvalidOperation, ValueError):
                return f"'{value}' is not a valid amount."

            AMOUNT_FIELD_CANDIDATES = ["line_amount", "opening_balance", "unit_price"]
            target_field = None
            for candidate in AMOUNT_FIELD_CANDIDATES:
                raw_val = mapped.get(candidate, "").strip()
                if not raw_val:
                    continue
                try:
                    Decimal(raw_val)
                except (InvalidOperation, ValueError):
                    target_field = candidate
                    break

            if not target_field:
                target_field = "line_amount"

            mapped[target_field] = str(new_amount)
            normalized[target_field] = str(new_amount)
            if "invalid_amount" in mapped:
                del mapped["invalid_amount"]
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- account_type (chart of accounts migration) ---
        if field == "account_type":
            
            cat = Category.objects.filter(
                kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                status=CategoryStatusChoices.ACTIVE,
                title__iexact=value,
            ).first()
            if not cat and RowFixService._is_valid_uuid(value):
                cat = Category.objects.filter(
                    kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                    status=CategoryStatusChoices.ACTIVE,
                    uid=value,
                ).first()
            if not cat:
                return (
                    f"Account Type '{value}' was not found. "
                    "Check the 'Type and Details Type' sheet for valid values."
                )
            mapped["account_type"] = cat.title
            normalized["account_type_id"] = cat.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- detail_type (chart of accounts migration) ---
        if field == "detail_type":
            cat = Category.objects.filter(
                kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                status=CategoryStatusChoices.ACTIVE,
                title__iexact=value,
            ).first()
            if not cat and RowFixService._is_valid_uuid(value):
                cat = Category.objects.filter(
                    kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                    status=CategoryStatusChoices.ACTIVE,
                    uid=value,
                ).first()
            if not cat:
                return (
                    f"Detail Type '{value}' was not found. "
                    "Check the 'Type and Details Type' sheet for valid values."
                )
            mapped["detail_type"] = cat.title
            normalized["detail_type_id"] = cat.id
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- email (employees) ---
        if field == "email":
            if not EMAIL_RE.match(value):
                return f"'{value}' is not a valid email address."
            from accounts.models import User as _User
            if _User.objects.filter(email__iexact=value).exists():
                return (
                    f"An employee with email '{value}' already exists in the system. "
                    "Use a different email address."
                )
            mapped["email"] = value
            normalized["email"] = value
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- first_name (employees) ---
        if field == "first_name":
            if not value.strip():
                return "First Name cannot be empty."
            mapped["first_name"] = value
            normalized["first_name"] = value
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- last_name (employees) ---
        if field == "last_name":
            if not value.strip():
                return "Last Name cannot be empty."
            mapped["last_name"] = value
            normalized["last_name"] = value
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- department / department_uid (employees) ---
        if field in ("department", "department_uid"):
            dept = None
            if RowFixService._is_valid_uuid(value):
                dept = CompanyDepartment.objects.filter(
                    uid=value,
                    company=company,
                    status=CompanyDepartmentStatusChoices.ACTIVE,
                ).first()
            if not dept:
                dept = CompanyDepartment.objects.filter(
                    title__iexact=value,
                    company=company,
                    status=CompanyDepartmentStatusChoices.ACTIVE,
                ).first()
            if not dept:
                return (
                    f"Department '{value}' was not found in this company. "
                    "Please provide an exact department name or valid UID."
                )
            mapped["department"] = dept.title
            normalized["department_id"] = dept.id
            normalized["department_uid"] = str(dept.uid)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- designation / designation_uid (employees) ---
        if field in ("designation", "designation_uid"):
            desig = None
            if RowFixService._is_valid_uuid(value):
                desig = CompanyDesignation.objects.filter(
                    uid=value,
                    company=company,
                    status=CompanyDesignationStatusChoices.ACTIVE,
                ).first()
            if not desig:
                desig = CompanyDesignation.objects.filter(
                    title__iexact=value,
                    company=company,
                    status=CompanyDesignationStatusChoices.ACTIVE,
                ).first()
            if not desig:
                return (
                    f"Designation '{value}' was not found in this company. "
                    "Please provide an exact designation name or valid UID."
                )
            mapped["designation"] = desig.title
            normalized["designation_id"] = desig.id
            normalized["designation_uid"] = str(desig.uid)
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- joining_date (employees) ---
        if field == "joining_date":
            date_format = row.job.date_format if row.job_id else "MM/DD/YYYY"
            parsed = _employee_parse_date(value, date_format)
            if not parsed:
                return (
                    f"'{value}' is not a valid date. "
                    f"Use the format {date_format}."
                )
            mapped["joining_date"] = value
            normalized["joining_date"] = parsed
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- date_of_birth (employees) ---
        if field == "date_of_birth":
            date_format = row.job.date_format if row.job_id else "MM/DD/YYYY"
            parsed = _employee_parse_date(value, date_format)
            if not parsed:
                return (
                    f"'{value}' is not a valid date. "
                    f"Use the format {date_format}."
                )
            mapped["date_of_birth"] = value
            normalized["date_of_birth"] = parsed
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- employment_type (employees) ---
        if field == "employment_type":
            VALID_KINDS = {c.upper() for c in EmployeeKindChoices.values}
            resolved = value.strip().upper()
            if resolved not in VALID_KINDS:
                return (
                    f"Employment type '{value}' is not valid. "
                    f"Valid values: {', '.join(sorted(VALID_KINDS))}."
                )
            mapped["employment_type"] = resolved
            normalized["kind"] = resolved
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- duplicate_employee (change email to resolve duplicate) ---
        if field == "duplicate_employee":
            if not EMAIL_RE.match(value):
                return f"'{value}' is not a valid email address."
            from accounts.models import User as _User
            if _User.objects.filter(email__iexact=value).exists():
                return (
                    f"An employee with email '{value}' already exists in the system. "
                    "Use a different email address."
                )
            mapped["email"] = value
            normalized["email"] = value
            if "duplicate_employee" in mapped:
                del mapped["duplicate_employee"]
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- duplicate document number fixes ---
        DUPLICATE_FIELD_TO_NUMBER_KEY = {
            "duplicate_sale_receipt": "receipt_number",
            "duplicate_invoice": "invoice_number",
            "duplicate_estimate": "estimate_number",
            "duplicate_purchase_order": "purchase_order_number",
            "duplicate_bill": "bill_number",
            "duplicate_check": "check_number",
            "duplicate_expense": "reference_number",
            "duplicate_chart_of_account": "account_name",
        }
        if field in DUPLICATE_FIELD_TO_NUMBER_KEY:
            number_key = DUPLICATE_FIELD_TO_NUMBER_KEY[field]
            mapped[number_key] = value
            if field in mapped:
                del mapped[field]
            row.mapped_data = mapped
            row.normalized_data = normalized
            return None

        # --- generic scalar fields (dates, amounts, reference numbers) ---
        mapped_key = field.replace("_uid", "").replace("_id", "")
        mapped[mapped_key if mapped_key in mapped else field] = value
        normalized[field] = value
        row.mapped_data = mapped
        row.normalized_data = normalized
        return None

    @staticmethod
    def apply_to_similar_rows(
        job,
        source_row,
        field,
        value,
        company,
        validator,
        mappings,
        match_mapped_value,
        match_mapped_field,
    ):
        similar_rows = (
            DataMigrationRow.objects.filter(job=job)
            .exclude(uid=source_row.uid)
            .filter(**{f"mapped_data__{match_mapped_field}": match_mapped_value})
        )

        fixed_rows = []
        for similar_row in similar_rows:
            apply_error = RowFixService.apply_field_value(
                similar_row, field, value, company
            )
            if apply_error:
                continue
            similar_row.save(
                update_fields=["mapped_data", "normalized_data", "updated_at"]
            )
            validator.validate_row(
                similar_row,
                job,
                company,
                mappings,
                counters=None,
                remap_from_raw=False,
            )
            if not RowFixService.field_related_issues(similar_row, field).exists():
                fixed_rows.append(similar_row)

        if fixed_rows:
            refresh_job_row_counters(job)
        return fixed_rows
