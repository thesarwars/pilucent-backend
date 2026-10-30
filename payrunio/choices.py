"""Run payroll (docs/backend/run-payroll-done.md): the run state machine, the
exception codes and the deduction order."""

from django.db import models

ENGINE_VERSION = "pilucent-payrun/1"


class RunStateChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    TEAM_SELECTED = "TEAM_SELECTED", "Team confirmed"
    COMPUTED = "COMPUTED", "Computed"
    APPROVED = "APPROVED", "Approved"
    DISBURSING = "DISBURSING", "Disbursing"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
    PAID = "PAID", "Paid"
    CLOSED = "CLOSED", "Paid and closed"
    CANCELLED = "CANCELLED", "Cancelled"


S = RunStateChoices
# §2. Every permitted move; anything else is refused. APPROVED has exactly one
# exit: an approved figure that can be recomputed is not an approval.
TRANSITIONS = {
    S.DRAFT: {S.TEAM_SELECTED, S.CANCELLED},
    S.TEAM_SELECTED: {S.COMPUTED, S.DRAFT, S.CANCELLED},
    S.COMPUTED: {S.APPROVED, S.TEAM_SELECTED, S.CANCELLED},
    S.APPROVED: {S.DISBURSING},
    S.DISBURSING: {S.PARTIALLY_PAID, S.PAID},
    S.PARTIALLY_PAID: {S.PAID},
    S.PAID: {S.CLOSED},
    S.CLOSED: set(),
    S.CANCELLED: set(),
}
PRE_APPROVAL = (S.DRAFT, S.TEAM_SELECTED, S.COMPUTED)
FIXED = (S.APPROVED, S.DISBURSING, S.PARTIALLY_PAID, S.PAID, S.CLOSED)


class RunTypeChoices(models.TextChoices):
    REGULAR = "REGULAR", "Regular"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    ARREARS = "ARREARS", "Arrears"
    OFF_CYCLE = "OFF_CYCLE", "Off cycle"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT", "Final settlement"


class PayMethodChoices(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank"
    MOBILE_WALLET = "MOBILE_WALLET", "Mobile"
    CASH = "CASH", "Cash"
    CHEQUE = "CHEQUE", "Cheque"


# The employee's payment profile names the wallet MFS.
METHOD_OF_PROFILE = {"BANK_TRANSFER": PayMethodChoices.BANK_TRANSFER, "MFS": PayMethodChoices.MOBILE_WALLET,
                     "CASH": PayMethodChoices.CASH}


class PayStatusChoices(models.TextChoices):
    PENDING = "PENDING", "Pending"
    INSTRUCTED = "INSTRUCTED", "Instructed"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    HELD = "HELD", "Held"


class OtSourceChoices(models.TextChoices):
    ATTENDANCE = "ATTENDANCE", "Attendance"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE", "Manual override"


class SeverityChoices(models.TextChoices):
    BLOCK = "BLOCK", "Block"
    WARN = "WARN", "Warn"
    INFO = "INFO", "Info"


class ResolutionChoices(models.TextChoices):
    EXCLUDED = "EXCLUDED", "Excluded from the run"
    FIXED_UPSTREAM = "FIXED_UPSTREAM", "Fixed upstream"
    ACCEPTED = "ACCEPTED", "Accepted"


# §3.8. `NO_RULE_SET` and `ATTENDANCE_NOT_LOCKED` refuse the run at creation
# rather than block a line: a run cannot exist without a rule set or before
# attendance is locked. `SALARY_ON_HOLD` is ours: a held salary is not paid,
# so the line is excluded and paid on a supplementary run when the hold lifts.
EXCEPTION_CODES = {
    "NO_STRUCTURE": "BLOCK",
    "NET_NOT_POSITIVE": "BLOCK",
    "BELOW_GRADE_FLOOR": "BLOCK",
    "MISSING_BANK_DETAIL": "BLOCK",
    "SALARY_ON_HOLD": "BLOCK",
    "DEDUCTION_DEFERRED": "WARN",
    "CASH_PAYMENT": "WARN",
    "NO_ETIN": "WARN",
    "PRORATED": "INFO",
}


class TransferStatusChoices(models.TextChoices):
    INSTRUCTED = "INSTRUCTED", "Instructed"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    RETURNED = "RETURNED", "Returned"


# §4.5. The order is statutory and fixed. Protected deductions are never
# deferred; a deduction that would take the net below zero is deferred, not
# clipped. Advance and loan recovery have no source yet (no BD loan model):
# their slots are kept so the order does not move when they arrive.
DEDUCTION_ORDER = [
    {"n": 1, "code": "TAX", "label": "Income tax withheld", "bn": "উৎসে কর", "protected": True,
     "citation": "Income Tax Act 2023, s.86"},
    {"n": 2, "code": "PF", "label": "Provident fund — employee", "bn": "ভবিষ্য তহবিল", "protected": True,
     "citation": "Bangladesh Labour Act 2006, s.264"},
    {"n": 3, "code": "ADVANCE", "label": "Advance recovery", "bn": "অগ্রিম সমন্বয়", "protected": False,
     "citation": "Bangladesh Labour Act 2006, s.125"},
    {"n": 4, "code": "LOAN", "label": "Loan repayment", "bn": "ঋণ পরিশোধ", "protected": False,
     "citation": "Bangladesh Labour Act 2006, s.125"},
    {"n": 5, "code": "OTHER", "label": "Other authorised deductions", "bn": "অন্যান্য অনুমোদিত কর্তন",
     "protected": False, "citation": "Bangladesh Labour Act 2006, s.125"},
]


class AuditActionChoices(models.TextChoices):
    RUN_CREATED = "RUN_CREATED", "Run created"
    TEAM_CONFIRMED = "TEAM_CONFIRMED", "Team confirmed"
    TEAM_REOPENED = "TEAM_REOPENED", "Team reopened"
    COMPUTED = "COMPUTED", "Computed"
    EXCEPTION_RESOLVED = "EXCEPTION_RESOLVED", "Exception resolved"
    EMPLOYEE_EXCLUDED = "EMPLOYEE_EXCLUDED", "Employee excluded"
    EMPLOYEE_INCLUDED = "EMPLOYEE_INCLUDED", "Employee included"
    OT_OVERRIDDEN = "OT_OVERRIDDEN", "Overtime overridden"
    APPROVED = "APPROVED", "Approved"
    FILE_GENERATED = "FILE_GENERATED", "File generated"
    INSTRUCTED = "INSTRUCTED", "Instructed"
    MARKED_PAID = "MARKED_PAID", "Marked paid"
    MARKED_FAILED = "MARKED_FAILED", "Marked failed"
    RELEASED = "RELEASED", "Payslips released"
    CLOSED = "CLOSED", "Closed"
    CANCELLED = "CANCELLED", "Cancelled"
    ACCOUNT_SET = "ACCOUNT_SET", "Corporate account set"


# §7, snake_case as every BD module declares them.
PERMISSIONS = (
    ("view_payroll_run", "Can view payroll runs and registers"),
    ("create_payroll_run", "Can open a payroll run"),
    ("compute_payroll_run", "Can compute and recompute a payroll run"),
    ("exclude_payroll_employee", "Can exclude an employee from a payroll run, with a reason"),
    ("override_payroll_ot", "Can type over attendance overtime in a payroll run"),
    ("approve_payroll_run", "Can approve a payroll run (never one they created)"),
    ("instruct_payroll_payment", "Can generate a payment file and instruct payment"),
    ("mark_payroll_paid", "Can mark a payroll line paid or failed"),
    ("release_payslips", "Can release payslips and close a payroll run"),
)
