from django.db import models


class TransactionStatusChoices(models.TextChoices):
    FOR_REVIEW = "FOR_REVIEW", "For_Review"
    CATEGORIZED = "CATEGORIZED", "Categorized"
    EXCLUDED = "EXCLUDED", "Excluded"


class TrxRuleTypeChoices(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    SPENT = "SPENT", "Spent"


class ParamsFieldChoices(models.TextChoices):
    AMOUNT = "AMOUNT", "Amount"
    DESCRIPTION = "DESCRIPTION", "Description"
    BANK_TEXT = "BANK_TEXT", "Bank Text"


class ParamsOperationsChoices(models.TextChoices):
    CONTAINS = "CONTAINS", "Contains"
    NOT_CONTAINS = "NOT_CONTAINS", "Not Contains"
    IS_EXACTLY = "IS_EXACTLY", "Is Exactly"
    EQUAL = "EQUAL", "Equal"
    NOT_EQUAL = "NOT_EQUAL", "Not Equal"
    GREATER_THAN = "GREATER_THAN", "Greater Than"
    LESS_THAN = "LESS_THAN", "Less Than"


class TrxAssignTypeChoices(models.TextChoices):
    EXPENSE = "EXPENSE", "Expense"
    TRANSFER = "TRANSFER", "Transfer"
    CHECK = "CHECK", "Check"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    DEPOSIT = "DEPOSIT", "Deposit"


class BankDepositStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REMOVED = "REMOVED", "Removed"


class DepositItemTypeChoices(models.TextChoices):
    PAYMENT = "PAYMENT", "Payment"
    SALES_RECEIPT = "SALES_RECEIPT", "Sales Receipt"
    REFUND = "REFUND", "Refund"
    OTHER_INCOME = "OTHER_INCOME", "Other Income"


class DepositItemPaymentMethodChoices(models.TextChoices):
    CASH = "CASH", "Cash"
    CHECK = "CHECK", "Check"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
    ONLINE_PAYMENT = "ONLINE_PAYMENT", "Online Payment"
    OTHER = "OTHER", "Other"


class BankReconciliationStatusChoices(models.TextChoices):
    """The lifecycle of a reconciliation session.

    Replaces an `is_closed` boolean. Spec s21 names these states directly, and
    the boolean could not hold them: once undo exists, `is_closed=True` beside
    an `is_undone=True` means *not closed*, and every reader that forgot the
    second flag would be wrong silently rather than loudly.

    `is_forced` stays a separate flag rather than becoming a fourth state,
    because forcing is a property of how a session closed, not a place in its
    lifecycle -- the spec's own data model lists `adjusted` the same way.

    UNDONE is terminal. Reconciling that period again is a new row, which is
    why the period-uniqueness constraint is partial: many undone sessions may
    share a period, at most one live one may.
    """

    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    UNDONE = "UNDONE", "Undone"
