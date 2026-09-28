from django.db import models


class CurrencyStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class CurrencyConnectorModelKind(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    SUPPLIER = "SUPPLIER", "Supplier"
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
    CREDIT_NOTE_ITEM = "CREDIT_NOTE_ITEM", "Credit Note Item"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    PAY_BILL = "PAY_BILL", "Pay Bill"