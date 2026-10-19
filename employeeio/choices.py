"""Enums for the BD employee profile. Every value is the contract's
(`docs/employee-profile.md` §2) -- the front end computes against these exact
strings, so a renamed value is a silently wrong payslip.
"""

from django.db import models


class EmployeeStatusChoices(models.TextChoices):
    """Record lifecycle, not employment status. Leaving employment is a
    separation (`separated_on`); REMOVED is an admin taking the record out of
    use, which also deactivates a linked login (see signals)."""

    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


# ------------------------------------------------------------ identity (§2.1)


class MaritalChoices(models.TextChoices):
    SINGLE = "SINGLE", "Single"
    MARRIED = "MARRIED", "Married"
    DIVORCED = "DIVORCED", "Divorced"
    WIDOWED = "WIDOWED", "Widowed"


class GenderChoices(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    THIRD_GENDER = "THIRD_GENDER", "Third gender"


class BloodGroupChoices(models.TextChoices):
    # '' is "not recorded" -- a truthful blank, not a missing default.
    NOT_RECORDED = "", "Not recorded"
    A_POS = "A+", "A+"
    A_NEG = "A-", "A-"
    B_POS = "B+", "B+"
    B_NEG = "B-", "B-"
    O_POS = "O+", "O+"
    O_NEG = "O-", "O-"
    AB_POS = "AB+", "AB+"
    AB_NEG = "AB-", "AB-"


class ReligionChoices(models.TextChoices):
    NOT_RECORDED = "", "Not recorded"
    ISLAM = "ISLAM", "Islam"
    HINDU = "HINDU", "Hindu"
    BUDDHIST = "BUDDHIST", "Buddhist"
    CHRISTIAN = "CHRISTIAN", "Christian"
    OTHER = "OTHER", "Other"


class DivisionChoices(models.TextChoices):
    DHAKA = "DHAKA", "Dhaka"
    CHATTOGRAM = "CHATTOGRAM", "Chattogram"
    KHULNA = "KHULNA", "Khulna"
    RAJSHAHI = "RAJSHAHI", "Rajshahi"
    SYLHET = "SYLHET", "Sylhet"
    BARISHAL = "BARISHAL", "Barishal"
    RANGPUR = "RANGPUR", "Rangpur"
    MYMENSINGH = "MYMENSINGH", "Mymensingh"


class RelationChoices(models.TextChoices):
    SPOUSE = "SPOUSE", "Spouse"
    SON = "SON", "Son"
    DAUGHTER = "DAUGHTER", "Daughter"
    FATHER = "FATHER", "Father"
    MOTHER = "MOTHER", "Mother"
    BROTHER = "BROTHER", "Brother"
    SISTER = "SISTER", "Sister"
    OTHER = "OTHER", "Other"


# ---------------------------------------------------------- employment (§2.2)


class ClassificationChoices(models.TextChoices):
    """Determined by work performed, not job title (s.2(65), 2026 amendment)."""

    WORKER = "WORKER", "Worker"
    NON_WORKER = "NON_WORKER", "Non-worker"


class WorkerCategoryChoices(models.TextChoices):
    PERMANENT = "PERMANENT", "Permanent"
    PROBATIONER = "PROBATIONER", "Probationer"
    TEMPORARY = "TEMPORARY", "Temporary"
    CASUAL = "CASUAL", "Casual"
    BADLI = "BADLI", "Badli"
    APPRENTICE = "APPRENTICE", "Apprentice"
    SEASONAL = "SEASONAL", "Seasonal"


class EstablishmentChoices(models.TextChoices):
    FACTORY = "FACTORY", "Factory"
    SHOP = "SHOP", "Shop"
    COMMERCIAL_ESTABLISHMENT = "COMMERCIAL_ESTABLISHMENT", "Commercial establishment"
    INDUSTRIAL_ESTABLISHMENT = "INDUSTRIAL_ESTABLISHMENT", "Industrial establishment"
    ROAD_TRANSPORT = "ROAD_TRANSPORT", "Road transport"
    TEA_PLANTATION = "TEA_PLANTATION", "Tea plantation"
    NEWSPAPER = "NEWSPAPER", "Newspaper"


class EmploymentTypeChoices(models.TextChoices):
    FULL_TIME = "FULL_TIME", "Full time"
    PART_TIME = "PART_TIME", "Part time"
    CONTRACT = "CONTRACT", "Contract"


class GradeChoices(models.TextChoices):
    G1 = "G1", "Grade 1"
    G2 = "G2", "Grade 2"
    G3 = "G3", "Grade 3"
    G4 = "G4", "Grade 4"
    G5 = "G5", "Grade 5"
    G6 = "G6", "Grade 6"
    G7 = "G7", "Grade 7"


class SeparationTypeChoices(models.TextChoices):
    TERMINATION = "TERMINATION", "Termination"
    RETRENCHMENT = "RETRENCHMENT", "Retrenchment"
    DISCHARGE = "DISCHARGE", "Discharge"
    DISMISSAL = "DISMISSAL", "Dismissal"
    RESIGNATION = "RESIGNATION", "Resignation"
    RETIREMENT = "RETIREMENT", "Retirement"
    DEATH = "DEATH", "Death"


# ----------------------------------------------------------- statutory (§2.4)


# --------------------------------------------------------- tax profile (§2.5)


class TaxpayerCategoryChoices(models.TextChoices):
    GENERAL = "GENERAL", "General"
    FEMALE = "FEMALE", "Female"
    SENIOR_CITIZEN_65_PLUS = "SENIOR_CITIZEN_65_PLUS", "Senior citizen (65+)"
    PERSON_WITH_DISABILITY = "PERSON_WITH_DISABILITY", "Person with disability"
    THIRD_GENDER = "THIRD_GENDER", "Third gender"
    WAR_WOUNDED_FREEDOM_FIGHTER = "WAR_WOUNDED_FREEDOM_FIGHTER", "War-wounded freedom fighter"
    NON_RESIDENT_FOREIGN = "NON_RESIDENT_FOREIGN", "Non-resident foreign"


class VehicleChoices(models.TextChoices):
    NONE = "NONE", "None"
    UPTO_2500 = "UPTO_2500", "Up to 2500cc"
    ABOVE_2500 = "ABOVE_2500", "Above 2500cc"


# --------------------------------------------------------- investments (§2.6)


class InstrumentChoices(models.TextChoices):
    DPS = "DPS", "DPS"
    LIFE_INSURANCE_PREMIUM = "LIFE_INSURANCE_PREMIUM", "Life insurance premium"
    SANCHAYAPATRA = "SANCHAYAPATRA", "Sanchayapatra"
    LISTED_SHARES = "LISTED_SHARES", "Listed shares"
    MUTUAL_FUND = "MUTUAL_FUND", "Mutual fund"
    RECOGNISED_PROVIDENT_FUND = "RECOGNISED_PROVIDENT_FUND", "Recognised provident fund"
    APPROVED_DONATION = "APPROVED_DONATION", "Approved donation"
    OTHER = "OTHER", "Other"


# ------------------------------------------------------------- payment (§2.7)


class PaymentMethodChoices(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
    MFS = "MFS", "Mobile financial service"
    CASH = "CASH", "Cash"


class MfsProviderChoices(models.TextChoices):
    BKASH = "BKASH", "bKash"
    NAGAD = "NAGAD", "Nagad"
    ROCKET = "ROCKET", "Rocket"
    UPAY = "UPAY", "Upay"


class WalletTypeChoices(models.TextChoices):
    SALARY = "SALARY", "Salary"
    PERSONAL = "PERSONAL", "Personal"


# ------------------------------------------------------------- history (§8)


class TrackedFieldChoices(models.TextChoices):
    CLASSIFICATION = "classification", "Classification"
    DESIGNATION = "designation", "Designation"
    GRADE = "grade", "Grade"
    DEPARTMENT = "department", "Department"
    SHIFT = "shift", "Shift"
    SECTION = "section", "Section"
    SALARY = "salary", "Salary"
    # Not in the §8 list of effective-dated fields, but a gated operation, and
    # every gated operation writes an entry with its reason (§8).
    SEPARATION = "separation", "Separation"


# ------------------------------------------------------ salary structure (§5)


class SalaryComponentChoices(models.TextChoices):
    BASIC = "BASIC", "Basic salary"
    HRA = "HRA", "House rent allowance"
    MED = "MED", "Medical allowance"
    CONV = "CONV", "Conveyance allowance"
    DA = "DA", "Dearness allowance"
    # Beyond the contract's list: the RMG gazette's food allowance, without
    # which an RMG structure cannot reach its own total-wage floor.
    FOOD = "FOOD", "Food allowance"
    # The balancing line of a template that allocates less than all of gross
    # (worker 95.5%, staff 99%), and of an override that keeps gross fixed.
    OTHER = "OTHER", "Other allowance"


class SalaryTemplateChoices(models.TextChoices):
    """Template codes. Officer, worker and staff are rows of `SalaryTemplate`
    (per company, versioned); RMG is built from the gazette in the rule book.
    std and classic are retired: structures on them still read, and their next
    revision moves them to a current template."""

    OFFICER = "officer", "Officer grade template"
    WORKER = "worker", "Worker grade template"
    STAFF = "staff", "Staff grade template"
    RMG = "rmg", "RMG gazette grade template"
    STD = "std", "Standard 60/50 (retired)"
    CLASSIC = "classic", "Classic 1.5 divisor (retired)"


class RevisionMethodChoices(models.TextChoices):
    PERCENTAGE_INCREASE = "PERCENTAGE_INCREASE", "Percentage increase"
    FIXED_INCREASE = "FIXED_INCREASE", "Fixed increase"
    NEW_GROSS = "NEW_GROSS", "New gross"
    # The RMG template is built up from basic: its revisions name a basic.
    NEW_BASIC = "NEW_BASIC", "New basic"
    CHANGE_TEMPLATE = "CHANGE_TEMPLATE", "Change template"
    # Components set one by one against the template (salary profile §11.2).
    OVERRIDE = "OVERRIDE", "Component override"


class RevisionTypeChoices(models.TextChoices):
    FIRST_ASSIGNMENT = "FIRST_ASSIGNMENT", "First assignment"
    # Brought forward at migration -- NOT a first assignment: the employee's
    # first structure may predate this system by years.
    OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
    INCREMENT = "INCREMENT", "Increment"
    PROMOTION = "PROMOTION", "Promotion"
    STRUCTURE_CHANGE = "STRUCTURE_CHANGE", "Structure change"
    CORRECTION = "CORRECTION", "Correction"
    GRADE_REVISION = "GRADE_REVISION", "Grade revision"
    MINIMUM_WAGE_ADJUSTMENT = "MINIMUM_WAGE_ADJUSTMENT", "Minimum wage adjustment"


class ArrearsRunChoices(models.TextChoices):
    NEXT_RUN = "NEXT_RUN", "Next payroll run"
    SEPARATE_RUN = "SEPARATE_RUN", "Separate arrears run"


class ProrationDivisorChoices(models.TextChoices):
    """The proration election (payroll settings §2): all four are lawful and
    pay differently; the difference is largest in a 31-day month and in
    February. Elected in `paysetio`, never defaulted."""

    CALENDAR_DAYS = "CALENDAR_DAYS", "Calendar days"
    FIXED_30 = "FIXED_30", "Fixed 30"
    WORKING_DAYS_26 = "WORKING_DAYS_26", "Working days (26)"
    ACTUAL_WORKING_DAYS = "ACTUAL_WORKING_DAYS", "Actual working days"


# ----------------------------------------------------------- documents (§9)


class DocumentKindChoices(models.TextChoices):
    SERVICE_BOOK = "SERVICE_BOOK", "Service book"
    APPOINTMENT_LETTER = "APPOINTMENT_LETTER", "Appointment letter"
    ID_CARD = "ID_CARD", "ID card"


class SalaryStatusChoices(models.TextChoices):
    """Derived from the dates and the cancellation, never stored: a stored
    SCHEDULED would go stale the morning it took effect."""

    ACTIVE = "ACTIVE", "In force"
    SCHEDULED = "SCHEDULED", "Scheduled"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    CANCELLED = "CANCELLED", "Cancelled"


class OverrideBasisChoices(models.TextChoices):
    PCT_GROSS = "PCT_GROSS", "% of gross"
    PCT_BASIC = "PCT_BASIC", "% of basic"
    FIXED = "FIXED", "Fixed amount"


class SalaryAuditActionChoices(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Assigned"
    REVISED = "REVISED", "Revised"
    OVERRIDDEN = "OVERRIDDEN", "Overridden"
    SCHEDULED = "SCHEDULED", "Scheduled"
    CANCELLED = "CANCELLED", "Cancelled"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    VIEWED_MASKED = "VIEWED_MASKED", "Viewed masked"
    VIEWED_FULL = "VIEWED_FULL", "Viewed in full"
