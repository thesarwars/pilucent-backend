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
    LEAVE = "LEAVE", "Leave"  # BD leave; message-only, the outbox carries the record
    ID_CARD = "ID_CARD", "ID card"  # BD ID cards; message-only, the outbox carries the record
    ATTENDANCE_INTAKE = "ATTENDANCE_INTAKE", "Attendance intake"  # BD intake; message-only
    PAYROLL_SETTINGS = "PAYROLL_SETTINGS", "Payroll settings"  # BD payroll settings; message-only
    PAYROLL_RUN = "PAYROLL_RUN", "Payroll run"  # BD run payroll; message-only


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

    # BD leave (leaveledgerio events, leave-backend.md §9)
    LEAVE_REQUESTED = "LEAVE_REQUESTED", "Leave Requested"
    LEAVE_APPROVED = "LEAVE_APPROVED", "Leave Approved"
    LEAVE_DECLINED = "LEAVE_DECLINED", "Leave Declined"
    LEAVE_BALANCE_GRANTED = "LEAVE_BALANCE_GRANTED", "Leave Balance Granted"
    LEAVE_ACCRUAL_POSTED = "LEAVE_ACCRUAL_POSTED", "Leave Accrual Posted"
    LEAVE_FORFEITED = "LEAVE_FORFEITED", "Leave Forfeited"
    ENCASHMENT_APPROVED = "ENCASHMENT_APPROVED", "Encashment Approved"
    MATERNITY_CASE_OPENED = "MATERNITY_CASE_OPENED", "Maternity Case Opened"
    MATERNITY_PAYMENT_DUE = "MATERNITY_PAYMENT_DUE", "Maternity Payment Due"
    COMPENSATORY_CREDIT_EARNED = "COMPENSATORY_CREDIT_EARNED", "Compensatory Credit Earned"

    # BD ID cards (idcardio events, id-cards.md §9)
    ID_CARD_ISSUED = "ID_CARD_ISSUED", "ID Card Issued"
    ID_CARD_REVOKED = "ID_CARD_REVOKED", "ID Card Revoked"
    ID_CARD_EXPIRING = "ID_CARD_EXPIRING", "ID Card Expiring"
    CARD_PRINT_READY = "CARD_PRINT_READY", "Card Print Job Ready"
    CARD_PRINT_FAILED = "CARD_PRINT_FAILED", "Card Print Job Failed"
    CARD_TEMPLATE_PUBLISHED = "CARD_TEMPLATE_PUBLISHED", "Card Template Published"

    # BD attendance intake (intakeio events, attendance-intake.md §10)
    INTAKE_ORPHANS_DETECTED = "INTAKE_ORPHANS_DETECTED", "Unmapped Device IDs Held"
    INTAKE_BATCH_REVERSED = "INTAKE_BATCH_REVERSED", "Attendance Import Reversed"
    ATTENDANCE_PERIOD_UNLOCKED = "ATTENDANCE_PERIOD_UNLOCKED", "Attendance Period Unlocked"

    # BD payroll settings (paysetio events, payroll-settings.md §8)
    PAYROLL_ELECTION_PROPOSED = "PAYROLL_ELECTION_PROPOSED", "Payroll Election Awaiting Approval"
    PAYROLL_ELECTION_BACKDATED = "PAYROLL_ELECTION_BACKDATED", "Payroll Election Backdated"
    PAYROLL_SETTINGS_BLOCKED = "PAYROLL_SETTINGS_BLOCKED", "Payroll Blocked By Settings"

    # BD run payroll (payrunio events, run-payroll.md §8)
    PAYROLL_RUN_COMPUTED = "PAYROLL_RUN_COMPUTED", "Payroll Run Awaiting Approval"
    PAYROLL_RUN_APPROVED = "PAYROLL_RUN_APPROVED", "Payroll Run Approved"
    PAYSLIPS_RELEASED = "PAYSLIPS_RELEASED", "Payslips Released"
