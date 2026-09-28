"""Default module/feature catalogue mapped to legacy Subscription boolean fields.

Used by ``seed_subscription_features`` and as fallback metadata for
``EntitlementService`` when resolving ``required_feature`` view attributes.
"""

FEATURE_CATALOG = [
    {
        "module": {
            "code": "accounting",
            "name": "Accounting Core",
            "display_order": 10,
        },
        "features": [
            {
                "code": "chart_of_account",
                "name": "Chart of Accounts",
                "legacy_field": "is_chart_of_account",
                "permission_codenames": ["view_chartofaccount", "add_chartofaccount"],
                "menu_key": "chart-of-accounts",
            },
            {
                "code": "chart_of_account_tree",
                "name": "Chart of Accounts Tree",
                "legacy_field": "is_chart_of_account_tree",
                "permission_codenames": ["view_chartofaccount"],
                "menu_key": "chart-of-accounts-tree",
            },
            {
                "code": "journal_entry",
                "name": "Journal Entries",
                "legacy_field": "is_journal_entry",
                "permission_codenames": ["view_journalentry", "add_journalentry"],
                "menu_key": "journals",
            },
            {
                "code": "bank_transaction",
                "name": "Bank Transactions",
                "legacy_field": "is_bank_transaction",
                "permission_codenames": ["view_journalentry"],
                "menu_key": "bank-transactions",
            },
        ],
    },
    {
        "module": {
            "code": "sales",
            "name": "Sales",
            "display_order": 20,
        },
        "features": [
            {
                "code": "sales",
                "name": "Sales",
                "legacy_field": "is_sales",
                "permission_codenames": ["view_sale", "add_sale", "change_sale"],
                "menu_key": "sales",
            },
            {
                "code": "customer",
                "name": "Customers",
                "legacy_field": "is_customer",
                "permission_codenames": ["view_customer", "add_customer"],
                "menu_key": "customers",
            },
        ],
    },
    {
        "module": {
            "code": "expense",
            "name": "Expenses & Purchases",
            "display_order": 30,
        },
        "features": [
            {
                "code": "expense",
                "name": "Expenses & Purchases",
                "legacy_field": "is_expense",
                "permission_codenames": ["view_purchase", "add_purchase"],
                "menu_key": "purchases",
            },
            {
                "code": "supplier_management",
                "name": "Supplier Management",
                "legacy_field": "is_supplier_management",
                "permission_codenames": ["view_supplier", "add_supplier"],
                "menu_key": "suppliers",
            },
        ],
    },
    {
        "module": {
            "code": "inventory",
            "name": "Inventory",
            "display_order": 40,
        },
        "features": [
            {
                "code": "inventory",
                "name": "Inventory",
                "legacy_field": "is_inventory",
                "permission_codenames": ["view_product", "add_product"],
                "menu_key": "products",
            },
            {
                "code": "warehouse",
                "name": "Warehouses",
                "legacy_field": "is_warehouse",
                "permission_codenames": ["view_warehouse", "add_warehouse"],
                "menu_key": "warehouses",
            },
        ],
    },
    {
        "module": {
            "code": "tax",
            "name": "Taxes & Agencies",
            "display_order": 50,
        },
        "features": [
            {
                "code": "agency_tax",
                "name": "Agency Tax",
                "legacy_field": "is_agency_tax",
                "permission_codenames": ["view_agencytax"],
                "menu_key": "agencies",
            },
        ],
    },
    {
        "module": {
            "code": "hr",
            "name": "HRIS",
            "display_order": 60,
        },
        "features": [
            {
                "code": "employees",
                "name": "Employees",
                "legacy_field": "is_employees",
                "permission_codenames": ["view_employee", "add_employee"],
                "menu_key": "employees",
            },
            {
                "code": "attendance",
                "name": "Attendance",
                "legacy_field": "is_attendance",
                "permission_codenames": ["view_attendance"],
                "menu_key": "attendances",
            },
            {
                "code": "punch_data_import",
                "name": "Punch Data Import",
                "legacy_field": "is_punch_data_import",
                "permission_codenames": [],
                "menu_key": "punch-import",
            },
        ],
    },
    {
        "module": {
            "code": "payroll",
            "name": "Payroll",
            "display_order": 70,
        },
        "features": [
            {
                "code": "payroll",
                "name": "Payroll",
                "legacy_field": "is_payroll",
                "permission_codenames": ["view_employee"],
                "menu_key": "payroll",
            },
        ],
    },
    {
        "module": {
            "code": "reports",
            "name": "Reports",
            "display_order": 80,
        },
        "features": [
            {
                "code": "standard_report",
                "name": "Standard Reports",
                "legacy_field": "is_standard_report",
                "permission_codenames": ["view_reports"],
                "menu_key": "reports",
            },
        ],
    },
    {
        "module": {
            "code": "platform",
            "name": "Platform",
            "display_order": 90,
        },
        "features": [
            {
                "code": "multicurrency",
                "name": "Multi Currency",
                "legacy_field": "is_multicurrency",
                "permission_codenames": ["view_currency"],
                "menu_key": "currencies",
            },
            {
                "code": "company_setting",
                "name": "Company Settings",
                "legacy_field": "is_company_setting",
                "permission_codenames": [],
                "menu_key": "settings",
            },
            {
                "code": "audit_log",
                "name": "Audit Log",
                "legacy_field": "is_audit_log",
                "permission_codenames": [],
                "menu_key": "audit-logs",
            },
            {
                "code": "attachment",
                "name": "Attachments",
                "legacy_field": "is_attachment",
                "permission_codenames": [],
                "menu_key": "attachments",
            },
            {
                "code": "user_role_management",
                "name": "User Role Management",
                "legacy_field": "is_user_role_management",
                "permission_codenames": [],
                "menu_key": "roles",
            },
            {
                "code": "terms",
                "name": "Terms",
                "legacy_field": "is_terms",
                "permission_codenames": ["view_term"],
                "menu_key": "terms",
            },
            {
                "code": "payment_management",
                "name": "Payment Methods",
                "legacy_field": "is_payment_management",
                "permission_codenames": ["view_paymentmethod"],
                "menu_key": "payment-methods",
            },
            {
                "code": "configuration",
                "name": "Configuration",
                "legacy_field": "is_configuration",
                "permission_codenames": [],
                "menu_key": "configuration",
            },
            {
                "code": "user_profile",
                "name": "User Profile",
                "legacy_field": "is_user_profile",
                "permission_codenames": [],
                "menu_key": "profile",
            },
            {
                "code": "support_ticket",
                "name": "Support Tickets",
                "legacy_field": "is_support_ticket",
                "permission_codenames": [],
                "menu_key": "support-tickets",
            },
            {
                "code": "ai_finzify",
                "name": "AI Assistant",
                "legacy_field": "is_ai_finzify",
                "permission_codenames": [],
                "menu_key": "ai",
            },
        ],
    },
]

LEGACY_FEATURE_FIELDS = [
    feature["legacy_field"]
    for group in FEATURE_CATALOG
    for feature in group["features"]
    if feature.get("legacy_field")
]
