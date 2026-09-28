from django.db import models


class SalaryAdjustmentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class SalaryAdjustmentKindChoices(models.TextChoices):
    ADDITION = "ADDITION", "Addition"
    DEDUCTION = "DEDUCTION", "Deduction"


class DeductionAndContributionChoices(models.TextChoices):
    PRETAX = "PRETAX", "Pretax"
    POST_TAX = "POST_TAX", "Post-Tax"


class PayScheduleStatusChoice(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class PayScheduleMonthChoice(models.TextChoices):
    SAME = "SAME", "Same"
    PREVIOUS = "PREVIOUS", "Previous"
    NEXT = "NEXT", "Next"


class PayFrequencyChoice(models.TextChoices):
    EVERY_WEEK = "EVERY_WEEK", "Every Week"
    OTHER_WEEK = "OTHER_WEEK", "Other Week"
    TWICE_A_MONTH = "TWICE_A_MONTH", "Twice A Month"
    EVERY_MONTH = "EVERY_MONTH", "Every Month"


class EndDayChoice(models.TextChoices):
    END_DAY = "END_DAY", "End Day"
    BEFORE_END_DAY = "BEFORE_END_DAY", "Before end day"


class SalaryProcessPayMethodChoice(models.TextChoices):
    PAPER_CHECK = "PAPER_CHECK", "Paper Check"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT", "Direct Deposit"


class PayrollSalaryProcessStatusChoices(models.TextChoices):
    """Lifecycle of a single payroll run for an employee.

    Only FINALIZED runs count toward Year-to-Date totals and toward wage-cap
    enforcement (Social Security, FUTA, etc.). DRAFT runs are in-progress and
    excluded; VOIDED runs are reversed and also excluded.
    """

    DRAFT = "DRAFT", "Draft"
    FINALIZED = "FINALIZED", "Finalized"
    VOIDED = "VOIDED", "Voided"


class PayTypeChoice(models.TextChoices):
    REGULAR = "REGULAR", "Regular Pay"
    OVERTIME = "OVERTIME", "Overtime Pay"
    DOUBLE_OVERTIME = "DOUBLE_OVERTIME", "Double Overtime Pay"
    PAID_TIME_OFF = "PAID_TIME_OFF", "Paid Time Off"
    UNPAID_TIME_OFF = "UNPAID_TIME_OFF", "Unpaid Time Off"
    SICK = "SICK", "Sick Pay"
    VACATION = "VACATION", "Vacation Pay"
    HOLIDAY = "HOLIDAY", "Holiday Pay"
    BONUS = "BONUS", "Bonus"
    COMMISSION = "COMMISSION", "Commission"


class PayrollComponentCategoryChoice(models.TextChoices):
    PAY = "PAY", "Pay"
    EMPLOYEE_TAXES = "EMPLOYEE_TAXES", "Employee Taxes"
    EMPLOYEE_DEDUCTIONS = "EMPLOYEE_DEDUCTIONS", "Employee Deductions"
    EMPLOYER_TAXES = "EMPLOYER_TAXES", "Employer Taxes"
    COMPANY_PAID_CONTRIBUTIONS = (
        "COMPANY_PAID_CONTRIBUTIONS",
        "Company Paid Contributions",
    )
    # TIME_OFF = "TIME_OFF", "Time Off"


class PayrollGeneralTaxCompanyTypeChoices(models.TextChoices):
    OTHER = "OTHER", "Other"
    NON_PROFIT_501C3_CORP = "NON_PROFIT_501C3_CORP", "Non Profit 501c3 Corp"
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR", "Sole Proprietor"


class PayrollFederalTaxInfoSettingChoices(models.TextChoices):
    SEMI_WEEKLY = "SEMI_WEEKLY", "Semi-Weekly (Recommended)"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    ANNUALLY = "ANNUALLY", "Annually"


class PayrollFederalTaxInfoTaxFormChoices(models.TextChoices):
    FORM_941_EACH_QUARTER = (
        "FORM_941_EACH_QUARTER",
        "Form 941 each quarter (most common)",
    )
    FORM_943_EACH_YEAR = "FORM_943_EACH_YEAR", "Form 943 each year (agricultural)"
    FORM_944_EACH_YEAR = "FORM_944_EACH_YEAR", "Form 944 each year"


class PayrollStateTaxInfoSettingChoices(models.TextChoices):
    SEMI_WEEKLY = "SEMI_WEEKLY", "Semi-Weekly (Recommended)"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    ANNUALLY = "ANNUALLY", "Annually"
    THREE_DAYS_AFTER_PAYROLL = "3_DAYS_AFTER_PAYROLL", "3 Days after Payroll"
    FIVE_DAYS_AFTER_PAYROLL = "5_DAYS_AFTER_PAYROLL", "5 Days after Payroll"


class PayrollStateMCTMTZoneChoices(models.TextChoices):
    ZONE_1 = "ZONE_1", "Zone 1"
    ZONE_2 = "ZONE_2", "Zone 2"


class PayrollWorkLocationChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


# accounting preferences types related choices

class AccountingPreferencesExpenseTypeChoices(models.TextChoices):
    # wage expense types 
    SINGLE_WAGE_ACCOUNT = (
        "SINGLE_WAGE_ACCOUNT",
        "All my employee's wages are posted to one expense account",
    )
    PER_WAGE_EMPLOYEE = (
        "PER_WAGE_EMPLOYEE",
        "Each employee's wages are posted to their own expense account",
    )
    PER_WAGE_TYPE = (
        "PER_WAGE_TYPE",
        "Each employee's wages are posted to different types of accounts (ex: salary, contractor, and so on)",
    )
    # company contribution expense types
    COMPANY_CONTRIBUTION_SINGLE_ACCOUNT = (
        "COMPANY_CONTRIBUTION_SINGLE_ACCOUNT",
        "Company contributions of the same type are posted to one expense account",
    )
    COMPANY_CONTRIBUTION_PER_EMPLOYEE = (
        "COMPANY_CONTRIBUTION_PER_EMPLOYEE",
        "Company contributions for each employee are posted to their own expense account",
    )
    COMPANY_CONTRIBUTION_DIFFERENT_TYPE = (
        "COMPANY_CONTRIBUTION_DIFFERENT_TYPE",
        "Company contributions of different types are posted to different accounts (ex: salary, contractor, and so on)",
    )
    # employer tax expense types
    SINGLE_EMPLOYER_TAX_ACCOUNT = (
        "SINGLE_EMPLOYER_TAX_ACCOUNT",
        "All employer taxes are posted to one expense account.",
    )
    PER_EMPLOYER_TAX_EXPENSE = (
        "PER_EMPLOYER_TAX_EXPENSE",
        "Employer taxes are posted to different expense accounts for different employees.",
    )
    DIFFERENT_TAX_DIFFERENT_GROUP = (
        "DIFFERENT_TAX_DIFFERENT_GROUP",
        "Employer taxes are posted to different expense accounts for different groups of taxes.",
    )
    DIFFERENT_EXPENSE_DIFFERENT_TAX = (
        "DIFFERENT_EXPENSE_DIFFERENT_TAX",
        "Employer taxes are posted to different expense accounts for different tax items.",
    )
    # tax liability account types
    DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP = (
        "DIFFERENT_LIABILITY_DIFFERENT_TAX_GROUP",
        "Tax Liabilities are posted to different accounts for different Tax Groups.",
    )
    DIFFERENT_LIABILITY_DIFFERENT_TAX_ITEMS = (
        "DIFFERENT_LIABILITY_DIFFERENT_TAX_ITEMS",
        "Tax Liabilities are posted to different accounts for different Tax Items.",
    )
    # other liability and asset account types
    OTHER_LIABILITY_ASSETS_TYPE = (
        "OTHER_LIABILITY_ASSETS_TYPE",
        "Other Liabilities and Assets"
    )
    

class PayrollGeneralSettingsWorkingChoices(models.TextChoices):
    CALENDAR_DAYS = "CALENDAR_DAYS", "Calendar Days"
    WORKING_DAYS = "WORKING_DAYS", "Working Days"


class PayrollTaxConfigStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"


class PayrollGeneralSettingsEmailTemplateChoices(models.TextChoices):
    DEFAULT_TEMPLATE = "DEFAULT_TEMPLATE", "Default Template"
    CUSTOM_TEMPLATE = "CUSTOM_TEMPLATE", "Custom Template"