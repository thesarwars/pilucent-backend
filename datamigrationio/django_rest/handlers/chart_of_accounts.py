import io

from django.conf import settings
from django.http import HttpResponse

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry


COLUMN_ALIAS_MAP = {
    # Account name
    "account name": "title",
    "name": "title",
    # Account number / code
    "account number": "code",
    "number": "code",
    "account no": "code",
    "account code": "code",
    # Account type
    "account type": "account_type",
    "type": "account_type",
    # Detail type
    "detail type": "detail_type",
    "sub type": "detail_type",
    "subtype": "detail_type",
    # Opening balance
    "opening balance": "opening_balance",
    "balance": "opening_balance",
    "opening bal": "opening_balance",
    # Other fields
    "description": "description",
    "notes": "description",
}

REQUIRED_TARGET_FIELDS = {"title", "account_type", "detail_type"}


@MigrationHandlerRegistry.register
class ChartOfAccountsMigrationHandler(BaseMigrationHandler):
    data_type = "chart_of_accounts"
    label = "Chart of Accounts"
    category = "Accounting"
    description = "Import chart of accounts structure."
    has_gl_impact = True
    is_posting_transaction = False
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "Account Number",
        "Account Name",
        "Account Type",
        "Detail Type",
        "Description",
        "Opening Balance",
    ]

    TEMPLATE_SAMPLE_ROWS = [
        ["112720", "Checking Account - Bank of America", "Bank", "Checking", "Primary checking account", "5000.00"],
        ["", "Money Market - First National Bank", "Bank", "Money Market", "", ""],
        ["410790", "Product Sales Revenue", "Income", "Sales of Product Income", "", ""],
        ["500780", "Cost of Materials", "Cost of Goods Sold", "Supplies & Materials", "", ""],
    ]

    TYPE_DETAIL_TYPE_DATA = [
        ("Account Type", "Detail Type"),
        ("Assets", "Accounts Receivable (A/R)"),
        ("Assets", "Other Current Assets"),
        ("Assets", "Allowance for Bad Debts"),
        ("Assets", "Development Costs"),
        ("Assets", "Employee Cash Advances"),
        ("Assets", "Inventory"),
        ("Assets", "Investment - Mortgage/Real Estate Loans"),
        ("Assets", "Investment - Tax-Exempt Securities"),
        ("Assets", "Investment - U.S. Government Obligations"),
        ("Assets", "Investments - Other"),
        ("Assets", "Loans To Officers"),
        ("Assets", "Loans to Others"),
        ("Assets", "Loans to Stockholders"),
        ("Assets", "Prepaid Expenses"),
        ("Assets", "Retainage"),
        ("Assets", "Undeposited Funds"),
        ("Assets", "Bank"),
        ("Assets", "Cash on hand"),
        ("Assets", "Checking"),
        ("Assets", "Money Market"),
        ("Assets", "Rents Held in Trust"),
        ("Assets", "Savings"),
        ("Assets", "Trust account"),
        ("Fixed Assets", "Accumulated Amortization"),
        ("Fixed Assets", "Accumulated Depletion"),
        ("Fixed Assets", "Accumulated Depreciation"),
        ("Fixed Assets", "Buildings"),
        ("Fixed Assets", "Depletable Assets"),
        ("Fixed Assets", "Fixed Asset Computers"),
        ("Fixed Assets", "Fixed Asset Copiers"),
        ("Fixed Assets", "Fixed Asset Furniture"),
        ("Fixed Assets", "Fixed Asset Other Tools Equipment"),
        ("Fixed Assets", "Fixed Asset Phone"),
        ("Fixed Assets", "Fixed Asset Photo Video"),
        ("Fixed Assets", "Fixed Asset Software"),
        ("Fixed Assets", "Furniture & Fixtures"),
        ("Fixed Assets", "Intangible Assets"),
        ("Fixed Assets", "Land"),
        ("Fixed Assets", "Leasehold Improvements"),
        ("Fixed Assets", "Machinery & Equipment"),
        ("Fixed Assets", "Other fixed assets"),
        ("Fixed Assets", "Vehicles"),
        ("Other Assets", "Accumulated Amortization of Other Assets"),
        ("Other Assets", "Goodwill"),
        ("Other Assets", "Lease Buyout"),
        ("Other Assets", "Licenses"),
        ("Other Assets", "Organizational Costs"),
        ("Other Assets", "Other Long-term Assets"),
        ("Other Assets", "Security Deposits"),
        ("Liabilities", "Accounts Payable (A/P)"),
        ("Liabilities", "Credit Card"),
        ("Liabilities", "Other Current Liabilities"),
        ("Liabilities", "Deferred Revenue"),
        ("Liabilities", "Federal Income Tax Payable"),
        ("Liabilities", "Insurance Payable"),
        ("Liabilities", "Line of Credit"),
        ("Liabilities", "Loan Payable"),
        ("Liabilities", "Payroll Clearing"),
        ("Liabilities", "Payroll Tax Payable"),
        ("Liabilities", "Prepaid Expenses Payable"),
        ("Liabilities", "Rents in trust - Liability"),
        ("Liabilities", "Sales Tax Payable"),
        ("Liabilities", "State/Local Income Tax Payable"),
        ("Liabilities", "Trust Accounts - Liabilities"),
        ("Liabilities", "Undistributed Tips"),
        ("Long Term Liabilities", "Notes Payable"),
        ("Long Term Liabilities", "Other Long Term Liabilities"),
        ("Long Term Liabilities", "Shareholder Notes Payable"),
        ("Equity", "Equity"),
        ("Equity", "Accumulated Adjustment"),
        ("Equity", "Common Stock"),
        ("Equity", "Estimated Taxes"),
        ("Equity", "Health Insurance Premium"),
        ("Equity", "Health Savings Account Contribution"),
        ("Equity", "Opening Balance Equity"),
        ("Equity", "Owner's Equity"),
        ("Equity", "Paid-In Capital or Surplus"),
        ("Equity", "Partner Contributions"),
        ("Equity", "Partner Distributions"),
        ("Equity", "Partner's Equity"),
        ("Equity", "Personal Expense"),
        ("Equity", "Personal Income"),
        ("Equity", "Preferred Stock"),
        ("Equity", "Retained Earnings"),
        ("Equity", "Treasury Stock"),
        ("Income", "Income"),
        ("Income", "Discounts/Refunds Given"),
        ("Income", "Non-Profit Income"),
        ("Income", "Other Primary Income"),
        ("Income", "Sales of Product Income"),
        ("Income", "Service/Fee Income"),
        ("Income", "Unapplied Cash Payment Income"),
        ("Other Income", "Dividend Income"),
        ("Other Income", "Interest Earned"),
        ("Other Income", "Other Investment Income"),
        ("Other Income", "Other Miscellaneous Income"),
        ("Other Income", "Tax-Exempt Interest"),
        ("Cost of Goods Sold (COGS)", "Cost of labor - COST"),
        ("Cost of Goods Sold (COGS)", "Equipment Rental - COST"),
        ("Cost of Goods Sold (COGS)", "Other Costs of Services - COST"),
        ("Cost of Goods Sold (COGS)", "Shipping, Freight & Delivery - COST"),
        ("Cost of Goods Sold (COGS)", "Supplies & Materials - COGS"),
        ("Expenses", "Advertising/Promotional"),
        ("Expenses", "Auto"),
        ("Expenses", "Bad Debts"),
        ("Expenses", "Bank Charges"),
        ("Expenses", "Charitable Contributions"),
        ("Expenses", "Communication"),
        ("Expenses", "Cost of Labor"),
        ("Expenses", "Dues & subscriptions"),
        ("Expenses", "Entertainment"),
        ("Expenses", "Entertainment Meals"),
        ("Expenses", "Equipment Rental"),
        ("Expenses", "Finance costs"),
        ("Expenses", "Insurance"),
        ("Expenses", "Interest Paid"),
        ("Expenses", "Legal & Professional Fees"),
        ("Expenses", "Office/General Administrative Expenses"),
        ("Expenses", "Other Business Expenses"),
        ("Expenses", "Other Miscellaneous Service Cost"),
        ("Expenses", "Payroll Expenses"),
        ("Expenses", "Payroll Tax Expenses"),
        ("Expenses", "Payroll Wage Expenses"),
        ("Expenses", "Promotional Meals"),
        ("Expenses", "Rent or Lease of Buildings"),
        ("Expenses", "Repair & Maintenance"),
        ("Expenses", "Shipping, Freight & Delivery"),
        ("Expenses", "Supplies & Materials"),
        ("Expenses", "Taxes Paid"),
        ("Expenses", "Travel"),
        ("Expenses", "Travel Meals"),
        ("Expenses", "Unapplied Cash Bill Payment Expense"),
        ("Expenses", "Utilities"),
        ("Other Expenses", "Amortization"),
        ("Other Expenses", "Depreciation"),
        ("Other Expenses", "Exchange Gain or Loss"),
        ("Other Expenses", "Gas And Fuel"),
        ("Other Expenses", "Home Office"),
        ("Other Expenses", "Homeowner Rental Insurance"),
        ("Other Expenses", "Mortgage Interest Home Office"),
        ("Other Expenses", "Other Home Office Expenses"),
        ("Other Expenses", "Other Miscellaneous Expense"),
        ("Other Expenses", "Other Vehicle Expenses"),
        ("Other Expenses", "Parking and Tolls"),
        ("Other Expenses", "Penalties & Settlements"),
        ("Other Expenses", "Property Tax Home Office"),
        ("Other Expenses", "Rent and Lease Home Office"),
        ("Other Expenses", "Repairs and Maintenance Home Office"),
        ("Other Expenses", "Utilities Home Office"),
        ("Other Expenses", "Vehicle"),
        ("Other Expenses", "Vehicle Insurance"),
        ("Other Expenses", "Vehicle Lease"),
        ("Other Expenses", "Vehicle Loan"),
        ("Other Expenses", "Vehicle Loan Interest"),
        ("Other Expenses", "Vehicle Registration"),
        ("Other Expenses", "Vehicle Repairs"),
        ("Other Expenses", "Wash and Road Services"),
    ]

    @classmethod
    def get_template_headers(cls) -> list:
        return cls.TEMPLATE_HEADERS

    @classmethod
    def get_template_sample_row(cls) -> list:
        return cls.TEMPLATE_SAMPLE_ROWS[0] if cls.TEMPLATE_SAMPLE_ROWS else []

    @classmethod
    def generate_template_response(cls) -> HttpResponse:
        """Generate an Excel template with two sheets: data template + type reference."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()

        # --- Sheet 1: Template ---
        ws1 = wb.active
        ws1.title = "Chart of Accounts"

        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        thin_border = Border(
            bottom=Side(style="thin", color="000000"),
        )

        for col_idx, header in enumerate(cls.TEMPLATE_HEADERS, 1):
            cell = ws1.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")

        for row_idx, sample_row in enumerate(cls.TEMPLATE_SAMPLE_ROWS, 2):
            for col_idx, value in enumerate(sample_row, 1):
                ws1.cell(row=row_idx, column=col_idx, value=value)

        for col_idx in range(1, len(cls.TEMPLATE_HEADERS) + 1):
            ws1.column_dimensions[get_column_letter(col_idx)].width = 30

        # --- Sheet 2: Type and Details Type ---
        ws2 = wb.create_sheet(title="Type and Details Type")

        for col_idx, header in enumerate(cls.TYPE_DETAIL_TYPE_DATA[0], 1):
            cell = ws2.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")

        for row_idx, row_data in enumerate(cls.TYPE_DETAIL_TYPE_DATA[1:], 2):
            for col_idx, value in enumerate(row_data, 1):
                ws2.cell(row=row_idx, column=col_idx, value=value)

        ws2.column_dimensions["A"].width = 30
        ws2.column_dimensions["B"].width = 45

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="chart_of_accounts-import-template.xlsx"'
        return response

    @classmethod
    def get_field_aliases(cls) -> dict:
        return COLUMN_ALIAS_MAP

    @classmethod
    def get_target_fields(cls) -> list:
        return sorted(set(COLUMN_ALIAS_MAP.values()))

    @classmethod
    def get_required_target_fields(cls) -> set:
        return REQUIRED_TARGET_FIELDS

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return {"opening_balance"}

    @classmethod
    def validate(cls, job, company) -> dict:
        from datamigrationio.django_rest.services.chart_of_account_validator import (
            ChartOfAccountValidatorService,
        )
        return ChartOfAccountValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        from datamigrationio.django_rest.services.chart_of_account_impact import (
            ChartOfAccountImpactService,
        )
        return ChartOfAccountImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        from datamigrationio.tasks import process_chart_of_account_migration

        send_email = (options or {}).get("send_email", False)
        use_celery = (
            bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG
        )

        if use_celery:
            process_chart_of_account_migration.delay(
                str(job.uid), user.id, send_email=send_email
            )
            message = "Import started. Check results endpoint for progress."
        else:
            process_chart_of_account_migration.apply(
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
        from datamigrationio.django_rest.services.chart_of_account_rollback import (
            ChartOfAccountMigrationRollbackService,
        )
        return ChartOfAccountMigrationRollbackService.run(job, user, reason=reason)
