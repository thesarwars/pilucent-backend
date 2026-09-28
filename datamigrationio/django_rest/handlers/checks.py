from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.check_validator import CheckValidatorService
from datamigrationio.django_rest.services.check_impact import CheckImpactService
from datamigrationio.django_rest.services.check_rollback import CheckMigrationRollbackService
from datamigrationio.tasks import process_check_migration


COLUMN_ALIAS_MAP = {
    "vendor name": "vendor",
    "vendor": "vendor",
    "payee name": "vendor",
    "payee": "vendor",
    "vendor email": "vendor_email",
    "payee email": "vendor_email",
    "email": "vendor_email",
    "check number": "check_number",
    "check no": "check_number",
    "check #": "check_number",
    "cheque number": "check_number",
    "cheque no": "check_number",
    "check date": "check_date",
    "date": "check_date",
    "bank account": "bank_account",
    "bank account name": "bank_account",
    "payment account": "bank_account",
    "line type": "line_type",
    "item type": "line_type",
    "type": "line_type",
    "product name": "product_service",
    "product": "product_service",
    "item": "product_service",
    "service": "product_service",
    "expense account": "expense_account",
    "expense account name": "expense_account",
    "account": "expense_account",
    "description": "description",
    "quantity": "quantity",
    "qty": "quantity",
    "unit price": "unit_price",
    "rate": "unit_price",
    "amount": "line_amount",
    "line amount": "line_amount",
    "total": "line_amount",
    "tax code": "tax_code",
    "tax": "tax_code",
    "location": "warehouse",
    "warehouse": "warehouse",
    "currency": "currency_kind",
    "currency rate": "currency_rate",
    "memo": "memo",
    "notes": "memo",
}

REQUIRED_TARGET_FIELDS = {
    "check_number",
    "check_date",
    "bank_account",
    "line_amount",
}

ACCOUNTING_TARGET_FIELDS = {
    "bank_account",
    "expense_account",
    "tax_code",
    "currency_kind",
    "currency_rate",
}


@MigrationHandlerRegistry.register
class ChecksMigrationHandler(BaseMigrationHandler):
    data_type = "checks"
    label = "Cheque"
    category = "Expenses"
    description = "Import cheque payments with full accounting impact."
    has_gl_impact = True
    is_posting_transaction = True
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Vendor Name",
        "Vendor Email",
        "Check Number",
        "Check Date",
        "Bank Account",
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
        "CHK-001",
        "01/15/2026",
        "Checking Account",
        "expense",
        "",
        "Office Supplies",
        "Monthly office supplies",
        "1",
        "250.00",
        "250.00",
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
        return REQUIRED_TARGET_FIELDS | {"vendor", "vendor_email"}

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return ACCOUNTING_TARGET_FIELDS

    @classmethod
    def validate(cls, job, company) -> dict:
        return CheckValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return CheckImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_check_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            print(
                f"[HANDLER] Running check import synchronously (DEBUG mode) "
                f"for job_uid={job.uid}"
            )
            process_check_migration.apply(
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
        return CheckMigrationRollbackService.run(job, user, reason=reason)
