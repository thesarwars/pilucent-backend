from django.db import models


class CompanyStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    REMOVED = "REMOVED", "Removed"


class CompanyInvitationStatusChoices(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REVOKED = "REVOKED", "Revoked"
    EXPIRED = "EXPIRED", "Expired"


class CompanyShiftKindChoices(models.TextChoices):
    DAY = "DAY", "Day"
    NIGHT = "NIGHT", "Night"
    SWING = (
        "SWING",
        "Swing",
    )  # A shift that typically spans both day and night hours, like 2 PM to 10 PM.
    WEEKEND = "WEEKEND", "Weekend"
    PART_TIME = "PART_TIME", "Part Time"
    OVERTIME = "OVERTIME", "Overtime"


class CompanyShiftStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class CompanyDepartmentStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class CompanySectionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class CompanyDesignationStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    IN_ACTIVE = "IN_ACTIVE", "In Active"
    REMOVED = "REMOVED", "Removed"


class CompanyAccountingMethodChoices(models.TextChoices):
    ACCRUAL = "ACCRUAL", "Accrual"
    CASH = "CASH", "Cash"


class CompanySettingTaxFormChoices(models.TextChoices):
    SOLO_PROPRIETOR = "SOLO_PROPRIETOR", "Sole proprietor (Form 1040)"
    PARTNERSHIP_LLC = (
        "PARTNERSHIP_LLC",
        "Partnership or limited liability company (Form 1065)",
    )
    SMALL_BUSINESS_CORP = (
        "SMALL_BUSINESS_CORP",
        "Small business corporation, two or more owners (Form 1120S)",
    )
    CORPORATION = "CORPORATION", "Corporation, one or more shareholders (Form 1120)"
    NONPROFIT_ORG = "NONPROFIT_ORG", "Nonprofit organization (Form 990)"
    LIMITED_LIABILITY = "LIMITED_LIABILITY", "Limited liability"
    NOT_SURE_NONE = "NOT_SURE_NONE", "Not sure/Other/None"
    TRUST = "TRUST", "Trust"


class CompanyKindChoices(models.TextChoices):
    CONSTRUCTION = "CONSTRUCTION", "Construction"
    PROPERTY_BOOKKEEPING = "PROPERTY_BOOKKEEPING", "Property Bookkeeping"
    REAL_ESTATE = "REAL_ESTATE", "Real Estate Company"
    ECOMMERCE = "ECOMMERCE", "E-commerce"
    FASHION_APPAREL = "FASHION_APPAREL", "Fashion and Apparel Industry"
    FOOD_BEVERAGE = "FOOD_BEVERAGE", "Food and Beverage Industry"
    HARDWARE_ELECTRONICS = "HARDWARE_ELECTRONICS", "Hardware and Electronics Industry"
    LEGAL_BOOKKEEPING = "LEGAL_BOOKKEEPING", "Legal Bookkeeping"
    AGRICULTURE = "AGRICULTURE", "Agriculture Industry"
    AUTOMOBILE = "AUTOMOBILE", "Automobile Industry"
    EDUCATION_TRAINING = "EDUCATION_TRAINING", "Education and Training Industry"
    RESTAURANT_HOTEL = "RESTAURANT_HOTEL", "Restaurant and Hotel Business"
    SPORTS_FITNESS = "SPORTS_FITNESS", "Sports and Fitness Industry"
    TRAVEL_TOURISM = "TRAVEL_TOURISM", "Travel and Tourism Industry"
    RETAIL_WHOLESALE = "RETAIL_WHOLESALE", "Retail and Wholesale Industry"
    MEDICAL_PHARMACEUTICAL = (
        "MEDICAL_PHARMACEUTICAL",
        "Medical and Pharmaceutical Industry",
    )
    MARKETING_ADVERTISING = (
        "MARKETING_ADVERTISING",
        "Marketing and Advertising Industry",
    )
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES", "Financial Services Industry"
    BUSINESS_CONSULTING = (
        "BUSINESS_CONSULTING",
        "Business Services and Consulting Industry",
    )
    BROKERAGE_HOUSE = "BROKERAGE_HOUSE", "Brokerage House"
