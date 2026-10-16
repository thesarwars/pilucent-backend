from django.db import models


class CycleKindChoices(models.TextChoices):
    """Earned leave runs on the service year, casual and sick on the calendar
    year (§3.2): one leave-year column cannot express both."""

    CALENDAR_YEAR = "CALENDAR_YEAR", "Calendar year"
    SERVICE_YEAR = "SERVICE_YEAR", "Service year"
    # A credit's own window: it lapses when the window closes.
    ROLLING = "ROLLING", "Rolling"
    EVENT = "EVENT", "Event"


class AccrualKindChoices(models.TextChoices):
    FIXED_ANNUAL = "FIXED_ANNUAL", "Fixed each cycle"
    PER_DAYS_WORKED = "PER_DAYS_WORKED", "Per days worked"
    CREDIT = "CREDIT", "Credit"
    EVENT = "EVENT", "On the event"


class GenderRestrictionChoices(models.TextChoices):
    NONE = "NONE", "Anyone"
    WOMAN = "WOMAN", "Women"


class WorkerRestrictionChoices(models.TextChoices):
    ANY = "ANY", "Anyone"
    WORKER_ONLY = "WORKER_ONLY", "Workers"


class LedgerReasonChoices(models.TextChoices):
    OPENING = "OPENING", "Opening balance"
    ACCRUAL = "ACCRUAL", "Accrued"
    # Zero days, deliberately: the employee sees why nothing accrued.
    ACCRUAL_CAPPED = "ACCRUAL_CAPPED", "Accrual capped"
    FORFEITURE = "FORFEITURE", "Forfeited at the year end"
    TAKEN = "TAKEN", "Taken"
    CANCELLED = "CANCELLED", "Cancelled"
    ENCASHED = "ENCASHED", "Encashed"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    SEPARATION_PAYOUT = "SEPARATION_PAYOUT", "Paid out on separation"
    CREDIT_EARNED = "CREDIT_EARNED", "Credit earned"
    CREDIT_EXPIRED = "CREDIT_EXPIRED", "Credit expired"
    REVERSAL = "REVERSAL", "Reversal"


# A correction is reversal + replacement; these are corrected through their
# own flows instead (cancel the request, decline the encashment).
REVERSIBLE = ("OPENING", "ACCRUAL", "ACCRUAL_CAPPED", "ADJUSTMENT", "CREDIT_EARNED", "CREDIT_EXPIRED",
              "FORFEITURE")


class HalfChoices(models.TextChoices):
    FULL = "FULL", "Full day"
    FIRST_HALF = "FIRST_HALF", "First half"
    SECOND_HALF = "SECOND_HALF", "Second half"


