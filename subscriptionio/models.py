from autoslug import AutoSlugField

from django.db import models

from django.utils.timezone import now

from common.choices import CurrencyChoices, DiscountKind
from common.models import BaseModelWithUID

from .choices import (
    SubscriptionPriceBillingFrequencyChoices,
    SubscriptionStatusChoices,
    SubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    CompanySubscriptionKindChoices,
    SubscriptionCanclePolicyStatusChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_subscription_slug,
    get_subscription_price_slug,
    get_company_subscription_slug,
)


class Subscription(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_subscription_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=SubscriptionStatusChoices,
        default=SubscriptionStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50,
        choices=SubscriptionKindChoices,
        default=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
    )
    description = models.TextField()
    currency = models.CharField(
        choices=CurrencyChoices, default=CurrencyChoices.USD, max_length=50
    )
    user_limit = models.PositiveIntegerField()
    employee_limit = models.PositiveIntegerField(default=0)
    storage_limit = models.PositiveIntegerField()
    trial_period = models.PositiveIntegerField()

    # Features
    is_chart_of_account = models.BooleanField(default=False)
    is_chart_of_account_tree = models.BooleanField(default=False)
    is_journal_entry = models.BooleanField(default=False)
    is_bank_transaction = models.BooleanField(default=False)
    is_sales = models.BooleanField(default=False)
    is_customer = models.BooleanField(default=False)
    is_inventory = models.BooleanField(default=False)
    is_warehouse = models.BooleanField(default=False)
    is_expense = models.BooleanField(default=False)
    is_supplier_management = models.BooleanField(default=False)
    is_standard_report = models.BooleanField(default=False)
    is_agency_tax = models.BooleanField(default=False)
    is_employees = models.BooleanField(default=False)
    is_payroll = models.BooleanField(default=False)
    is_attendance = models.BooleanField(default=False)
    is_punch_data_import = models.BooleanField(default=False)
    is_multicurrency = models.BooleanField(default=False)
    is_company_setting = models.BooleanField(default=False)
    is_audit_log = models.BooleanField(default=False)
    is_attachment = models.BooleanField(default=False)
    is_user_role_management = models.BooleanField(default=False)
    is_terms = models.BooleanField(default=False)
    is_payment_management = models.BooleanField(default=False)
    is_configuration = models.BooleanField(default=False)
    is_user_profile = models.BooleanField(default=False)
    is_support_ticket = models.BooleanField(default=False)
    is_ai_finzify = models.BooleanField(default=False)

    is_auto_renew = models.BooleanField(default=False)
    is_enable_email_notification = models.BooleanField(default=False)
    cancel_policy = models.CharField(
        max_length=50,
        choices=SubscriptionCanclePolicyStatusChoices,
        default=SubscriptionCanclePolicyStatusChoices.ANYTIME,
    )

    # Accountant related
    is_monthly_bookkeeping_and_reconciliations = models.BooleanField(default=False)
    is_reports = models.BooleanField(default=False)
    is_annual_tax_filing = models.BooleanField(default=False)
    is_1099_preparation_filing = models.BooleanField(default=False)
    is_30_minute_consultation_per_quarter = models.BooleanField(default=False)
    is_monthly_or_biweekly_payroll_processing = models.BooleanField(default=False)
    is_quarterly_tax_planning_reviews = models.BooleanField(default=False)
    is_budgeting_and_cash_flow_forecasting = models.BooleanField(default=False)
    is_sales_tax_filing = models.BooleanField(default=False)
    is_unlimited_email_support = models.BooleanField(default=False)
    is_dedicated_accountant = models.BooleanField(default=False)
    is_Virtual_CFO_services = models.BooleanField(default=False)
    is_financial_modeling_and_custom_dashboards = models.BooleanField(default=False)
    is_investo_ready_financial_statements = models.BooleanField(default=False)
    is_audit_support_and_representation = models.BooleanField(default=False)
    is_year_end_planning_for_tax_minimization = models.BooleanField(default=False)
    is_multi_entity_or_multi_state_handling = models.BooleanField(default=False)
    is_priority_support = models.BooleanField(default=False)

    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"


class SubscriptionPrice(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_subscription_price_slug, unique=True, db_index=True
    )
    billing_frequency = models.CharField(
        choices=SubscriptionPriceBillingFrequencyChoices,
        default=SubscriptionPriceBillingFrequencyChoices.YEARLY,
        max_length=50,
    )
    price = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    discount = models.DecimalField(
        default=0.00, max_digits=19, decimal_places=3, null=True, blank=True
    )
    discount_kind = models.CharField(
        choices=DiscountKind, default=DiscountKind.FLAT, max_length=50
    )
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)
    currency = models.CharField(
        choices=CurrencyChoices,
        default=CurrencyChoices.USD,
        max_length=50,
    )
    is_active = models.BooleanField(default=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("subscription", "billing_frequency", "currency")
    

    def __str__(self):
        return f"ID: {self.id}, Subscription: {self.subscription.title}, Subscription kind: {self.subscription.kind}, Price: {self.price}, Billing Frequently: {self.billing_frequency}"


class CompanySubscription(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_company_subscription_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=50,
        choices=CompanySubscriptionStatusChoices,
        default=CompanySubscriptionStatusChoices.DRAFT,
    )
    kind = models.CharField(
        max_length=50,
        choices=CompanySubscriptionKindChoices,
        default=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
    )
    start_date = models.DateTimeField(default=now)
    renew_date = models.DateTimeField(blank=True, null=True)
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    trial_start = models.DateTimeField(blank=True, null=True)
    trial_end = models.DateTimeField(blank=True, null=True)
    dunning_started_at = models.DateTimeField(blank=True, null=True)
    grace_ends_at = models.DateTimeField(blank=True, null=True)
    suspend_ends_at = models.DateTimeField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)
    failed_payment_count = models.PositiveIntegerField(default=0)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)

    # FK
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, blank=True, null=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    subscription_price = models.ForeignKey(SubscriptionPrice, on_delete=models.CASCADE)
    plan_version = models.ForeignKey(
        "subscriptionio.PlanVersion",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="company_subscriptions",
    )
    applied_coupon = models.ForeignKey(
        "subscriptionio.SubscriptionCoupon",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="company_subscriptions",
    )

    def __str__(self):
        return f"ID: {self.id}, "


from .billing_models import (  # noqa: E402, F401
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
)
from .enforcement_models import UsageCounter  # noqa: E402, F401
from .entitlement_models import (  # noqa: E402, F401
    PlanFeature,
    PlanLimit,
    PlanVersion,
    SubscriptionFeature,
    SubscriptionModule,
)
from .enterprise_models import (  # noqa: E402, F401
    PlanMigrationJob,
    PlanMigrationRecord,
    SubscriptionContract,
)
from .lifecycle_models import ScheduledPlanChange, SubscriptionEvent  # noqa: E402, F401
from .metric_models import SubscriptionBillableMetric  # noqa: E402, F401
from .addon_models import CompanyAddOn, PlanAddOn, SubscriptionAddOn  # noqa: E402, F401
from .promotion_models import (  # noqa: E402, F401
    CouponRedemption,
    ReferralCode,
    ReferralRedemption,
    SubscriptionCoupon,
    SubscriptionCredit,
    SubscriptionOffer,
    SubscriptionProgramSettings,
)
