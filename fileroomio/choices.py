from django.db import models


class FileItemStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    UN_PUBLISHED = "UN_PUBLISHED", "Un Published"
    REMOVED = "REMOVED", "Removed"


class FileItemKindChoices(models.TextChoices):
    IMAGE = "IMAGE", "Image"
    VIDEO = "VIDEO", "Video"
    PDF = "PDF", "PDF"
    EXCEL = "EXCEL", "Excel"
    WORD = "WORD", "Word"
    TEXT = "TEXT", "Text"
    AUDIO = "AUDIO", "Audio"
    ARCHIVE = "ARCHIVE", "Archive"
    PPT = "PPT", "Power Point"
    SCRIPT = "SCRIPT", "Script"
    OTHER = "OTHER", "Other"


class FileItemConnectorModelKindChoices(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    SUPPLIER = "SUPPLIER", "Supplier"
    PURCHASE = "PURCHASE", "Purchase"
    EMPLOYEE = "EMPLOYEE", "Employee"
    THREAD = "THREAD", "Thread"
    ATTACHMENT = "ATTACHMENT", "Attachment"
    SALE = "SALE", "Sale"
    JOURNAL_ENTRY = "JOURNAL_ENTRY", "Journal Entry"
    CREDIT_NOTE_ITEM = "CREDIT_NOTE_ITEM", "Credit Note Item"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit Note"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"
    PRODUCT = "PRODUCT", "Product"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    PAY_BILL = "PAY_BILL", "Pay Bill"
    BANK_DEPOSIT = "BANK_DEPOSIT", "Bank Deposit"
    RECURRING_TEMPLATE = "RECURRING_TEMPLATE", "Recurring Template"
