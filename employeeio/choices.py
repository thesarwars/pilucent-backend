from django.db import models


class EmployeeKindChoices(models.TextChoices):
    FULL_TIME = "FULL_TIME", "Full time"
    PART_TIME = "PART_TIME", "Part time"
    CONTRACT = "CONTRACT", "CONTRACT"
    TEMORARY = "TEMPORARY", "Temporary"
    SEASONAL = "SEASONAL", "Seasonal"
    VOLUNTEER = "VOLUNTEER", "Volunteer"
    INTERN = "INTERN", "Intern"
    TRAINEE = "TRAINEE", "Trainee"
    OTHER = "OTHER", "Other"


class EmployeeStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeLevelChoices(models.TextChoices):
    SENIOR = "SENIOR", "Senior"
    JUNIOR = "JUNIOR", "Junior"
    LEAD = "LEAD", "Lead"
    TEAM_LEAD = "TEAM_LEAD", "Team Lead"
    TECH_LEAD = "TECH_LEAD", "Tech Lead"
    MID_LEVEL = "MID_LEVEL", "Mid-level"
    ASSOCIATE = "ASSOCIATE", "Associate"


class EmployeeSalaryKind(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
    CHEQUE = "CHEQUE", "Cheque"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    DEBIT_CARD = "DEBIT_CARD", "Debit Card"
    CASH = "CASH", "Cash"
    PAYPAL = "PAYPAL", "PayPal"
    MOBILE_PAYMENT = "MOBILE_PAYMENT", "Mobile Payment"
    DIGITAL_WALLET = "DIGITAL_WALLET", "Digital Wallet"
    FIXED = "FIXED", "Fixed"


class EmployeeBankingInfoChoices(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    DEBIT_CARD = "DEBIT_CARD", "Debit Card"
    PAYPAL = "PAYPAL", "PayPal"
    MOBILE_PAYMENT = "MOBILE_PAYMENT", "Mobile Payment"
    DIGITAL_WALLET = "DIGITAL_WALLET", "Digital Wallet"


class EmployeeSalaryStatusChoices(models.TextChoices):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeNoticePeriodChoices(models.TextChoices):
    ONE_DAY = "ONE_DAY", "One Day"
    FIVE_DAYS = "FIVE_DAYS", "Five Days"
    SEVEN_DAYS = "SEVEN_DAYS", "Seven Days"
    FIFTEEN_DAYS = "FIFTEEN_DAYS", "Fifteen Days"
    THIRTY_DAYS = "THIRTY_DAYS", "Thirty Days"
    FORTY_FIVE_DAYS = "FORTY_FIVE_DAYS", "Forty-Five Days"
    SIXTY_DAYS = "SIXTY_DAYS", "Sixty Days"
    NINETY_DAYS = "NINETY_DAYS", "Ninety Days"


class EmployeeTerminateKindChoices(models.TextChoices):
    FULL = "FULL", "Full"
    PARTIALLY = "PARTIALLY", "Partially"

    # Voluntary
    RESIGNATION = (
        "RESIGNATION",
        "Resignation",
    )
    RETIREMENT = "RETIREMENT", "Retirement"
    JOB_ABANDONMENT = "JOB_ABANDONMENT", "Job Abandonment"
    FAILURE_TO_RETURN = "FAILURE_TO_RETURN", "Failure to Return"
    MUTUAL_SEPARATION = (
        "MUTUAL_SEPARATION",
        "Mutual Separation",
    )

    # Involuntary
    LAYOFF = "LAYOFF", "Layoff"
    POSITION_ELIMINATION = (
        "POSITION_ELIMINATION",
        "Position Elimination",
    )
    END_TEMP_ASSIGNMENT = "END_TEMP_ASSIGNMENT", "End Temporary Assignment"
    CONTRACT_END = (
        "CONTRACT_END",
        "Contract End",
    )

    # Involuntary (Cause-related)
    PERFORMANCE = "PERFORMANCE", "Performance"
    MISCONDUCT = ("MISCONDUCT", "Misconduct / Policy Violation")
    ATTENDANCE = "ATTENDANCE", "Attendance"
    PROBATIONARY_DISMISSAL = ("PROBATIONARY_DISMISSAL", "Probationary Sismissal")

    # Other / Legal
    DEATH = "DEATH", "Death"
    MEDICAL_SEPARATION = ("MEDICAL_SEPARATION", "Medical Separation")
    CONSTRUCTIVE_DISCHARGE = ("CONSTRUCTIVE_DISCHARGE", "Constructive Discharge")


class EmployeeBankingInformationStatusChoices(models.TextChoices):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeBankingInformationKindChoices(models.TextChoices):
    PAPER_CHECK = "PAPER_CHECK", "Paper Check"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
    CASH = "CASH", "Cash"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    DEBIT_CARD = "DEBIT_CARD", "Debit Card"
    MOBILE_PAYMENT = "MOBILE_PAYMENT", "Mobile Payment"
    DIGITAL_WALLET = "DIGITAL_WALLET", "Digital Wallet"


class EmployeeEducationStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeBankingInformationAccountKind(models.TextChoices):
    CHECKING = "CHECKING", "Checking"
    SAVINGS = "SAVINGS", "Savings"


class EmployeeTaxMartialChoicess(models.TextChoices):
    MARRIED = "MARRIED", "Married"
    UN_MARRIED = "UN_MARRIED", "Un Married"
    OTHER = "OTHER", "Other"


class EmployeeTaxExemptChoicess(models.TextChoices):
    EXEMPT = "EXEMPT", "Exempt"
    NOT_EXEMPT = "NOT_EXEMPT", "Not Exempt"


class EmployeeTaxW4KindChoicess(models.TextChoices):
    YEAR_2019_OR_EARLY = "YEAR_2019_OR_EARLY", "Year 2019 Or Early"
    YEAR_2020_OR_LETTER = "YEAR_2020_OR_LETTER", "Year 2020 Or Letter"


class EmployeeTaxHoldingStatusChoicess(models.TextChoices):
    SINGLE_OR_MARRIED_FILING_SEPARATLEY = (
        "SINGLE_OR_MARRIED_FILING_SEPARATLEY",
        "Single Or Married Filing Separatley",
    )
    MARRIED_FILING_JOINTLY_OR_QUALIYING_WIDOW = (
        "MARRIED_FILING_JOINTLY_OR_QUALIYING_WIDOW",
        "Married Filing Jointly Or Qualifying Widow",
    )
    HEAD_OF_HOUSHOLD = "HEAD_OF_HOUSHOLD", "Head Of Houshold"
    EXEMPT = "EXEMPT", "Exempt"


class EmployeePayKindChoices(models.TextChoices):
    SALARY = "SALARY", "Salary"
    HOURLY = "HOURLY", "HOURLY"
    COMMISSION = "COMMISSION", "Commission"


class EmployeeSalaryFrequencyChoices(models.TextChoices):
    PER_YEAR = "PER_YEAR", "Per Year"
    PER_MONTH = "PER_MONTH", "Per Month"
    PER_WEEK = "PER_WEEK", "Per Week"


class EmployeeEarningStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeEarningPayKindChoices(models.TextChoices):
    ALLOWANCE = "ALLOWANCE", "Allowance"
    REIMBURSEMENT = "REIMBURSEMENT", "Reimbursement"
    CASH_TIPS = "CASH_TIPS", "Cash Tips"
    PAYCHECK_TIPS = "PAYCHECK_TIPS", "Paycheck Tips"
    CLERGY_HOUSING_CASH = "CLERGY_HOUSING_CASH", "Clergy Housing (Cash)"
    CLERGY_HOUSING_IN_KIND = "CLERGY_HOUSING_IN_KIND", "Clergy Housing (In-Kind)"
    NONTAXABLE_PER_DIEM = "NONTAXABLE_PER_DIEM", "Nontaxable Per Diem"
    GROUP_TERM_LIFE_INSURANCE = "GROUP_TERM_LIFE_INSURANCE", "Group-Term Life Insurance"
    S_CORP_OWNERS_HEALTH_INSURANCE = (
        "S_CORP_OWNERS_HEALTH_INSURANCE",
        "S-Corp Owners Health Insurance",
    )
    COMPANY_HSA_CONTRIBUTION = "COMPANY_HSA_CONTRIBUTION", "Company HSA Contribution"
    PERSONAL_USE_OF_COMPANY_CAR = (
        "PERSONAL_USE_OF_COMPANY_CAR",
        "Personal Use of Company Car",
    )
    BEREAVEMENT_PAY = "BEREAVEMENT_PAY", "Bereavement Pay"
    OTHER_EARNINGS = "OTHER_EARNINGS", "Other Earnings"
    NEW_YORK_HWB_BONUS_PROGRAM = (
        "NEW_YORK_HWB_BONUS_PROGRAM",
        "New York (HWB) Worker Bonus Program",
    )


class EmployeeDeductionContributionKindChoices(models.TextChoices):
    FLAT_AMOUNT = "FLAT_AMOUNT", "Flat Amount"
    PERCENT_OF_GROSS_PAY = "PERCENT_OF_GROSS_PAY", "Percent Of Gross Pay"
    PER_HOUR_WORKED = "PER_HOUR_WORKED", "Per Hour Worked"


class EmployeeDeductionContributionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeGarnishmentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeGarnishmentKindChoices(models.TextChoices):
    CHILD_SPOUSAL_SUPPORT = "CHILD_SPOUSAL_SUPPORT", "Child/Spousal Support"
    FEDERAL_TAX_LEVY = "FEDERAL_TAX_LEVY", "Federal tax Levy"
    OTHER_GARNISHMENT = "OTHER_GARNISHMENT", "Other Garnishment"


class EmployeeWorkExperienceStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class EmployeeWorkExperienceKindChoices(models.TextChoices):
    HISTORY = "HISTORY", "History"
    EXPERIENCE = "EXPERIENCE", "Experience"


class EmployeeOnboardingKindChoices(models.TextChoices):
    SELF_ONBOARD_WITH_I9 = "SELF_ONBOARD_WITH_I9", "Employee self onboard with form i-9"
    SELF_ONBOARD = "SELF_ONBOARD", "Employee self onboard"
    MANUAL_ENTRY = "MANUAL_ENTRY", "I'll enter all their info myself"


class EmployeeCitizenshipKindChoices(models.TextChoices):
    US_CITIZEN = "US_CITIZEN", "US citizen"
    LAWFUL_RESIDENT = "LAWFUL_RESIDENT", "Lawful permanent resident"
    NONCITIZEN_OF_USA = "NONCITIZEN_OF_USA", "Noncitizen nation of the U.S"
    OTHER = "OTHER", "Other"


class EmployeeExpenseReportStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    REVIEW = "REVIEW", "Review"
    REQUEST_CHANGES = "REQUEST_CHANGES", "Request Changes"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    PAID = "PAID", "Paid"
