from django.db import models


class TagKindChoices(models.TextChoices):
    PRODUCT = "PRODUCT", "Product"
    SERVICE = "SERVICE", "Service"
    PROJECT = "PROJECT", "Project"
    EVENT = "EVENT", "Event"
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
    JOURNAL_ENTRY = "JOURNAL_ENTRY", "Journal Entry"
    CREDIT_NOTE_ITEM = "CREDIT_NOTE_ITEM", "Credit Note Item"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    PAY_BILL = "PAY_BILL", "Pay Bill"
    BANK_DEPOSIT = "BANK_DEPOSIT", "Bank Deposit"


class TagStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "DRAFT"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
