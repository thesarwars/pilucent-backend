from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry
from datamigrationio.django_rest.services.expense_validator import ExpenseValidatorService
from datamigrationio.django_rest.services.expense_impact import ExpenseImpactService
from datamigrationio.django_rest.services.expense_rollback import ExpenseMigrationRollbackService
from datamigrationio.tasks import process_expense_migration


COLUMN_ALIAS_MAP = {
    "payee name": "vendor",
    "payee": "vendor",
    "vendor name": "vendor",
    "vendor": "vendor",
    "payee email": "vendor_email",
    "vendor email": "vendor_email",
    "email": "vendor_email",
    "payment date": "expense_date",
    "date": "expense_date",
    "payment account": "payment_account",
    "payment account name": "payment_account",
    "bank account": "payment_account",
    "payment method": "payment_method",
    "reference number": "reference_number",
    "ref no": "reference_number",
    "reference no": "reference_number",
    "line type": "line_type",
    "item type": "line_type",
    "type": "line_type",
    "expense account": "expense_account",
    "expense account name": "expense_account",
    "account": "expense_account",
    "product name": "product_service",
    "product": "product_service",
    "item": "product_service",
    "service": "product_service",
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
    "expense_date",
    "line_amount",
    "payment_account",
}

ACCOUNTING_TARGET_FIELDS = {
    "payment_account",
    "expense_account",
    "tax_code",
    "currency_kind",
    "currency_rate",
}


@MigrationHandlerRegistry.register
class ExpensesMigrationHandler(BaseMigrationHandler):
    data_type = "expenses"
    label = "Expenses"
    category = "Expenses"
    description = "Import business expenses with full accounting impact."
    has_gl_impact = True
    is_posting_transaction = True
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Payment Date",
        "Payee Name",
        "Payee Email",
        "Payment Account",
        "Payment Method",
        "Reference Number",
        "Line Type",
        "Expense Account",
        "Product Name",
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
        "01/15/2026",
        "Acme Supplies",
        "acme@example.com",
        "Checking Account",
        "Check",
        "EXP-001",
        "expense",
        "Office Supplies",
        "",
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
        return ExpenseValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        return ExpenseImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_expense_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            print(
                f"[HANDLER] Running expense import synchronously (DEBUG mode) "
                f"for job_uid={job.uid}"
            )
            process_expense_migration.apply(
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
        return ExpenseMigrationRollbackService.run(job, user, reason=reason)
