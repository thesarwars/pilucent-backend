from django.db import models


class PaymentMethodStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class PaymentInformationStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    SUCCEEDED = (
        "SUCCEEDED",
        "Succeeded",
    )
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Failed"
    PROCESSING = "PROCESSING", "Processing"
    REFUNDED = "REFUNDED", "Refunded"
    ON_HOLD = "ON_HOLD", "On Hold"
    DISPUTE = "DISPUTED", "Dispute"
    APPROVED = "APPROVED", "Approved"
    PAID = "PAID", "Paid"


class PaymentInformationKindChoices(models.TextChoices):
    SALE = "SALE", "Sale"
    REFUND = "REFUND", "Refund"
    PURCHASE = "PURCHASE", "Purchase"
    COMPANY_SUBSCRIPTION = "COMPANY_SUBSCRIPTION", "Company Subscription"
    ACCOUNTANT_SUBSCRIPTION = "ACCOUNTANT_SUBSCRIPTION", "Accountant Subscription"
