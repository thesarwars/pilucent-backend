from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.estimate_validator import (
    EstimateValidatorService,
)
from datamigrationio.django_rest.services.estimate_impact import (
    EstimateImpactService,
)
from datamigrationio.django_rest.services.estimate_rollback import (
    EstimateMigrationRollbackService,
)
from datamigrationio.tasks import process_estimate_migration


COLUMN_ALIAS_MAP = {
    "customer name": "customer",
    "customer": "customer",
    "customer email": "customer_email",
    "email": "customer_email",
    "estimate number": "estimate_number",
    "estimate no": "estimate_number",
    "estimate #": "estimate_number",
    "estimate date": "estimate_date",
    "date": "estimate_date",
    "expiry date": "expiry_date",
    "expiration date": "expiry_date",
    "expired date": "expiry_date",
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
    "estimate_number",
    "estimate_date",
    "line_amount",
}

ACCOUNTING_TARGET_FIELDS = set()  # estimates have no accounting fields


@MigrationHandlerRegistry.register
class EstimateMigrationHandler(BaseMigrationHandler):
    data_type = "estimates"
    label = "Estimates"
    category = "Sales"
    description = "Import sales estimates."
    has_gl_impact = False
    is_posting_transaction = False
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Customer Name",
        "Customer Email",
        "Estimate Number",
        "Estimate Date",
        "Expiry Date",
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
        "EST-001",
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
        return REQUIRED_TARGET_FIELDS | {"customer", "customer_email"}

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return ACCOUNTING_TARGET_FIELDS

    @classmethod
    def validate(cls, job, company) -> dict:
        return EstimateValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return EstimateImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_estimate_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            print(f"[HANDLER] Running estimate import synchronously (DEBUG mode) for job_uid={job.uid}")
            process_estimate_migration.apply(args=[str(job.uid), user.id], kwargs={"send_email": send_email})
            message = "Import completed synchronously."

        return {
            "implemented": True,
            "job_uid": str(job.uid),
            "status": job.status,
            "message": message,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:
        return EstimateMigrationRollbackService.run(job, user, reason=reason)