class RequestStatusChoices(models.TextChoices):
    """Stored. IN_PROGRESS and TAKEN are an approved request read against
    today, so they are derived, never stored (they could only go stale)."""

    SUBMITTED = "SUBMITTED", "Waiting for a decision"
    APPROVED = "APPROVED", "Approved"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class EncashmentStatusChoices(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Waiting for approval"
    APPROVED = "APPROVED", "Approved"
    PAID = "PAID", "Paid"
    DECLINED = "DECLINED", "Declined"


class NoticeMethodChoices(models.TextChoices):
    # An oral notice is a valid notice: s.46 does not require writing.
    WRITTEN = "WRITTEN", "Written"
    ORAL = "ORAL", "Oral"


class MaternityStatusChoices(models.TextChoices):
    """The statute's order: notice, proof of pregnancy and the first
    instalment, delivery, proof of birth and the second, the return."""

    NOTIFIED = "NOTIFIED", "Notice recorded"
    ON_LEAVE_PRE = "ON_LEAVE_PRE", "First instalment paid"
    DELIVERED = "DELIVERED", "Delivery recorded"
    ON_LEAVE_POST = "ON_LEAVE_POST", "Second instalment paid"
    COMPLETED = "COMPLETED", "Returned to work"
    CANCELLED = "CANCELLED", "Cancelled"


class MaternityEventChoices(models.TextChoices):
    NOTICE = "NOTICE", "Notice received"
    PROOF_OF_PREGNANCY = "PROOF_OF_PREGNANCY", "Proof of pregnancy recorded"
    PAY_FIRST = "PAY_FIRST", "First instalment paid"
    DELIVERY = "DELIVERY", "Delivery recorded"
    PROOF_OF_BIRTH = "PROOF_OF_BIRTH", "Proof of birth recorded"
    PAY_SECOND = "PAY_SECOND", "Second instalment paid"
    RETURN = "RETURN", "Returned to work"
    CANCEL = "CANCEL", "Case cancelled"


class BenefitBasisChoices(models.TextChoices):
    # Disputed in the rule book: an election made on the record.
    ACT_S48 = "ACT_S48", "3 months' wages ÷ days actually worked (s.48)"
    RULES_2022 = "RULES_2022", "1 month's wages ÷ 26 (Rules 2022)"


class IssueMethodChoices(models.TextChoices):
    PRINTED = "PRINTED", "Printed pack"
    EMAIL = "EMAIL", "Email"
    PORTAL = "PORTAL", "Portal"
    SMS = "SMS", "SMS"


class LeaveAuditActionChoices(models.TextChoices):
    REQUEST_SUBMITTED = "REQUEST_SUBMITTED", "Request submitted"
    REQUEST_APPROVED = "REQUEST_APPROVED", "Request approved"
    REQUEST_DECLINED = "REQUEST_DECLINED", "Request declined"
    REQUEST_WITHDRAWN = "REQUEST_WITHDRAWN", "Request withdrawn"
    REQUEST_CANCELLED = "REQUEST_CANCELLED", "Approved leave cancelled"
    GRANTED = "GRANTED", "Manual grant or debit"
    REVERSED = "REVERSED", "Entry reversed"
    CYCLE_OPENED = "CYCLE_OPENED", "Cycle opened"
    ACCRUAL_POSTED = "ACCRUAL_POSTED", "Accrual posted"
    YEAR_CLOSED = "YEAR_CLOSED", "Year-end close"
    CREDIT_EARNED = "CREDIT_EARNED", "Compensatory credit earned"
    CREDIT_EXPIRED = "CREDIT_EXPIRED", "Compensatory credit expired"
    ENCASHMENT_REQUESTED = "ENCASHMENT_REQUESTED", "Encashment requested"
    ENCASHMENT_APPROVED = "ENCASHMENT_APPROVED", "Encashment approved"
    ENCASHMENT_DECLINED = "ENCASHMENT_DECLINED", "Encashment declined"
    ENCASHMENT_PAID = "ENCASHMENT_PAID", "Encashment paid"
    MATERNITY_OPENED = "MATERNITY_OPENED", "Maternity case opened"
    MATERNITY_DELIVERY = "MATERNITY_DELIVERY", "Delivery recorded"
    RESTRICTED_READ = "RESTRICTED_READ", "Restricted maternity field read"
    RESTRICTED_READ_REFUSED = "RESTRICTED_READ_REFUSED", "Restricted maternity field refused"
    MATERNITY_EVENT = "MATERNITY_EVENT", "Maternity event"
    STATEMENTS_GENERATED = "STATEMENTS_GENERATED", "Quarterly statements generated"
    STATEMENT_ISSUED = "STATEMENT_ISSUED", "Statement issued"
    STATEMENT_ACKNOWLEDGED = "STATEMENT_ACKNOWLEDGED", "Statement receipt acknowledged"


class LeaveEventChoices(models.TextChoices):
    """§9. Written to the outbox for consumers (payroll) and as notifications."""

    LEAVE_REQUESTED = "LeaveRequested", "Leave requested"
    LEAVE_APPROVED = "LeaveApproved", "Leave approved"
    LEAVE_DECLINED = "LeaveDeclined", "Leave declined"
    BALANCE_GRANTED = "LeaveBalanceGranted", "Leave granted or debited"
    ACCRUAL_POSTED = "LeaveAccrualPosted", "Earned leave accrued"
    FORFEITED = "LeaveForfeited", "Leave forfeited"
    ENCASHMENT_APPROVED = "EncashmentApproved", "Encashment approved"
    MATERNITY_CASE_OPENED = "MaternityCaseOpened", "Maternity case opened"
    MATERNITY_PAYMENT_DUE = "MaternityPaymentDue", "Maternity benefit instalment due"
    CREDIT_EARNED = "CompensatoryCreditEarned", "Compensatory holiday earned"
