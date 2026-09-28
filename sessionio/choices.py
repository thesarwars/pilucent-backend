from django.db import models


class TransactionSessionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class TransactionSessionKindChoices(models.TextChoices):
    CREATED = "CREATED", "Created"
    UPDATED = "UPDATED", "Updated"
    DELETED = "DELETED", "Deleted"
    RECOVERED = "RECOVERED", "Recovered"


class TransactionSessionModelKindChoices(models.TextChoices):
    CREDIT_NOTE = "CREDIT_NOTE", "Credit Note"

    # purchase related
    PURCHASE = "PURCHASE", "Purchase"
    EXPENSE = "EXPENSE", "Expense"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    PAY_BILL = "PAY_BILL", "Pay Bill"

    # sale related
    SALE = "SALE", "Sale"
    SALE_RECEPT = "SALE_RECEPT", "Sale Recept"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"

class TransactionSessionLabelChoices(models.TextChoices):
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
