from django.db import models


class PurchaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    OPEN = "OPEN", "Open"
    ACCEPTED = "ACCEPTED", "Accepted"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"
    COMPLETED = "COMPLETED", "Completed"


class PurchaseItemStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"


class PurchaseItemkind(models.TextChoices):
    EXPENSE = "EXPENSE", "Expense"
    PRODUCT = "PRODUCT", "Product"


class PurchaseTaxKindChoices(models.TextChoices):
    INCLUSIVE = "INCLUSIVE", "Inclusive of Tax"
    EXCLUSIVE = "EXCLUSIVE", "Exclusive of Tax"
    NO_TAX = "NO_TAX", "No Tax"


class ExpenseStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"


class PurchasePaymentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PARTIALLY = "PARTIALLY", "Partially"
    COMPLETED = "COMPLETED", "Completed"


class PurchasePaymentItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"
    PARTIALLY = "PARTIALLY", "Partially"
    COMPLETED = "COMPLETED", "Completed"


class PurchasePaymentItemModelKindChoices(models.TextChoices):
    PURCHASE = "PURCHASE", "Purchase"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit Note"


class PayBillStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"
    PAID = "PAID", "Paid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"


class PayBillItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"
    PAID = "PAID", "Paid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
