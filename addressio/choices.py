from django.db import models


class AddressStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class AddressConnectorKindCoices(models.TextChoices):
    SUPPLIER = "SUPPLIER", "Supplier"
    CUSTOMER = "CUSTOMER", "Customer"
    WAREHOUSE = "WAREHOUSE", "Warehouse"
    PURCHASE = "PURCHASE", "Purchase"
    SALE = "SALE", "Sale"
    CREDIT_NOTE_ITEM = "CREDIT_NOTE_ITEM", "Credit Note Item"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    COMPANY = "COMPANY", "Company"
    EMPLOYEE = "EMPLOYEE", "Employee"
