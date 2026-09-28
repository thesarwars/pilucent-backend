from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.sales_receipt_validator import (
    SalesReceiptValidatorService,
)
from datamigrationio.django_rest.services.sales_receipt_impact import (
    SalesReceiptImpactService,
)
from datamigrationio.django_rest.services.sales_receipt_rollback import (
    SalesReceiptMigrationRollbackService,
)
from datamigrationio.tasks import process_sales_receipt_migration


COLUMN_ALIAS_MAP = {
    "customer name": "customer",
    "customer": "customer",
    "customer email": "customer_email",
    "email": "customer_email",
    "receipt number": "receipt_number",
    "receipt no": "receipt_number",
    "receipt #": "receipt_number",
    "receipt date": "receipt_date",
    "date": "receipt_date",
    "product name": "product_service",
    "product": "product_service",
    "product uid": "product_uid",
    "item": "product_service",
    "service": "product_service",
    "quantity": "quantity",
    "qty": "quantity",
    "unit price": "unit_price",
    "rate": "unit_price",
    "amount": "line_amount",
    "line amount": "line_amount",
    "total": "line_amount",
    "tax code": "tax_code",
    "tax uid": "tax_uid",
    "account name": "income_account",
    "income account": "income_account",
    "deposit account": "deposit_account",
    "deposit account uid": "deposit_account_uid",
    "payment method": "payment_method",
    "location": "warehouse",
    "warehouse": "warehouse",
    "location uid": "warehouse_uid",
    "currency": "currency_kind",
    "currency rate": "currency_rate",
    "memo": "memo",
    "description": "description",
    "billing address": "full_billing_address",
    "shipping address": "full_shipping_address",
    "shipping by": "shipping_by",
    "shipping date": "shipping_date",
    "term": "term",
    "reference number": "reference_number",
}

REQUIRED_TARGET_FIELDS = {
    "receipt_number",
    "receipt_date",
    "line_amount",
}

ACCOUNTING_TARGET_FIELDS = {
    "income_account",
    "income_account_uid",
    "deposit_account",
    "deposit_account_uid",
    "tax_code",
    "tax_uid",
    "currency_kind",
    "currency_rate",
}


@MigrationHandlerRegistry.register
class SalesReceiptsMigrationHandler(BaseMigrationHandler):
    data_type = "sales_receipts"
    label = "Sales Receipts"
    category = "Sales"
    description = "Import sales receipts."
    has_gl_impact = True
    is_posting_transaction = True
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Customer Name",
        "Customer Email",
        "Receipt Number",
        "Receipt Date",
        "Product Name",
        "Description",
        "Quantity",
        "Unit Price",
        "Amount",
        "Tax Code",
        "Deposit Account",
        "Payment Method",
        "Location",
        "Currency",
        "Currency Rate",
        "Memo",
    ]

    TEMPLATE_SAMPLE_ROW = [
        "Acme Corp",
        "acme@example.com",
        "SR-001",
        "01/15/2026",
        "Consulting Hours",
        "Implementation support",
        "2",
        "150.00",
        "300.00",
        "",
        "Checking",
        "",
        "",
        "USD",
        "1",
        "",
    ]

    @classmethod
    def get_template_headers(cls) -> list:
        return cls.TEMPLATE_HEADERS

    @classmethod
    def get_template_sample_row(cls) -> list:
        return cls.TEMPLATE_SAMPLE_ROW

    @classmethod
    def get_field_aliases(cls) -> dict:
        return COLUMN_ALIAS_MAP

    @classmethod
    def get_target_fields(cls) -> list:
        aliases = cls.get_field_aliases()
        return sorted(set(aliases.values()))

    @classmethod
    def get_required_target_fields(cls) -> set:
        return REQUIRED_TARGET_FIELDS | {"customer", "customer_email"} | {
            "product_service",
            "product_uid",
            "income_account",
            "income_account_uid",
        }

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return ACCOUNTING_TARGET_FIELDS

    @classmethod
    def validate(cls, job, company) -> dict:
        return SalesReceiptValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return SalesReceiptImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_sales_receipt_migration.delay(
                str(job.uid), user.id, send_email=send_email
            )
            message = "Import started. Check results endpoint for progress."
        else:
            print(
                f"[HANDLER] Running sales receipt import synchronously (DEBUG) "
                f"for job_uid={job.uid}"
            )
            process_sales_receipt_migration.apply(
                args=[str(job.uid), user.id], kwargs={"send_email": send_email}
            )
            message = "Import completed synchronously."

        return {
            "implemented": True,
            "job_uid": str(job.uid),
            "status": job.status,
            "message": message,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:
        return SalesReceiptMigrationRollbackService.run(job, user, reason=reason)
