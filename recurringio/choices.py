from django.db import models


class RecurringTxnTypeChoices(models.TextChoices):
    BILL = "BILL", "Bill"
    EXPENSE = "EXPENSE", "Expense"
    CHEQUE = "CHEQUE", "Cheque"  # a numbered payment drawn on a bank account
    ESTIMATE = "ESTIMATE", "Estimate"  # a non-posting sales quote to a customer
    # a settled sales refund to a customer (money leaves a bank/credit-card
    # account); the mirror of a sales receipt, materialized as a we/sales
    # record with kind=REFUND.
    REFUND_RECEIPT = "REFUND_RECEIPT", "Refund receipt"
    # A recurring cash sale charged to a stored payment method. Despite the
    # name, this is structurally a SALES RECEIPT, not a "payment received":
    # it carries product lines and no open invoice to apply cash against
    # (RECURRING_PAYMENT_BACKEND.md section 3).
    PAYMENT = "PAYMENT", "Payment"
    # A recurring accounts-receivable invoice: a we/sales record with
    # is_invoice=True, due date derived from the template's terms.
    INVOICE = "INVOICE", "Invoice"
    # A recurring purchase order: a we/purchases record with is_bill=False.
    # NON-POSTING -- a PO is a commitment to buy, not a liability, so it must
    # not touch A/P, inventory or the journal (the real endpoint gates all
    # three on is_bill).
    PURCHASE_ORDER = "PURCHASE_ORDER", "Purchase order"
    # A recurring cash sale: a we/sales record with is_sale_receipt=True, paid
    # in full on the fire date. Produces the SAME document as PAYMENT -- the two
    # screens collect slightly different inputs and are kept separate
    # deliberately (RECURRING_SALES_RECEIPT_BACKEND.md section 12.1).
    SALES_RECEIPT = "SALES_RECEIPT", "Sales receipt"
    # A recurring bank deposit. Unique in two ways: it has NO document-level
    # party (the payer is per line) and its cash-back amount is SUBTRACTED from
    # the total rather than added.
    DEPOSIT = "DEPOSIT", "Bank deposit"
    # A recurring credit note: reduces the customer's balance. Stored positive
    # with a negative ledger effect, matching the manual screen.
    CREDIT_MEMO = "CREDIT_MEMO", "Credit memo"


class RecurringTemplateTypeChoices(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    REMINDER = "REMINDER", "Reminder"
    UNSCHEDULED = "UNSCHEDULED", "Unscheduled"


class RecurringTemplateStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    # Stopped by a person, and resumable. Distinct from ENDED, which the
    # generation job sets when the schedule itself runs out — conflating the two
    # would make "resume" meaningless on a template that simply finished.
    PAUSED = "PAUSED", "Paused"
    ENDED = "ENDED", "Ended"
    # Charge-on-acceptance template whose start date passed while still
    # unaccepted: it can no longer produce anything.
    EXPIRED = "EXPIRED", "Expired"
    REMOVED = "REMOVED", "Removed"  # soft delete


class RecurringFrequencyChoices(models.TextChoices):
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    YEARLY = "YEARLY", "Yearly"


class RecurringDayModeChoices(models.TextChoices):
    DAY_OF_MONTH = "DAY_OF_MONTH", "Day of month"
    WEEKDAY = "WEEKDAY", "Weekday of month"


class RecurringOrdinalChoices(models.TextChoices):
    FIRST = "FIRST", "First"
    SECOND = "SECOND", "Second"
    THIRD = "THIRD", "Third"
    FOURTH = "FOURTH", "Fourth"
    LAST = "LAST", "Last"


class RecurringEndTypeChoices(models.TextChoices):
    NONE = "NONE", "Never"
    BY_DATE = "BY_DATE", "By date"
    AFTER_COUNT = "AFTER_COUNT", "After N occurrences"


class RecurringLineTypeChoices(models.TextChoices):
    CATEGORY = "CATEGORY", "Category"  # account-based line
    ITEM = "ITEM", "Item"  # product/service line


class RecurringOccurrenceStatusChoices(models.TextChoices):
    GENERATED = "GENERATED", "Generated"
    REMINDED = "REMINDED", "Reminded"
    SKIPPED = "SKIPPED", "Skipped"
    FAILED = "FAILED", "Failed"


class RecurringWhenToChargeChoices(models.TextChoices):
    """When a PAYMENT template is allowed to charge the customer."""

    FUTURE = "FUTURE", "On the schedule"
    # Charge only once the customer accepts. There is no acceptance surface
    # yet (no email, public accept page or stored-card flow), so these
    # generate nothing and expire if the start date passes -- charging a
    # customer who never accepted is exactly what the setting prevents.
    ACCEPT = "ACCEPT", "When the customer accepts"


class RecurringAcceptanceStatusChoices(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
