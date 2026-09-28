from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.purchase_order_validator import (
    PurchaseOrderValidatorService,
)
from datamigrationio.django_rest.services.purchase_order_impact import (
    PurchaseOrderImpactService,
)
from datamigrationio.django_rest.services.purchase_order_rollback import (
    PurchaseOrderMigrationRollbackService,
)
from datamigrationio.tasks import process_purchase_order_migration


COLUMN_ALIAS_MAP = {
    "vendor name": "vendor",
    "vendor": "vendor",
    "vendor email": "vendor_email",
    "email": "vendor_email",
    "purchase order number": "purchase_order_number",
    "purchase order no": "purchase_order_number",
    "purchase order #": "purchase_order_number",
    "po number": "purchase_order_number",
    "po no": "purchase_order_number",
    "po #": "purchase_order_number",
    "purchase order date": "purchase_order_date",
    "po date": "purchase_order_date",
    "date": "purchase_order_date",
    "expected date": "expected_date",
    "delivery date": "expected_date",
    "line type": "line_type",
    "item type": "line_type",
    "type": "line_type",
    "product name": "product_service",
    "product": "product_service",
    "item": "product_service",
    "service": "product_service",
    "expense account": "expense_account",
    "expense account name": "expense_account",
    "quantity": "quantity",
    "qty": "quantity",
    "unit price": "unit_price",
    "rate": "unit_price",
    "amount": "line_amount",
    "line amount": "line_amount",
    "total": "line_amount",
    "tax code": "tax_code",
    "location": "warehouse",
    "warehouse": "warehouse",
    "currency": "currency_kind",
    "currency rate": "currency_rate",
    "memo": "memo",
    "description": "description",
}

REQUIRED_TARGET_FIELDS = {
    "purchase_order_number",
    "purchase_order_date",
    "line_amount",
}

ACCOUNTING_TARGET_FIELDS = set()


@MigrationHandlerRegistry.register
class PurchaseOrderMigrationHandler(BaseMigrationHandler):
    data_type = "purchase_orders"
    label = "Purchase Orders"
    category = "Expenses"
    description = "Import purchase orders."
    has_gl_impact = False
    is_posting_transaction = False
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Vendor Name",
        "Vendor Email",
        "Purchase Order Number",
        "Purchase Order Date",
        "Expected Date",
        "Line Type",
        "Product Name",
        "Expense Account",
        "Description",
        "Quantity",
        "Unit Price",
        "Amount",
        "Tax Code",
        "Location",
        "Currency",
        "Currency Rate",
        "Memo",
    ]

    TEMPLATE_SAMPLE_ROW = [
        "Acme Supplies",
        "acme@example.com",
        "PO-001",
        "01/15/2026",
        "02/15/2026",
        "product",
        "Office Chair",
        "",
        "Ergonomic office chair",
        "2",
        "150.00",
        "300.00",
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
        all_fields = sorted(set(aliases.values()))
        return all_fields

    @classmethod
    def get_required_target_fields(cls) -> set:
        return REQUIRED_TARGET_FIELDS | {"vendor", "vendor_email"}

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return ACCOUNTING_TARGET_FIELDS

    @classmethod
    def validate(cls, job, company) -> dict:
        return PurchaseOrderValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return PurchaseOrderImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_purchase_order_migration.delay(
                str(job.uid), user.id, send_email=send_email
            )
            message = "Import started. Check results endpoint for progress."
        else:
            print(
                f"[HANDLER] Running purchase order import synchronously (DEBUG mode) "
                f"for job_uid={job.uid}"
            )
            process_purchase_order_migration.apply(
                args=[str(job.uid), user.id],
                kwargs={"send_email": send_email},
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
        return PurchaseOrderMigrationRollbackService.run(job, user, reason=reason)
