from django.db import models


class JournalEntryStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"
    UN_PUBLISHED = "UN_PUBLISHED", "Un Published"


class JournalEntryConnectorRequestKindChoices(models.TextChoices):
    CREATED = "CREATED", "Created"
    UPDATED = "UPDATED", "Updated"
    DELETED = "DELETED", "Deleted"
    RECOVERED = "RECOVERED", "Recovered"


class JournalEntryKindChoices(models.TextChoices):
    CREDIT_NOTE = "CREDIT_NOTE", "Credit Note"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT", "Stock Adjustment"
    # purchase related
    PURCHASE = "PURCHASE", "Purchase"
    EXPENSE = "EXPENSE", "Expense"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    PAY_BILL = "PAY_BILL", "Pay Bill"
    CHEQUE = "CHEQUE", "Cheque"

    # sale related
    SALE = "SALE", "Sale"
    SALE_RECEPT = "SALE_RECEPT", "Sale Recept"
    REFUND_RECEIPT = "REFUND_RECEIPT", "Refund Receipt"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"

    # product related
    PRODUCT_PRURCHASE = "PRODUCT_PRURCHASE", "Product Purchase"

    # chart of account related
    CHART_OF_ACCOUNT = "CHART_OF_ACCOUNT", "Chart Of Account"

    # A journal entry someone keyed by hand, belonging to no document.
    #
    # Every other value here names the kind of document the entry was posted
    # from, and `kind` defaults to PURCHASE -- so a hand-keyed entry, which has
    # no document at all, was labelled a bill. Harmless while nothing read the
    # field; the register's Type column reads it.
    JOURNAL_ENTRY = "JOURNAL_ENTRY", "Journal Entry"
    
    #bank deposit related
    BANK_DEPOSIT = "BANK_DEPOSIT", "Bank Deposit"
    # A forced reconciliation posts the amount it could not explain. Its own
    # kind so the entry is filterable and cannot be mistaken for a deposit.
    BANK_RECONCILIATION = "BANK_RECONCILIATION", "Bank Reconciliation"
    
    #salary process
    PAYROLL_SALARY_PROCESS = "PAYROLL_SALARY_PROCESS", "Payroll Salary Process"
    PAYROLL_TAX_PAYMENT = "PAYROLL_TAX_PAYMENT", "Payroll Tax Payment"
    
    #sales tax 
    SALES_TAX = "SALES_TAX", "Sales Tax"

class JournalEntryConnectorKindChoices(models.TextChoices):
    DEBIT = "DEBIT", "Debit"
    CREDIT = "CREDIT", "Credit"


