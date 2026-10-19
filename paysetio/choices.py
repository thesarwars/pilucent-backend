"""Payroll settings (docs/backend/payroll-settings-done.md): the seven
elections the Labour Act leaves to the employer, the pay schedule and the
four statutory schemes."""

from django.db import models

# §2. The seven keys, in screen order. `citation` names the rule-book
# citation the election cites (captured on the row at election time, §3.2);
# `suffix` is added to it. `preset` is the value a company starts with; the
# four without one are NULL until chosen (§2.1).
ELECTIONS = {
    "overtime_base": {
        "label": "Overtime base", "bn": "ওভারটাইমের ভিত্তি",
        "question": "What does the s.108 hourly rate divide?",
        "options": [("BASIC_PLUS_DA", "Basic + dearness allowance"), ("GROSS", "Gross salary"),
                    ("CUSTOM", "Custom component selection")],
        "citation": "overtime", "preset": None,
        "governs": "the hourly overtime rate",
    },
    "proration_method": {
        "label": "Proration", "bn": "আংশিক মাসের হিসাব",
        "question": "How is a part month paid?",
        "options": [("CALENDAR_DAYS", "Calendar days"), ("FIXED_30", "Fixed 30"),
                    ("WORKING_DAYS_26", "Working days (26)"), ("ACTUAL_WORKING_DAYS", "Actual working days")],
        "citation": "proration", "preset": None,
        "governs": "part-month pay for joiners, leavers and arrears",
    },
    "gratuity_basis": {
        "label": "Gratuity basis", "bn": "গ্র্যাচুইটির ভিত্তি",
        "question": "What wage is gratuity computed on?",
        "options": [("BASIC", "Basic"), ("GROSS", "Gross"), ("CUSTOM", "Custom component selection")],
        "citation": "gratuity", "preset": None,
        "governs": "the separation payout and the monthly provision",
    },
    "days_worked_basis": {
        "label": "Days worked for earned leave", "bn": "অর্জিত ছুটির জন্য কর্মদিবস",
        "question": "Which days count toward earned leave?",
        "options": [], "flags": [("present", "Days present"), ("paidLeave", "Paid leave"),
                                 ("festival", "Festival holidays"), ("weekly", "Weekly holidays"),
                                 ("maternity", "Maternity leave")],
        "citation": "earnedLeave", "preset": {"present": True, "paidLeave": False, "festival": False,
                                               "weekly": False, "maternity": False},
        "governs": "the numerator of the earned-leave ratio",
    },
    "festival_bonus_policy": {
        "label": "Festival bonus under a year", "bn": "এক বছরের কম চাকরিতে উৎসব ভাতা",
        "question": "What does an employee with under a year's service receive?",
        "options": [("NONE", "Nothing — the statutory position"), ("PRO_RATA", "Pro-rata by completed months"),
                    ("FULL", "Full bonus"), ("BANDED", "Banded percentage")],
        "citation": "festivalBonus", "preset": None,
        "governs": "the festival bonus of anyone under twelve months' service",
    },
    "rounding_mode": {
        "label": "Rounding", "bn": "পূর্ণসংখ্যায় রূপান্তর",
        "question": "How is each payslip line rounded?",
        "options": [("PAISA", "Nearest paisa"), ("TAKA", "Nearest taka"), ("TEN_TAKA", "Nearest 10 taka")],
        "citation": "wagePayment", "suffix": " — wages payable without unauthorised deduction", "preset": "TAKA",
        "governs": "every payslip line, once, never below the paisa figure",
    },
    "balancing_component": {
        "label": "Balancing component", "bn": "সমন্বয়কারী উপাদান",
        "question": "Where does the rounding residue land when a structure is built from percentages?",
        "options": [("BASIC", "Basic salary"), ("HRA", "House rent allowance"), ("MED", "Medical allowance")],
        "citation": "wagePayment", "preset": "BASIC",
        "governs": "the default balancing line of a new structure template",
    },
}
ELECTION_KEYS = tuple(ELECTIONS)
NO_DEFAULT = tuple(k for k, v in ELECTIONS.items() if v["preset"] is None)
DAYS_WORKED_FLAGS = tuple(f for f, _ in ELECTIONS["days_worked_basis"]["flags"])
# Components a CUSTOM base may pick from (§3.3).
CUSTOM_COMPONENTS = ("BASIC", "DA", "HRA", "MED", "CONV", "FOOD", "OTHER")
DEFAULT_BANDS = [{"fromMonths": 0, "toMonths": 2, "pct": "0"}, {"fromMonths": 3, "toMonths": 5, "pct": "25"},
                 {"fromMonths": 6, "toMonths": 8, "pct": "50"}, {"fromMonths": 9, "toMonths": 11, "pct": "75"}]
HOURS_RANGE = (100, 400)

SCHEMES = {
    "PF": {"label": "Provident fund", "bn": "ভবিষ্য তহবিল", "citation": "pf",
           "expense": ("5210", "Provident fund expense"), "liability": ("2310", "Provident fund payable")},
    "GRATUITY": {"label": "Gratuity", "bn": "গ্র্যাচুইটি", "citation": "gratuity",
                 "expense": ("5220", "Gratuity provision"), "liability": ("2320", "Gratuity payable")},
    "GROUP_INSURANCE": {"label": "Group insurance", "bn": "গোষ্ঠী বীমা", "citation": "insurance",
                        "expense": ("5230", "Group insurance premium"), "liability": None},
    "WPPF": {"label": "WPPF", "bn": "শ্রমিক অংশগ্রহণ তহবিল", "citation": "wppf",
             "expense": ("5240", "WPPF contribution"), "liability": ("2330", "WPPF payable")},
}
SCHEME_CODES = tuple(SCHEMES)
# Per-employee participation applies to these; WPPF is a share of profit,
# distributed by the trustees, not a payroll enrolment.
PARTICIPATION_SCHEMES = ("PF", "GRATUITY", "GROUP_INSURANCE")


class ElectionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Proposed, awaiting approval"
    ACTIVE = "ACTIVE", "In force"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    REJECTED = "REJECTED", "Rejected"


class FrequencyChoices(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    FORTNIGHTLY = "FORTNIGHTLY", "Fortnightly"
    WEEKLY = "WEEKLY", "Weekly"
    DAILY = "DAILY", "Daily"


class SchemeStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "In force"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class AuditActionChoices(models.TextChoices):
    ELECTED = "ELECTED", "Elected"
    PROPOSED = "PROPOSED", "Proposed"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    REJECTED = "REJECTED", "Rejected"
    SCHEME_ENABLED = "SCHEME_ENABLED", "Scheme enabled"
    SCHEME_DISABLED = "SCHEME_DISABLED", "Scheme disabled"
    SCHEME_CHANGED = "SCHEME_CHANGED", "Scheme changed"
    RATE_CHANGED = "RATE_CHANGED", "Rate changed"
    GL_MAPPED = "GL_MAPPED", "GL account mapped"
    SCHEDULE_CHANGED = "SCHEDULE_CHANGED", "Schedule changed"
    ENROLLED = "ENROLLED", "Enrolled"
    OPTED_OUT = "OPTED_OUT", "Opted out"


PF_ELIGIBILITY = ("ON_JOINING", "ON_CONFIRMATION", "AFTER_MONTHS")
GRATUITY_METHODS = ("MONTHLY_PROVISION", "FUNDED_SCHEME")
INSURANCE_COVERAGE = ("ALL_WORKERS", "PERMANENT_ONLY", "CUSTOM")
