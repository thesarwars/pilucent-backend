from django.db import models


class UserStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class ChartOfAccountStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    # Retired from data entry, kept in the books. The state two shipped error
    # messages have been telling users to reach for -- the control-account
    # delete refusal and the 409 on deleting an account with history both say
    # "make it inactive instead" -- while no such state existed, so both routed
    # the user in a circle. Spec BLZ-FIN-COA-SPEC-001 s9.4.
    #
    # Deliberately NOT the same as REMOVED. An inactive account keeps its
    # balance, its history and its place in every report; it is only withheld
    # from pickers and new documents. That is why the ordinary
    # `.exclude(status=REMOVED)` used across the codebase still admits it: those
    # call sites are reports and resolvers, and they should.
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class ChartOfAccountSystemKeyChoices(models.TextChoices):
    """Stable identifiers for the accounts the posting engine must resolve.

    These ten are the ones `get_chart_of_account()` looks up. Until now it
    resolved them by **title**, which is user-editable -- so renaming
    "Inventory Asset" silently broke every sale posting, and the `food_beverage`
    template, which spells them differently, could not post at all.

    The key is the contract; the title is a label the user owns.
    """

    AR = "AR", "Accounts Receivable"
    AP = "AP", "Accounts Payable"
    # The one account every set of books closes into. Seeded by all 20
    # templates and present on 54 of 60 companies, but by title only -- so
    # unlike every other control account it was renameable, retypeable and
    # deletable, because `is_fixed` and the resolver both key off this
    # enumeration. Spec BLZ-FIN-COA-SPEC-001 s8: exactly one per entity.
    RETAINED_EARNINGS = "RETAINED_EARNINGS", "Retained Earnings"
    INVENTORY_ASSET = "INVENTORY_ASSET", "Inventory Asset"
    UNDEPOSITED_FUNDS = "UNDEPOSITED_FUNDS", "Undeposited Funds"
    OPENING_BALANCE_EQUITY = "OPENING_BALANCE_EQUITY", "Opening Balance Equity"
    SALES_TAX_PAYABLE = "SALES_TAX_PAYABLE", "Sales Tax Payable"
    COGS = "COGS", "Cost of Goods Sold"
    SALES_OF_PRODUCT_INCOME = "SALES_OF_PRODUCT_INCOME", "Sales of Product Income"
    SERVICE = "SERVICE", "Service"
    OTHER_MISC_EXPENSE = "OTHER_MISC_EXPENSE", "Other Miscellaneous Expense"
    # Contra-revenue: carries a DEBIT balance while sitting in the income
    # section, which is correct and must not be flagged as a sign error.
    SALES_DISCOUNTS = "SALES_DISCOUNTS", "Sales Discounts"
    # Shipping charged TO the customer is revenue. Every shipping account the
    # templates ship is an EXPENSE (freight paid out), which is a different
    # thing and cannot be the credit side of a shipping charge.
    SHIPPING_INCOME = "SHIPPING_INCOME", "Shipping Income"
    # Where a forced reconciliation puts the amount it could not explain. It is
    # created on demand rather than seeded, because a company that never forces
    # one should never see the account: a nonzero balance here is a standing
    # admission that the books and the bank disagree by that much.
    RECONCILIATION_DISCREPANCIES = (
        "RECONCILIATION_DISCREPANCIES",
        "Reconciliation Discrepancies",
    )
    # Where a payroll deduction with no configured liability account lands, so
    # the pay run still balances. Seeded by 15 of 20 templates and present on 17
    # of 60 companies, and resolved BY TITLE on every pay run -- so for the other
    # 43 the residual path already resolves to None, logs "the journal entry will
    # not balance", and posts short. Keyed and created on demand instead.
    PAYROLL_LIABILITIES = "PAYROLL_LIABILITIES", "Payroll Liabilities"
    # The two federal payroll tax liabilities. Unlike the NY/MN components
    # beside them these titles are NOT per-state -- `FEDERAL_TAX_LIABILITY_
    # COMPONENTS` is a flat tuple, so they are the same two strings on every
    # company in the product. They are resolved by `title__iexact` when payroll
    # components are created, which happens long after onboarding, and a miss
    # skips the component so the pay run posts short by the whole federal
    # withholding.
    FEDERAL_TAX_941 = "FEDERAL_TAX_941", "Federal Taxes (941/943/944)"
    FEDERAL_UNEMPLOYMENT_940 = "FEDERAL_UNEMPLOYMENT_940", "Federal Unemployment (940)"


class ChartOfAccountKindChoices(models.TextChoices):
    EXPENSES = "EXPENSES", "Expenses"
    INCOMES = "INCOMES", "Incomes"
    EQUITIES = "EQUITIES", "Equities"
    LIABILITIES = "LIABILITIES", "Liabilities"
    ASSETS = "ASSETS", "Assets"


class UserGenderChoices(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHERS = "OTHERS", "Others"
