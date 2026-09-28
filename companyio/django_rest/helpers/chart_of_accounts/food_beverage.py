from companyio.choices import CompanyKindChoices

from accounts.choices import ChartOfAccountKindChoices

food_beverage = [
    {
        "kind": CompanyKindChoices.FOOD_BEVERAGE,
        "chart_of_accounts": [
            {
                "title": "Cash on Hand",
                "code": "1010",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Bank",
                "detail_type_title": "Cash & Cash Equivalents",
            },
            {
                "title": "Cash in Bank",
                "code": "1020",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Bank",
                "detail_type_title": "Checking",
            },
            {
                # Renamed from "Accounts Receivable". The posting engine
                # resolves this account by system_key, and the key is stamped
                # from this canonical title -- see TITLE_TO_SYSTEM_KEY.
                "title": "Accounts Receivable (A/R)",
                "code": "1030",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Accounts Receivable (A/R)",
                "detail_type_title": "Accounts Receivable",
            },
            {
                # The inventory control account. Food and Beverage stay as
                # sub-accounts beneath it, so the industry split survives while
                # inventory postings still have one account to land on. It must
                # precede its children -- the seeder resolves `parent` by title
                # in a single forward pass.
                "title": "Inventory Asset",
                "code": "1100",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Other Current Assets",
                "detail_type_title": "Inventory",
            },
            {
                "title": "Undeposited Funds",
                "code": "1110",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Other Current Assets",
                "detail_type_title": "Undeposited Funds",
            },
            {
                "title": "Inventory (Food)",
                "code": "1040",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Other Current Assets",
                "detail_type_title": "Inventory",
                "parent": "Inventory Asset",
            },
            {
                "title": "Inventory (Beverage)",
                "code": "1050",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Other Current Assets",
                "detail_type_title": "Inventory",
                "parent": "Inventory Asset",
            },
            {
                "title": "Prepaid Expenses",
                "code": "1060",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Other Current Assets",
                "detail_type_title": "Prepaid Expenses",
            },
            {
                "title": "Equipment",
                "code": "1070",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Fixed Assets",
                "detail_type_title": "Machinery & Equipment",
            },
            {
                "title": "Furniture and Fixtures",
                "code": "1080",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Fixed Assets",
                "detail_type_title": "Furniture and Fixtures",
            },
            {
                "title": "Leasehold Improvements",
                "code": "1090",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Fixed Assets",
                "detail_type_title": "Leasehold Improvements",
            },
            {
                # This template seeded Equipment, Furniture & Fixtures and
                # Leasehold Improvements but no way to depreciate any of them --
                # the only industry missing it. A contra-asset: it carries a
                # credit balance, which is correct and not a sign error.
                "title": "Accumulated Depreciation",
                "code": "1200",
                "kind": ChartOfAccountKindChoices.ASSETS,
                "account_type_title": "Fixed Assets",
                "detail_type_title": "Accumulated Depreciation",
            },
            {
                # Renamed from "Accounts Payable" -- canonical title, so the
                # system key is stamped and bill posting can resolve it.
                "title": "Accounts Payable (A/P)",
                "code": "2010",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Accounts Payable (A/P)",
                "detail_type_title": "Accounts Payable",
            },
            {
                "title": "Sales Tax Payable",
                "code": "2100",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Sales Tax Payable",
            },
            {
                # The payroll module posts to this detail type by name. This
                # template had "Payroll Taxes" as an *expense* but no liability
                # to accrue withholdings against.
                "title": "Payroll Liabilities",
                "code": "2110",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Payroll Liabilities",
            },
            {
                "title": "Accrued Expenses",
                "code": "2020",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Other Current Liability",
            },
            {
                "title": "Short-term Loans Payable",
                "code": "2030",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Loan Payable",
            },
            {
                "title": "Long-term Loans Payable",
                "code": "2040",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Long Term Liabilities",
                "detail_type_title": "Notes Payable",
            },
            {
                "title": "Taxes Payable",
                "code": "2050",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Taxes Payable",
            },
            {
                "title": "Owner's Capital",
                "code": "3010",
                "kind": ChartOfAccountKindChoices.EQUITIES,
                "account_type_title": "Equity",
                "detail_type_title": "Owner's Equity",
            },
            {
                "title": "Retained Earnings",
                "code": "3020",
                "kind": ChartOfAccountKindChoices.EQUITIES,
                "account_type_title": "Equity",
                "detail_type_title": "Retained Earnings",
            },
            {
                # The other side of every migrated opening balance. Without it
                # this template could not even create an account carrying an
                # opening balance -- the COA serializer looks it up by name and
                # dereferences the result.
                "title": "Opening Balance Equity",
                "code": "3000",
                "kind": ChartOfAccountKindChoices.EQUITIES,
                "account_type_title": "Equity",
                "detail_type_title": "Opening Balance Equity",
            },
            {
                # Default revenue landing account. Food/Beverage/Catering Sales
                # stay as the industry-specific breakdown.
                "title": "Sales of Product Income",
                "code": "4000",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Sales of Product Income",
            },
            {
                # Contra-revenue. Carries a DEBIT balance inside the income
                # section, which is correct -- do not treat it as a sign error.
                "title": "Sales Discounts",
                "code": "4060",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Discounts/Refunds Given",
            },
            {
                # Shipping charged TO the customer, i.e. revenue. Distinct from
                # the freight/shipping EXPENSE accounts, which are what the
                # company pays out.
                "title": "Shipping Income",
                "code": "4070",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Other Primary Income",
            },
            {
                "title": "Service",
                "code": "4050",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Service/Fee Income",
            },
            {
                "title": "Food Sales",
                "code": "4010",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Sales of Product Income",
            },
            {
                "title": "Beverage Sales",
                "code": "4020",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Sales of Product Income",
            },
            {
                "title": "Catering Sales",
                "code": "4030",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Income",
                "detail_type_title": "Service/Fee Income",
            },
            {
                "title": "Other Revenue",
                "code": "4040",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Other Income",
                "detail_type_title": "Other Miscellaneous Income",
            },
            {
                # The COGS control account. Sales relieve inventory to this one;
                # the Food/Beverage/Catering splits below remain for manual use
                # and reporting.
                "title": "Cost of Goods Sold (COGS)",
                "code": "5000",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Cost of Goods Sold (COGS)",
                "detail_type_title": "Supplies & Materials - COGS",
            },
            {
                "title": "Cost of Food Sold",
                "code": "5010",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Cost of Goods Sold (COGS)",
                "detail_type_title": "Supplies & Materials - COGS",
            },
            {
                "title": "Cost of Beverage Sold",
                "code": "5020",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Cost of Goods Sold (COGS)",
                "detail_type_title": "Supplies & Materials - COGS",
            },
            {
                "title": "Cost of Catering Sold",
                "code": "5030",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Cost of Goods Sold (COGS)",
                "detail_type_title": "Supplies & Materials - COGS",
            },
            {
                "title": "Other COGS",
                "code": "5040",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Cost of Goods Sold (COGS)",
                "detail_type_title": "Supplies & Materials - COGS",
            },
            {
                "title": "Wages and Salaries",
                "code": "6010",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Payroll Expenses",
            },
            {
                "title": "Payroll Taxes",
                "code": "6020",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Payroll Expenses",
            },
            {
                "title": "Employee Benefits",
                "code": "6030",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Payroll Expenses",
            },
            {
                "title": "Rent Expense",
                "code": "6040",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Rent or Lease of Buildings",
            },
            {
                "title": "Utilities",
                "code": "6050",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Utilities",
            },
            {
                "title": "Insurance",
                "code": "6060",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Insurance",
            },
            {
                "title": "Marketing and Advertising",
                "code": "6070",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Advertising/Promotional",
            },
            {
                "title": "Repairs and Maintenance",
                "code": "6080",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Repair & Maintenance",
            },
            {
                "title": "Supplies",
                "code": "6090",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Supplies & Materials",
            },
            {
                "title": "Depreciation Expense",
                "code": "6100",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Other Expenses",
                "detail_type_title": "Depreciation",
            },
            {
                "title": "Professional Fees",
                "code": "6110",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Legal & Professional Fees",
            },
            {
                "title": "Training and Development",
                "code": "6120",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Other Business Expenses",
            },
            {
                "title": "Other Operating Expenses",
                "code": "6130",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Other Expenses",
                "detail_type_title": "Other Miscellaneous Expense",
            },
            {
                # The fallback the posting engine resolves when an expense has
                # nowhere else to land. Without it those postings had no legal
                # target, which is how ledgers become unbalanced.
                "title": "Other Miscellaneous Expense",
                "code": "6140",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Other Expenses",
                "detail_type_title": "Other Miscellaneous Expense",
            },
            {
                "title": "Interest Income",
                "code": "7010",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Other Income",
                "detail_type_title": "Interest Earned",
            },
            {
                "title": "Interest Expense",
                "code": "7020",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Other Expenses",
                "detail_type_title": "Interest Paid",
            },
            {
                "title": "Gain/Loss on Sale of Assets",
                "code": "7030",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Other Income",
                "detail_type_title": "Other Miscellaneous Income",
            },
            {
                "title": "Other Non-Operating Income/Expenses",
                "code": "7040",
                "kind": ChartOfAccountKindChoices.INCOMES,
                "account_type_title": "Other Income",
                "detail_type_title": "Other Miscellaneous Income",
            },
            {
                "title": "Income Taxes",
                "code": "2000",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Taxes Payable",
            },
            {
                # Was "Sales Taxes" here as well as the control account added in
                # the liabilities block above -- two accounts for one concept.
                # Renamed to make the distinction explicit: this is the accrual
                # for taxes already remitted or being tracked separately, while
                # "Sales Tax Payable" (2100) is what invoices post to.
                "title": "Sales Taxes Accrual",
                "code": "2001",
                "kind": ChartOfAccountKindChoices.LIABILITIES,
                "account_type_title": "Other Current Liabilities",
                "detail_type_title": "Sales Tax Payable",
            },
            {
                "title": "Property Taxes",
                "code": "6000",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Taxes & Licenses",
            },
            {
                "title": "Other Taxes",
                "code": "6001",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Taxes & Licenses",
            },
            {
                "title": "Bad Debt Expense",
                "code": "6002",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Expense",
                "detail_type_title": "Bad Debts",
            },
            {
                "title": "Donations and Contributions",
                "code": "7000",
                "kind": ChartOfAccountKindChoices.EXPENSES,
                "account_type_title": "Other Expenses",
                "detail_type_title": "Other Miscellaneous Expense",
            },
        ],
    },
]


