from django.db import models


class MigrationDataTypeChoices(models.TextChoices):
    INVOICES = "invoices", "Invoices"
    ESTIMATES = "estimates", "Estimates"
    SALES_RECEIPTS = "sales_receipts", "Sales Receipts"
    DEPOSITS = "deposits", "Deposits"
    BILLS = "bills", "Bills"
    PURCHASE_ORDERS = "purchase_orders", "Purchase Orders"
    EXPENSES = "expenses", "Expenses"
    CHECKS = "checks", "Checks"
    JOURNAL_ENTRIES = "journal_entries", "Journal Entries"
    BANK_DATA = "bank_data", "Bank Data"
    CUSTOMERS = "customers", "Customers"
    VENDORS = "vendors", "Vendors"
    PRODUCTS = "products", "Products"
    CHART_OF_ACCOUNTS = "chart_of_accounts", "Chart of Accounts"
    EMPLOYEES = "employees", "Employees"
    LOCATIONS = "locations", "Locations"
    OPENING_BALANCES = "opening_balances", "Opening Balances"
    TIME_ACTIVITIES = "time_activities", "Time Activities"
    OPEN_TRANSACTIONS = "open_transactions", "Open Transactions"
    HISTORICAL_TRANSACTIONS = "historical_transactions", "Historical Transactions"


class MigrationStatusChoices(models.TextChoices):
    DRAFT = "draft", "Draft"
    UPLOADED = "uploaded", "Uploaded"
    MAPPED = "mapped", "Mapped"
    PREVIEWED = "previewed", "Previewed"
    VALIDATED = "validated", "Validated"
    IMPACT_REVIEWED = "impact_reviewed", "Impact Reviewed"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    PARTIALLY_COMPLETED = "partially_completed", "Partially Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    ROLLED_BACK = "rolled_back", "Rolled Back"
    PARTIALLY_ROLLED_BACK = "partially_rolled_back", "Partially Rolled Back"


class MigrationStepChoices(models.TextChoices):
    SELECT_DATA_TYPE = "select_data_type", "Select Data Type"
    UPLOAD_FILE = "upload_file", "Upload File"
    MAP_FIELDS = "map_fields", "Map Fields"
    PREVIEW_DATA = "preview_data", "Preview Data"
    VALIDATE_DATA = "validate_data", "Validate Data"
    REVIEW_IMPACT = "review_impact", "Review Impact"
    CONFIRM_IMPORT = "confirm_import", "Confirm Import"
    RESULTS_AUDIT = "results_audit", "Results & Audit"


class MigrationRowStatusChoices(models.TextChoices):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    DUPLICATE = "duplicate", "Duplicate"
    SKIPPED = "skipped", "Skipped"
    IMPORTED = "imported", "Imported"
    FAILED = "failed", "Failed"
    ROLLED_BACK = "rolled_back", "Rolled Back"


class MigrationSeverityChoices(models.TextChoices):
    ERROR = "error", "Error"
    WARNING = "warning", "Warning"
    DUPLICATE = "duplicate", "Duplicate"


class MigrationIssueTypeChoices(models.TextChoices):
    CUSTOMER_NOT_FOUND = "customer_not_found", "Customer Not Found"
    PRODUCT_NOT_FOUND = "product_not_found", "Product Not Found"
    PRODUCT_INCOME_ACCOUNT_MISSING = "product_income_account_missing", "Product Income Account Missing"
    INCOME_ACCOUNT_NOT_FOUND = "income_account_not_found", "Income Account Not Found"
    DEPOSIT_ACCOUNT_NOT_FOUND = "deposit_account_not_found", "Deposit Account Not Found"
    TAX_NOT_FOUND = "tax_not_found", "Tax Not Found"
    WAREHOUSE_NOT_FOUND = "warehouse_not_found", "Warehouse Not Found"
    TERM_NOT_FOUND = "term_not_found", "Term Not Found"
    INVALID_DATE = "invalid_date", "Invalid Date"
    INVALID_AMOUNT = "invalid_amount", "Invalid Amount"
    AMOUNT_MISMATCH = "amount_mismatch", "Amount Mismatch"
    DUPLICATE_INVOICE = "duplicate_invoice", "Duplicate Invoice"
    DUPLICATE_SALE_RECEIPT = "duplicate_sale_receipt", "Duplicate Sale Receipt"
    DUPLICATE_ESTIMATE = "duplicate_estimate", "Duplicate Estimate"
    DUPLICATE_PURCHASE_ORDER = "duplicate_purchase_order", "Duplicate Purchase Order"
    VENDOR_NOT_FOUND = "vendor_not_found", "Vendor Not Found"
    EXPENSE_ACCOUNT_NOT_FOUND = "expense_account_not_found", "Expense Account Not Found"
    MISSING_REQUIRED_FIELD = "missing_required_field", "Missing Required Field"
    CLOSED_PERIOD = "closed_period", "Closed Accounting Period"
    DUPLICATE_BILL = "duplicate_bill", "Duplicate Bill"
    DUPLICATE_CHECK = "duplicate_check", "Duplicate Check"
    BANK_ACCOUNT_NOT_FOUND = "bank_account_not_found", "Bank Account Not Found"
    DUPLICATE_EXPENSE = "duplicate_expense", "Duplicate Expense"
    PAYMENT_ACCOUNT_NOT_FOUND = "payment_account_not_found", "Payment Account Not Found"
    DUPLICATE_LOCATION = "duplicate_location", "Duplicate Location"
    ACCOUNT_TYPE_NOT_FOUND = "account_type_not_found", "Account Type Not Found"
    DETAIL_TYPE_NOT_FOUND = "detail_type_not_found", "Detail Type Not Found"
    DUPLICATE_CHART_OF_ACCOUNT = "duplicate_chart_of_account", "Duplicate Chart of Account"
    DUPLICATE_EMPLOYEE = "duplicate_employee", "Duplicate Employee"


class MigrationDuplicateHandlingChoices(models.TextChoices):
    SKIP_DUPLICATES = "skip_duplicates", "Skip Duplicates"
