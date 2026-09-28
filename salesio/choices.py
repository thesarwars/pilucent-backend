from django.db import models


class SalesStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    OPEN = "OPEN", "Open"
    ACCEPTED = "ACCEPTED", "Accepted"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"
    PAID = "PAID", "Paid"


class SaleItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"


class SaleReceptStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"


class SaleReceptKindChoices(models.TextChoices):
    SALE = "SALE", "Sale"
    REFUND = "REFUND", "Refund"


class SalePaymentReceiveStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PARTIALLY = "PARTIALLY", "Partially"
    COMPLETED = "COMPLETED", "Completed"


class SalePaymentReceiveItemModelKindChoices(models.TextChoices):
    SALE = "SALE", "Sale"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit Note"


class SalePaymentReceiveItemModelStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"
    PARTIALLY = "PARTIALLY", "Partially"
    COMPLETED = "COMPLETED", "Completed"


class SaleSettingPeferredDeliveryMethodChoices(models.TextChoices):
    PRINT_LATER = "PRINT_LATER", "Print Later"
    SEND_LATER = "SEND_LATER", "Send Later"


class SaleSettingInvoicePaymentChoices(models.TextChoices):
    CASH = "CASH", "Cash"
    ACCRUAL = "ACCRUAL", "Accrual"


class SalesTaxStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    PAID = "PAID", "Paid"
    OVER_DUE = "OVER_DUE", "Over Due"
    OPEN = "OPEN", "Open"
    DUE = "DUE", "Due"