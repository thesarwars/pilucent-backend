from django.db import models


class NotificationStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    PUBLISHED = "PUBLISHED", "Published"


class NotificationModelKindChoices(models.TextChoices):
    PURCHASE = "PURCHASE", "Purchase"
    EXPENSE = "EXPENSE", "Expense"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT", "Purchase Payment"
    SALE = "SALE", "Sale"
    SALE_PAYMENT_RECEIVE = "SALE_PAYMENT_RECEIVE", "Sale Payment Receive"
    INBOX = "INBOX", "Inbox"
    STOCK_ALERT = "STOCK_ALERT", "Stock Alert"
    DISPUT = "DISPUT", "Disput"
    NEXUS = "NEXUS", "Economic Nexus"  # no per-object FK; message-only


class NotificationKindChoices(models.TextChoices):

    # Invoice relatad
    SALE_CREATED = "SALE_CREATED", "Sale Created"
    INVOICE_CREATED = "INVOICE_CREATED", "Invoice Created"
    INVOICE_SHARED = "INVOICE_SHARED", "Invoice Shared"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment Received"
    INVOICE_OVERDUE = "INVOICE_OVERDUE", "Invoice Overdue"
    PAYMENT_FAILED = "PAYMENT_FAILED", "Payment Failed"

    # Banking Related

    # Expense related
    PURCHASE_PAYMENT_DUE = "PURCHASE_PAYMENT_DUE", "Purchase Payment Due"
    BILL_OVERDUE = "BILL_OVERDUE", "Bill Overdue"
    BILL_PAYMENT = "BILL_PAYMENT", "Bill Payment"
    PURCHASE_CREATED = "PURCHASE_CREATED", "Purchase Created"
    BILL_CREATED = "BILL_CREATED", "Bill Created"

    # System update and maintenance
    SCHEDULED_MAINTENANCE = "SCHEDULED_MAINTENANCE", "Scheduled Maintenance"
    SOFTWARE_UPDATE = "SOFTWARE_UPDATE", "Software Update"
    ERROR_REPORT = "ERROR_REPORT", "Error Report"

    # Financial Insights and Reports
    WEEKLY_SUMMARY_REPORT = "WEEKLY_SUMMARY_REPORT", "Weekly Summary Report"
    MONTHLY_PROFIT_AND_LOSS_REPORT = (
        "MONTHLY_PROFIT_AND_LOSS_REPORT",
        "Monthly Profit And Loss Report",
    )
    CASH_FLOW_INSIGHT = "CASH_FLOW_INSIGHT", "Cash Flow Insight"

    NEW_PRODUCT = "NEW_PRODUCT", "New Product"
    DISPUT = "DISPUT", "Disput"

    # Economic nexus
    NEXUS_THRESHOLD_APPROACHING = (
        "NEXUS_THRESHOLD_APPROACHING",
        "Nexus Threshold Approaching",
    )
    NEXUS_THRESHOLD_CROSSED = "NEXUS_THRESHOLD_CROSSED", "Nexus Threshold Crossed"
