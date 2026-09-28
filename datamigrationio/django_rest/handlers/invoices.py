from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.invoice_validator import (
    InvoiceValidatorService,
)
from datamigrationio.django_rest.services.invoice_impact import (
    InvoiceImpactService,
)
from datamigrationio.django_rest.services.invoice_rollback import (
    InvoiceMigrationRollbackService,
)
from datamigrationio.tasks import process_invoice_migration


COLUMN_ALIAS_MAP = {
    "customer name": "customer",
    "customer": "customer",
    "customer email": "customer_email",
    "email": "customer_email",
    "invoice number": "invoice_number",
    "invoice no": "invoice_number",
    "invoice #": "invoice_number",
    "invoice date": "invoice_date",
    "date": "invoice_date",
    "due date": "due_date",
    "product name": "product_service",
    "product": "product_service",
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
    "account name": "income_account",
    "income account": "income_account",
    "location": "warehouse",
    "warehouse": "warehouse",
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
    "invoice_number",
    "invoice_date",
    "due_date",
    "line_amount",
}

ACCOUNTING_TARGET_FIELDS = {
    "income_account",
    "income_account_uid",
    "tax_code",
    "currency_kind",
    "currency_rate",
}


@MigrationHandlerRegistry.register
class InvoiceMigrationHandler(BaseMigrationHandler):
    data_type = "invoices"
    label = "Invoices"
    category = "Sales"
    description = "Import customer invoices for sales."
    has_gl_impact = True
    is_posting_transaction = True
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
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

    TEMPLATE_SAMPLE_ROW = [
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
        all_fields = sorted(set(aliases.values()))
        return all_fields

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

        return InvoiceValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:

        return InvoiceImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:

        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_invoice_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            print(f"[HANDLER] Running import synchronously (DEBUG mode) for job_uid={job.uid}")
            process_invoice_migration.apply(args=[str(job.uid), user.id], kwargs={"send_email": send_email})
            message = "Import completed synchronously."

        return {
            "implemented": True,
            "job_uid": str(job.uid),
            "status": job.status,
            "message": message,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:

        return InvoiceMigrationRollbackService.run(job, user, reason=reason)
