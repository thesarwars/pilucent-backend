from auditlog.registry import auditlog

from django.contrib import admin

from .billing_models import SubscriptionInvoice, SubscriptionInvoiceLine
from .enterprise_models import PlanMigrationJob, PlanMigrationRecord, SubscriptionContract
from .lifecycle_models import SubscriptionEvent
from .enforcement_models import UsageCounter
from .entitlement_models import (
    PlanFeature,
    PlanLimit,
    PlanVersion,
    SubscriptionFeature,
    SubscriptionModule,
)
from .models import Subscription, SubscriptionPrice, CompanySubscription
from .promotion_models import (
    CouponRedemption,
    ReferralCode,
    SubscriptionCoupon,
    SubscriptionCredit,
    SubscriptionOffer,
)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["uid", "title", "status", "kind", "created_at"]
    search_fields = list_display
    list_filter = ["status"]


@admin.register(SubscriptionPrice)
class SubscriptionPriceAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "subscription",
        "billing_frequency",
        "currency",
        "price",
        "discount",
        "is_active",
        "created_at",
    ]
    # `search_fields` is not `list_display`. A display column may be a relation
    # rendered through __str__, or an admin method -- neither of which is an ORM
    # path, and a search term is applied with `icontains`, so reusing the list
    # made every search on this changelist a FieldError.
    search_fields = [
        "uid",
        "subscription__title",
        "billing_frequency",
        "currency",
        "stripe_price_id",
    ]
    list_filter = ["billing_frequency", "discount_kind", "currency", "is_active"]


@admin.register(CompanySubscription)
class CompanySubscriptionAdmin(admin.ModelAdmin):
    
    list_display = ["uid", "subscription", "start_date", "status", "created_at", "company"]
    # `search_fields` is not `list_display`. A display column may be a relation
    # rendered through __str__, or an admin method -- neither of which is an ORM
    # path, and a search term is applied with `icontains`, so reusing the list
    # made every search on this changelist a FieldError.
    #
    # Here `subscription` is an admin METHOD (defined below), which is the
    # sharper version of the same mistake: it renders fine in a column and
    # cannot be queried at all.
    search_fields = [
        "uid",
        "status",
        "company__name",
        "subscription_price__subscription__title",
        "stripe_subscription_id",
    ]
    list_filter = ["status", "start_date"]
    
    def subscription(self, obj):
        return obj.subscription_price.subscription.title


@admin.register(SubscriptionModule)
class SubscriptionModuleAdmin(admin.ModelAdmin):
    list_display = ["uid", "code", "title", "display_order", "is_active"]
    search_fields = ["code", "title"]


@admin.register(SubscriptionFeature)
class SubscriptionFeatureAdmin(admin.ModelAdmin):
    list_display = ["uid", "code", "module", "legacy_field", "is_active"]
    search_fields = ["code", "legacy_field"]
    list_filter = ["module"]


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 0


class PlanLimitInline(admin.TabularInline):
    model = PlanLimit
    extra = 0
    fields = [
        "metric_code",
        "included_quantity",
        "overage_unit_price",
        "stripe_overage_price_id",
        "enforcement_mode",
    ]


@admin.register(PlanVersion)
class PlanVersionAdmin(admin.ModelAdmin):
    list_display = ["uid", "subscription", "version_no", "status", "published_at"]
    list_filter = ["status"]
    inlines = [PlanFeatureInline, PlanLimitInline]


auditlog.register(Subscription)
auditlog.register(SubscriptionPrice)
auditlog.register(CompanySubscription)
auditlog.register(PlanVersion)


class SubscriptionInvoiceLineInline(admin.TabularInline):
    model = SubscriptionInvoiceLine
    extra = 0


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = ["uid", "company", "metric_code", "quantity", "source", "updated_at"]
    list_filter = ["metric_code", "source"]


@admin.register(SubscriptionContract)
class SubscriptionContractAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "status",
        "currency",
        "custom_price",
        "is_manual_billing",
        "contract_start",
        "contract_end",
    ]
    list_filter = ["status", "is_manual_billing", "currency"]


@admin.register(PlanMigrationJob)
class PlanMigrationJobAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "source_subscription",
        "target_subscription",
        "status",
        "dry_run",
        "migrated_count",
        "failed_count",
    ]
    list_filter = ["status", "dry_run"]


@admin.register(PlanMigrationRecord)
class PlanMigrationRecordAdmin(admin.ModelAdmin):
    list_display = ["uid", "job", "company", "status", "created_at"]
    list_filter = ["status"]


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "event_type",
        "previous_status",
        "new_status",
        "source",
        "created_at",
    ]
    list_filter = ["event_type", "source"]
    search_fields = ["company__name", "event_type"]


@admin.register(SubscriptionCoupon)
class SubscriptionCouponAdmin(admin.ModelAdmin):
    list_display = ["uid", "code", "status", "discount_kind", "discount_value", "redemption_count"]
    search_fields = ["code"]


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ["uid", "coupon", "company", "discount_amount", "created_at"]


@admin.register(SubscriptionOffer)
class SubscriptionOfferAdmin(admin.ModelAdmin):
    list_display = ["uid", "code", "title", "status", "is_retention_offer"]


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = ["uid", "code", "company", "total_redemptions", "is_active"]


@admin.register(SubscriptionCredit)
class SubscriptionCreditAdmin(admin.ModelAdmin):
    list_display = ["uid", "company", "balance", "source", "is_active"]


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "company",
        "status",
        "total",
        "currency",
        "stripe_invoice_id",
        "is_manual",
        "created_at",
    ]
    list_filter = ["status", "currency", "is_manual"]
    inlines = [SubscriptionInvoiceLineInline]
