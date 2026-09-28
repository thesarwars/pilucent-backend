from django.db import models


class SubscriptionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"
    PUBLISHED = "PUBLISHED", "Published"


class SubscriptionKindChoices(models.TextChoices):
    COMPANY_SUBSCRIPTION = "COMPANY_SUBSCRIPTION", "Company Subscription"
    ACCOUNTANT_SUBSCRIPTION = "ACCOUNTANT_SUBSCRIPTION", "Accountant Subscription"


class SubscriptionPriceBillingFrequencyChoices(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", " Quarterly"
    HALF_YEARLY = "HALF_YEARLY", "Half Yearly"
    YEARLY = "YEARLY", "Yearly"


class SubscriptionDiscountChoices(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    YEARLY = "YEARLY", "Yearly"
    QUARTERLY = "QUARTERLY", " Quarterly"


class CompanySubscriptionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    TRIALING = "TRIALING", "Trialing"
    PAST_DUE = "PAST_DUE", "Past Due"
    GRACE = "GRACE", "Grace"
    SUSPENDED = "SUSPENDED", "Suspended"
    CANCELED = "CANCELED", "Canceled"
    EXPIRED = "EXPIRED", "Expired"
    PENDING = "PENDING", "Pending"
    REMOVED = "REMOVED", "Removed"


class PlanVersionStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    ARCHIVED = "ARCHIVED", "Archived"


class FeatureAccessLevelChoices(models.TextChoices):
    NONE = "NONE", "None"
    READ = "READ", "Read"
    WRITE = "WRITE", "Write"
    FULL = "FULL", "Full"


class LimitMetricChoices(models.TextChoices):
    EMPLOYEE = "EMPLOYEE", "Employee"
    USER = "USER", "User"
    BRANCH = "BRANCH", "Branch"
    STORAGE = "STORAGE", "Storage"
    PAYROLL_RUN = "PAYROLL_RUN", "Payroll Run"
    AI_CREDIT = "AI_CREDIT", "AI Credit"


class LimitEnforcementModeChoices(models.TextChoices):
    HARD_BLOCK = "HARD_BLOCK", "Hard Block"
    SOFT_WARNING = "SOFT_WARNING", "Soft Warning"
    AUTO_OVERAGE = "AUTO_OVERAGE", "Auto Overage"
    MANUAL_APPROVAL = "MANUAL_APPROVAL", "Manual Approval"
    GRACE_OVERAGE = "GRACE_OVERAGE", "Grace Overage"


class CompanySubscriptionKindChoices(models.TextChoices):
    COMPANY_SUBSCRIPTION = "COMPANY_SUBSCRIPTION", "Company Subscription"
    ACCOUNTANT_SUBSCRIPTION = "ACCOUNTANT_SUBSCRIPTION", "Accountant Subscription"


class SubscriptionCanclePolicyStatusChoices(models.TextChoices):
    ANYTIME = "ANYTIME", "Anytime"


class SubscriptionInvoiceStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    VOID = "VOID", "Void"


class SubscriptionInvoiceLineTypeChoices(models.TextChoices):
    BASE = "BASE", "Base Plan"
    OVERAGE = "OVERAGE", "Overage"
    ADDON = "ADDON", "Add-on"
    DISCOUNT = "DISCOUNT", "Discount"
    CREDIT = "CREDIT", "Credit"
    PRORATION = "PRORATION", "Proration"
    TAX = "TAX", "Tax"


class CouponStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"
    EXPIRED = "EXPIRED", "Expired"


class OfferStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"


class SubscriptionCreditSourceChoices(models.TextChoices):
    REFERRAL = "REFERRAL", "Referral"
    PROMOTION = "PROMOTION", "Promotion"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT", "Admin Adjustment"
    REFUND = "REFUND", "Refund"


class AddOnPricingModelChoices(models.TextChoices):
    RECURRING = "RECURRING", "Recurring"
    ONE_TIME = "ONE_TIME", "One Time"
    USAGE_BASED = "USAGE_BASED", "Usage Based"


class AddOnStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"


class PlanAddOnAvailabilityChoices(models.TextChoices):
    OPTIONAL = "OPTIONAL", "Optional"
    REQUIRED = "REQUIRED", "Required"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"


class CompanyAddOnStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CANCELED = "CANCELED", "Canceled"


class ReferralRedemptionStatusChoices(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class SubscriptionEventTypeChoices(models.TextChoices):
    TRIAL_STARTED = "TRIAL_STARTED", "Trial Started"
    TRIAL_EXPIRED = "TRIAL_EXPIRED", "Trial Expired"
    TRIAL_CONVERTED = "TRIAL_CONVERTED", "Trial Converted"
    CHECKOUT_COMPLETED = "CHECKOUT_COMPLETED", "Checkout Completed"
    PAYMENT_FAILED = "PAYMENT_FAILED", "Payment Failed"
    PAYMENT_RECOVERED = "PAYMENT_RECOVERED", "Payment Recovered"
    DUNNING_GRACE = "DUNNING_GRACE", "Dunning Grace"
    DUNNING_SUSPENDED = "DUNNING_SUSPENDED", "Dunning Suspended"
    DUNNING_EXPIRED = "DUNNING_EXPIRED", "Dunning Expired"
    SUBSCRIPTION_CANCELED = "SUBSCRIPTION_CANCELED", "Subscription Canceled"
    SUBSCRIPTION_REACTIVATED = "SUBSCRIPTION_REACTIVATED", "Subscription Reactivated"
    PLAN_CHANGED = "PLAN_CHANGED", "Plan Changed"
    REFERRAL_APPROVED = "REFERRAL_APPROVED", "Referral Approved"
    REFERRAL_REJECTED = "REFERRAL_REJECTED", "Referral Rejected"
    REFERRAL_REDEEMED = "REFERRAL_REDEEMED", "Referral Redeemed"
    RETENTION_OFFER_ACCEPTED = "RETENTION_OFFER_ACCEPTED", "Retention Offer Accepted"
    DOWNGRADE_SCHEDULED = "DOWNGRADE_SCHEDULED", "Downgrade Scheduled"
    DOWNGRADE_CANCELED = "DOWNGRADE_CANCELED", "Downgrade Canceled"
    PLAN_CHANGE_EXECUTED = "PLAN_CHANGE_EXECUTED", "Plan Change Executed"


class ScheduledPlanChangeStatusChoices(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    COMPLETED = "COMPLETED", "Completed"
    CANCELED = "CANCELED", "Canceled"


class ScheduledPlanChangeKindChoices(models.TextChoices):
    UPGRADE = "UPGRADE", "Upgrade"
    DOWNGRADE = "DOWNGRADE", "Downgrade"


class SubscriptionEventSourceChoices(models.TextChoices):
    SYSTEM = "SYSTEM", "System"
    WEBHOOK = "WEBHOOK", "Webhook"
    API = "API", "API"
    ADMIN = "ADMIN", "Admin"


class SubscriptionContractStatusChoices(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    CANCELED = "CANCELED", "Canceled"


class PlanMigrationJobStatusChoices(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class PlanMigrationRecordStatusChoices(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"
