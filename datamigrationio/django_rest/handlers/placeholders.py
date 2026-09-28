from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry


class PlaceholderMigrationHandler(BaseMigrationHandler):
    """Base for all not-yet-implemented migration types. All defaults from BaseMigrationHandler apply."""
    import_available = False


# (data_type, label, category, description, has_gl_impact, is_posting_transaction, template_headers)
_PLACEHOLDER_DEFINITIONS = [
    # (
    #     "deposits",
    #     "Deposits",
    #     "Banking",
    #     "Import bank deposits.",
    #     True,
    #     True,
    #     [
    #         "Deposit Date", "Deposit Account", "Deposit Account UID", "Received From",
    #         "Received From Email", "Account Name", "Account UID", "Payment Method",
    #         "Reference Number", "Description", "Amount", "Currency", "Currency Rate", "Memo",
    #     ],
    # ),
    # (
    #     "journal_entries",
    #     "Journal Entries",
    #     "Accounting",
    #     "Import manual journal entries.",
    #     True,
    #     True,
    #     [
    #         "Journal Number", "Journal Date", "Account Name", "Account UID", "Description",
    #         "Debit", "Credit", "Customer Name", "Vendor Name", "Location", "Location UID",
    #         "Class", "Reference Number", "Memo",
    #     ],
    # ),
    (
        "bank_data",
        "Bank Data",
        "Banking",
        "Import bank transaction data.",
        True,
        False,
        [
            "Bank Account", "Bank Account UID", "Transaction Date", "Description",
            "Reference Number", "Debit", "Credit", "Amount", "Transaction Type",
            "Payee", "Memo",
        ],
    ),
    (
        "customers",
        "Customers",
        "Contacts",
        "Import customer records.",
        False,
        False,
        [
            "Customer Name", "Display Name", "Email", "Phone", "Company Name",
            "Billing Address", "Shipping Address", "Opening Balance", "Opening Balance Date",
            "Tax Number", "Notes",
        ],
    ),
    (
        "vendors",
        "Vendors",
        "Contacts",
        "Import vendor records.",
        False,
        False,
        [
            "Vendor Name", "Display Name", "Email", "Phone", "Company Name",
            "Billing Address", "Opening Balance", "Opening Balance Date", "Tax Number", "Notes",
        ],
    ),
    (
        "products",
        "Products and Services",
        "Inventory",
        "Import product and service items.",
        False,
        False,
        [
            "Name", "SKU", "Type", "Category", "Description", "Sales Price", "Purchase Cost",
            "Income Account", "Income Account UID", "Expense Account", "Expense Account UID",
            "Asset Account", "Asset Account UID", "Quantity On Hand", "As Of Date",
            "Taxable", "Status",
        ],
    ),
    # employees is fully implemented — see handlers/employees.py
    # (
    #     "opening_balances",
    #     "Opening Balances",
    #     "Accounting",
    #     "Import account opening balances.",
    #     True,
    #     False,
    #     [
    #         "Account Name", "Account UID", "Opening Balance Date", "Debit", "Credit",
    #         "Description", "Reference Number",
    #     ],
    # ),
    # (
    #     "time_activities",
    #     "Time Activities",
    #     "Payroll",
    #     "Import time tracking entries.",
    #     False,
    #     False,
    #     [
    #         "Employee Name", "Employee Email", "Customer Name", "Service Name", "Date",
    #         "Start Time", "End Time", "Hours", "Description", "Billable", "Rate",
    #     ],
    # ),
    # (
    #     "open_transactions",
    #     "Open Transactions",
    #     "Accounting",
    #     "Import outstanding open transactions.",
    #     True,
    #     True,
    #     [
    #         "Transaction Type", "Transaction Number", "Transaction Date", "Due Date",
    #         "Customer/Vendor", "Amount", "Open Balance", "Account", "Reference Number", "Memo",
    #     ],
    # ),
    # (
    #     "historical_transactions",
    #     "Historical Transactions",
    #     "Accounting",
    #     "Import historical transaction records.",
    #     True,
    #     True,
    #     [
    #         "Transaction Type", "Transaction Number", "Transaction Date", "Customer/Vendor",
    #         "Account", "Description", "Debit", "Credit", "Amount", "Reference Number", "Memo",
    #     ],
    # ),
]


def _make_placeholder_handler(data_type, label, category, description, has_gl_impact, is_posting, headers):
    """Dynamically create and register a PlaceholderMigrationHandler subclass."""
    class_name = (
        "".join(word.title() for word in label.replace("/", " ").split()) + "MigrationHandler"
    )
    handler_class = type(
        class_name,
        (PlaceholderMigrationHandler,),
        {
            "data_type": data_type,
            "label": label,
            "category": category,
            "description": description,
            "has_gl_impact": has_gl_impact,
            "is_posting_transaction": is_posting,
            "_template_headers": headers,
            "get_template_headers": classmethod(lambda cls: cls._template_headers),
        },
    )
    MigrationHandlerRegistry.register(handler_class)
    return handler_class


for _args in _PLACEHOLDER_DEFINITIONS:
    _make_placeholder_handler(*_args)
