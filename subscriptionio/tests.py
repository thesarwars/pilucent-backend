from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now

from subscriptionio.choices import (
    CompanySubscriptionKindChoices,
    CompanySubscriptionStatusChoices,
    LimitMetricChoices,
    PlanVersionStatusChoices,
    SubscriptionKindChoices,
    SubscriptionPriceBillingFrequencyChoices,
    SubscriptionStatusChoices,
)
from subscriptionio.models import (
    CompanySubscription,
    PlanFeature,
    PlanLimit,
    PlanVersion,
    Subscription,
    SubscriptionFeature,
    SubscriptionModule,
    SubscriptionPrice,
)
from subscriptionio.services.billing_preview_service import BillingPreviewService
from subscriptionio.services.entitlement_service import EntitlementService
from subscriptionio.services.plan_version_service import PlanVersionService
from common.choices import DiscountKind
from subscriptionio.choices import CouponStatusChoices, SubscriptionContractStatusChoices
from subscriptionio.models import SubscriptionCoupon
from subscriptionio.services.coupon_service import CouponService
from subscriptionio.services.limit_enforcement_service import LimitEnforcementService
from subscriptionio.services.plan_change_guard_service import PlanChangeGuardService
from subscriptionio.services.referral_service import ReferralService
from subscriptionio.services.stripe_checkout_service import StripeCheckoutService
from subscriptionio.models import SubscriptionContract, SubscriptionEvent
from subscriptionio.services.enterprise_pricing_service import EnterprisePricingService
from subscriptionio.services.plan_migration_service import PlanMigrationService
from subscriptionio.services.dunning_service import DunningService
from subscriptionio.services.lifecycle_service import LifecycleService
from subscriptionio.services.trial_service import TrialService

from companyio.models import Company


class EntitlementServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Co", title="Test Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=14,
            is_sales=True,
            is_employees=False,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=150,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )
        self.sales_module = SubscriptionModule.objects.create(
            code="sales",
            title="Sales",
        )
        self.sales_feature = SubscriptionFeature.objects.create(
            module=self.sales_module,
            code="sales",
            title="Sales",
            legacy_field="is_sales",
            permission_codenames=["view_sale"],
        )

    def test_legacy_feature_allowed_when_subscription_flag_enabled(self):
        result = EntitlementService.check_feature(self.company, "is_sales")
        self.assertTrue(result.allowed)

    def test_legacy_feature_denied_when_subscription_flag_disabled(self):
        result = EntitlementService.check_feature(self.company, "is_employees")
        self.assertFalse(result.allowed)
        self.assertEqual(result.denied_by, "subscription")

    def test_plan_version_overrides_legacy_flags(self):
        plan_version = PlanVersion.objects.create(
            subscription=self.subscription,
            version_no=1,
            status=PlanVersionStatusChoices.PUBLISHED,
            title="Starter v1",
        )
        PlanFeature.objects.create(
            plan_version=plan_version,
            feature=self.sales_feature,
            is_enabled=False,
        )
        self.company_subscription.plan_version = plan_version
        self.company_subscription.save()

        result = EntitlementService.check_feature(self.company, "is_sales")
        self.assertFalse(result.allowed)

    def test_expired_subscription_is_denied(self):
        self.company_subscription.start_date = now() - timedelta(days=60)
        self.company_subscription.save()

        result = EntitlementService.check_feature(self.company, "is_sales")
        self.assertFalse(result.allowed)
        self.company_subscription.refresh_from_db()
        self.assertEqual(
            self.company_subscription.status,
            CompanySubscriptionStatusChoices.PENDING,
        )

    def test_trialing_status_is_operational(self):
        self.company_subscription.status = CompanySubscriptionStatusChoices.TRIALING
        self.company_subscription.save()

        result = EntitlementService.check_feature(self.company, "is_sales")
        self.assertTrue(result.allowed)

    def test_plan_version_service_publish_archives_previous(self):
        first = PlanVersionService.create_draft_version(self.subscription)
        PlanVersionService.publish(first)
        second = PlanVersionService.create_draft_version(self.subscription)
        PlanVersionService.publish(second)

        first.refresh_from_db()
        self.assertEqual(first.status, PlanVersionStatusChoices.ARCHIVED)
        self.assertEqual(second.status, PlanVersionStatusChoices.PUBLISHED)


class BillingPreviewServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Billing Co", title="Billing Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=14,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            stripe_price_id="price_base_test",
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )
        plan_version = PlanVersionService.ensure_initial_version(self.subscription)
        PlanLimit.objects.filter(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.EMPLOYEE,
        ).update(included_quantity=2, overage_unit_price=6)

    def test_preview_base_amount_without_overage(self):
        preview = BillingPreviewService.preview(
            self.company,
            subscription_price=self.subscription_price,
            employee_count=2,
        )
        self.assertIsNotNone(preview)
        self.assertEqual(preview.subtotal, Decimal("180"))
        self.assertEqual(preview.overage_total, Decimal("0"))
        self.assertEqual(preview.total, Decimal("180"))

    def test_preview_includes_employee_overage(self):
        preview = BillingPreviewService.preview(
            self.company,
            subscription_price=self.subscription_price,
            employee_count=5,
        )
        self.assertEqual(preview.overage_total, Decimal("18"))
        self.assertEqual(preview.total, Decimal("198"))

    def test_period_expiry_uses_current_period_end(self):
        self.company_subscription.current_period_end = now() - timedelta(days=1)
        self.company_subscription.save()
        result = EntitlementService.check_feature(self.company, "is_sales")
        self.assertFalse(result.allowed)

    def test_checkout_line_items_include_dynamic_employee_overage(self):
        preview = BillingPreviewService.preview(
            self.company,
            subscription_price=self.subscription_price,
            employee_count=5,
        )
        plan_version = PlanVersionService.ensure_initial_version(self.subscription)
        line_items = StripeCheckoutService.build_stripe_line_items(
            preview=preview,
            subscription_price=self.subscription_price,
            plan_version=plan_version,
        )
        self.assertEqual(len(line_items), 2)
        self.assertEqual(line_items[0]["price"], "price_base_test")
        self.assertEqual(line_items[1]["quantity"], 3)
        self.assertEqual(line_items[1]["price_data"]["unit_amount"], 600)

    def test_checkout_line_items_use_configured_stripe_overage_price(self):
        preview = BillingPreviewService.preview(
            self.company,
            subscription_price=self.subscription_price,
            employee_count=5,
        )
        plan_version = PlanVersionService.ensure_initial_version(self.subscription)
        PlanLimit.objects.filter(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.EMPLOYEE,
        ).update(stripe_overage_price_id="price_employee_overage")
        line_items = StripeCheckoutService.build_stripe_line_items(
            preview=preview,
            subscription_price=self.subscription_price,
            plan_version=plan_version,
        )
        self.assertEqual(line_items[1]["price"], "price_employee_overage")
        self.assertEqual(line_items[1]["quantity"], 3)


class LimitEnforcementServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Limit Co", title="Limit Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=2,
            employee_limit=2,
            storage_limit=5,
            trial_period=14,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )
        plan_version = PlanVersionService.ensure_initial_version(self.subscription)
        PlanLimit.objects.filter(
            plan_version=plan_version,
            metric_code=LimitMetricChoices.EMPLOYEE,
        ).update(
            included_quantity=2,
            enforcement_mode="HARD_BLOCK",
        )

    def test_hard_block_denies_employee_create(self):
        from employeeio.models import Employee
        from accounts.models import User

        user = User.objects.create(email="e1@test.com", name="E1")
        Employee.objects.create(user=user, company=self.company, status="ACTIVE")
        user2 = User.objects.create(email="e2@test.com", name="E2")
        Employee.objects.create(user=user2, company=self.company, status="ACTIVE")

        result = LimitEnforcementService.check_create_allowed(
            self.company, LimitMetricChoices.EMPLOYEE
        )
        self.assertFalse(result.allowed)

    def test_plan_change_guard_blocks_downgrade(self):
        small_plan = Subscription.objects.create(
            title="Micro",
            description="Micro",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=1,
            employee_limit=1,
            storage_limit=1,
            trial_period=0,
        )
        small_price = SubscriptionPrice.objects.create(
            subscription=small_plan,
            price=50,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        PlanVersionService.ensure_initial_version(small_plan)

        guard = PlanChangeGuardService.validate_plan_change(
            self.company,
            subscription_price=small_price,
        )
        self.assertFalse(guard.allowed)
        self.assertTrue(guard.blockers)


class CouponServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Coupon Co", title="Coupon Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=14,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=Decimal("180"),
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.coupon = SubscriptionCoupon.objects.create(
            code="SAVE20",
            status=CouponStatusChoices.ACTIVE,
            discount_kind=DiscountKind.PERCENTAGE,
            discount_value=Decimal("20"),
        )

    def test_valid_coupon_returns_discount(self):
        result = CouponService.validate(
            "save20",
            company=self.company,
            subscription_price=self.subscription_price,
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.discount_amount, Decimal("36"))

    def test_non_stackable_coupon_rejects_plan_discount(self):
        self.subscription_price.discount = Decimal("10")
        self.subscription_price.save()
        result = CouponService.validate(
            "SAVE20",
            company=self.company,
            subscription_price=self.subscription_price,
        )
        self.assertFalse(result.valid)


class TrialServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Trial Co", title="Trial Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=14,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )

    def test_start_trial_activates_trialing_status(self):
        result = TrialService.start_trial(
            self.company,
            subscription_price=self.subscription_price,
        )
        self.assertTrue(result.active)
        self.assertEqual(result.status, CompanySubscriptionStatusChoices.TRIALING)
        self.assertIsNotNone(result.trial_end)

    def test_second_trial_is_rejected(self):
        TrialService.start_trial(self.company, subscription_price=self.subscription_price)
        result = TrialService.start_trial(
            self.company,
            subscription_price=self.subscription_price,
        )
        self.assertFalse(result.active)
        self.assertIn("already", result.message.lower())


class ReferralServiceTests(TestCase):
    def setUp(self):
        self.referrer = Company.objects.create(name="Referrer", title="Referrer")
        self.referee = Company.objects.create(name="Referee", title="Referee")

    def test_self_referral_is_blocked(self):
        referral = ReferralService.get_or_create_company_code(self.referrer)
        result = ReferralService.validate(referral.code, company=self.referrer)
        self.assertFalse(result.valid)

    def test_valid_referral_redeem_creates_credit(self):
        referral = ReferralService.get_or_create_company_code(self.referrer)
        result = ReferralService.validate(referral.code, company=self.referee)
        self.assertTrue(result.valid)
        redemption = ReferralService.redeem(referral, referred_company=self.referee)
        self.assertIsNotNone(redemption.reward_credit)
        self.assertEqual(redemption.reward_credit.balance, ReferralService.DEFAULT_REWARD_AMOUNT)


class DunningServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Dunning Co", title="Dunning Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )

    def test_payment_failure_moves_to_past_due(self):
        DunningService.record_payment_failure(self.company_subscription)
        self.company_subscription.refresh_from_db()
        self.assertEqual(
            self.company_subscription.status,
            CompanySubscriptionStatusChoices.PAST_DUE,
        )
        self.assertEqual(self.company_subscription.failed_payment_count, 1)

    def test_payment_recovery_clears_dunning(self):
        DunningService.record_payment_failure(self.company_subscription)
        DunningService.record_payment_recovery(self.company_subscription)
        self.company_subscription.refresh_from_db()
        self.assertEqual(
            self.company_subscription.status,
            CompanySubscriptionStatusChoices.ACTIVE,
        )
        self.assertEqual(self.company_subscription.failed_payment_count, 0)


class LifecycleServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Lifecycle Co", title="Lifecycle Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )

    def test_cancel_without_stripe_sets_canceled(self):
        result = LifecycleService.cancel_subscription(
            self.company,
            at_period_end=False,
        )
        self.assertTrue(result.success)
        self.company_subscription.refresh_from_db()
        self.assertEqual(
            self.company_subscription.status,
            CompanySubscriptionStatusChoices.CANCELED,
        )
        self.assertTrue(
            SubscriptionEvent.objects.filter(
                company=self.company,
                event_type="SUBSCRIPTION_CANCELED",
            ).exists()
        )


class EnterprisePricingServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Enterprise Co", title="Enterprise Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            currency="USD",
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=Decimal("180"),
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            currency="USD",
        )
        self.eur_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=Decimal("160"),
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            currency="EUR",
        )

    def test_resolve_price_by_currency(self):
        resolved = EnterprisePricingService.resolve_pricing(
            self.company,
            plan_title="Starter",
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            currency="EUR",
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.currency, "EUR")
        self.assertEqual(resolved.base_price, Decimal("160"))

    def test_contract_overrides_price(self):
        SubscriptionContract.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            currency="USD",
            custom_price=Decimal("99"),
            contract_start=now(),
            status=SubscriptionContractStatusChoices.ACTIVE,
        )
        resolved = EnterprisePricingService.resolve_pricing(
            self.company,
            subscription_price=self.subscription_price,
        )
        self.assertTrue(resolved.contract_applied)
        self.assertEqual(resolved.base_price, Decimal("99"))


class PlanMigrationServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Migrate Co", title="Migrate Co")
        self.source_plan = Subscription.objects.create(
            title="Legacy",
            description="Legacy",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=5,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.target_plan = Subscription.objects.create(
            title="Modern",
            description="Modern",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=5,
            storage_limit=10,
            trial_period=0,
            is_sales=True,
        )
        self.source_price = SubscriptionPrice.objects.create(
            subscription=self.source_plan,
            price=100,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            currency="USD",
        )
        self.target_price = SubscriptionPrice.objects.create(
            subscription=self.target_plan,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
            currency="USD",
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.source_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )
        PlanVersionService.ensure_initial_version(self.source_plan)
        PlanVersionService.ensure_initial_version(self.target_plan)

    def test_dry_run_migration_preview_and_execute(self):
        from subscriptionio.models import PlanMigrationJob

        job = PlanMigrationJob.objects.create(
            source_subscription=self.source_plan,
            target_subscription=self.target_plan,
            dry_run=True,
        )
        preview = PlanMigrationService.preview_job(job)
        self.assertEqual(preview["eligible_companies"], 1)
        job = PlanMigrationService.execute_job(job)
        self.assertEqual(job.migrated_count, 1)
        self.company_subscription.refresh_from_db()
        self.assertEqual(
            self.company_subscription.subscription_price.subscription.title,
            "Legacy",
        )


class CreditServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Credit Co", title="Credit Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )

    def test_billing_preview_applies_account_credit(self):
        from subscriptionio.choices import SubscriptionCreditSourceChoices
        from subscriptionio.models import SubscriptionCredit
        from subscriptionio.services.credit_service import CreditService

        SubscriptionCredit.objects.create(
            company=self.company,
            initial_amount=Decimal("50"),
            balance=Decimal("50"),
            source=SubscriptionCreditSourceChoices.ADMIN_ADJUSTMENT,
        )
        preview = BillingPreviewService.preview(
            self.company,
            subscription_price=self.subscription_price,
        )
        self.assertEqual(preview.credit_total, Decimal("50"))
        self.assertEqual(preview.total, Decimal("130"))
        self.assertTrue(any(line.line_type == "CREDIT" for line in preview.lines))

    def test_apply_credits_deducts_fifo(self):
        from subscriptionio.choices import SubscriptionCreditSourceChoices
        from subscriptionio.models import SubscriptionCredit
        from subscriptionio.services.credit_service import CreditService

        first = SubscriptionCredit.objects.create(
            company=self.company,
            initial_amount=Decimal("30"),
            balance=Decimal("30"),
            source=SubscriptionCreditSourceChoices.REFERRAL,
        )
        second = SubscriptionCredit.objects.create(
            company=self.company,
            initial_amount=Decimal("40"),
            balance=Decimal("40"),
            source=SubscriptionCreditSourceChoices.PROMOTION,
        )
        applied = CreditService.apply_credits(self.company, Decimal("50"))
        self.assertEqual(applied, Decimal("50"))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.balance, Decimal("0"))
        self.assertFalse(first.is_active)
        self.assertEqual(second.balance, Decimal("20"))


class ProgramSettingsEnforcementTests(TestCase):
    def setUp(self):
        self.referrer = Company.objects.create(
            name="Referrer",
            title="Referrer",
            email="ref@example.com",
        )
        self.referee = Company.objects.create(
            name="Referee",
            title="Referee",
            email="new@example.com",
        )
        self.domain_company = Company.objects.create(
            name="Other",
            title="Other",
            email="boss@example.com",
        )
        self.trial_company = Company.objects.create(
            name="Trial Co",
            title="Trial Co",
            email="trial@example.com",
        )
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        from subscriptionio.models import SubscriptionProgramSettings

        self.settings = SubscriptionProgramSettings.get_solo()
        self.settings.trial_default_days = 14
        self.settings.trial_one_per_domain = True
        self.settings.referral_program_active = True
        self.settings.save()

    def test_referral_program_inactive_blocks_validation(self):
        self.settings.referral_program_active = False
        self.settings.save(update_fields=["referral_program_active", "updated_at"])
        referral = ReferralService.get_or_create_company_code(self.referrer)
        result = ReferralService.validate(referral.code, company=self.referee)
        self.assertFalse(result.valid)

    def test_trial_uses_default_days_when_plan_has_none(self):
        result = TrialService.start_trial(
            self.trial_company,
            subscription_price=self.subscription_price,
        )
        self.assertTrue(result.active)
        self.assertEqual(result.days_remaining, 14)

    def test_domain_trial_limit_blocks_second_company(self):
        CompanySubscription.objects.create(
            company=self.domain_company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.TRIALING,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            trial_start=now(),
            trial_end=now() + timedelta(days=7),
        )
        blocked = Company.objects.create(
            name="Blocked",
            title="Blocked",
            email="user@example.com",
        )
        result = TrialService.start_trial(
            blocked,
            subscription_price=self.subscription_price,
        )
        self.assertFalse(result.active)
        self.assertIn("domain", result.message.lower())


class OfferServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Offer Co", title="Offer Co")
        self.subscription = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=2,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.subscription_price = SubscriptionPrice.objects.create(
            subscription=self.subscription,
            price=180,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.subscription_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now(),
        )
        from subscriptionio.models import SubscriptionCoupon, SubscriptionOffer
        from subscriptionio.choices import OfferStatusChoices

        self.coupon = SubscriptionCoupon.objects.create(
            code="OFFER20",
            status=CouponStatusChoices.ACTIVE,
            discount_kind=DiscountKind.PERCENTAGE,
            discount_value=20,
        )
        self.offer = SubscriptionOffer.objects.create(
            code="WELCOME20",
            title="Welcome Offer",
            description="20% off",
            status=OfferStatusChoices.ACTIVE,
            coupon=self.coupon,
            is_retention_offer=False,
        )
        self.retention_coupon = SubscriptionCoupon.objects.create(
            code="STAY15",
            status=CouponStatusChoices.ACTIVE,
            discount_kind=DiscountKind.PERCENTAGE,
            discount_value=15,
        )
        self.retention_offer = SubscriptionOffer.objects.create(
            code="STAYWITHUS",
            title="Stay With Us",
            description="Retention discount",
            status=OfferStatusChoices.ACTIVE,
            coupon=self.retention_coupon,
            is_retention_offer=True,
        )

    def test_validate_public_offer_returns_coupon(self):
        from subscriptionio.services.offer_service import OfferService

        result = OfferService.validate("WELCOME20", company=self.company)
        self.assertTrue(result.valid)
        self.assertEqual(result.coupon_code, "OFFER20")

    def test_retention_offer_requires_retention_context(self):
        from subscriptionio.services.offer_service import OfferService

        result = OfferService.validate("STAYWITHUS", company=self.company)
        self.assertFalse(result.valid)

        retention = OfferService.validate(
            "STAYWITHUS",
            company=self.company,
            retention_context=True,
        )
        self.assertTrue(retention.valid)

    def test_accept_retention_offer_clears_cancel_flag(self):
        from subscriptionio.services.offer_service import OfferService

        self.company_subscription.cancel_at_period_end = True
        self.company_subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
        offer = OfferService.accept_retention_offer(self.company, "STAYWITHUS")
        self.company_subscription.refresh_from_db()
        self.assertFalse(self.company_subscription.cancel_at_period_end)
        self.assertEqual(self.company_subscription.applied_coupon_id, self.retention_coupon.id)
        self.assertEqual(offer["code"], "STAYWITHUS")


class ReferralDashboardTests(TestCase):
    def test_referral_dashboard_includes_redemptions_and_credits(self):
        referrer = Company.objects.create(name="Dash Referrer", title="Dash Referrer")
        referee = Company.objects.create(name="Dash Referee", title="Dash Referee")
        referral = ReferralService.get_or_create_company_code(referrer)
        ReferralService.redeem(referral, referred_company=referee)
        dashboard = ReferralService.get_referral_dashboard(referrer)
        self.assertEqual(dashboard["code"], referral.code)
        self.assertEqual(dashboard["summary"]["approved_count"], 1)
        self.assertEqual(len(dashboard["redemptions"]), 1)
        self.assertEqual(len(dashboard["credits"]), 1)


class PlanChangeServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Change Co", title="Change Co")
        self.starter = Subscription.objects.create(
            title="Starter",
            description="Starter plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=10,
            employee_limit=25,
            storage_limit=5,
            trial_period=0,
            is_sales=True,
        )
        self.growth = Subscription.objects.create(
            title="Growth",
            description="Growth plan",
            status=SubscriptionStatusChoices.PUBLISHED,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            user_limit=25,
            employee_limit=100,
            storage_limit=10,
            trial_period=0,
            is_sales=True,
        )
        self.starter_price = SubscriptionPrice.objects.create(
            subscription=self.starter,
            price=150,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        self.growth_price = SubscriptionPrice.objects.create(
            subscription=self.growth,
            price=250,
            billing_frequency=SubscriptionPriceBillingFrequencyChoices.MONTHLY,
        )
        period_end = now() + timedelta(days=20)
        self.company_subscription = CompanySubscription.objects.create(
            company=self.company,
            subscription_price=self.growth_price,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION,
            start_date=now() - timedelta(days=10),
            current_period_start=now() - timedelta(days=10),
            current_period_end=period_end,
            renew_date=period_end,
        )

    def test_preview_downgrade_includes_proration(self):
        from subscriptionio.services.plan_change_service import PlanChangeService

        preview = PlanChangeService.preview_plan_change(
            self.company,
            subscription_price=self.starter_price,
        )
        self.assertTrue(preview["is_downgrade"])
        self.assertLess(Decimal(preview["proration"]["proration_amount"]), Decimal("0"))

    def test_schedule_downgrade_creates_record(self):
        from subscriptionio.models import ScheduledPlanChange
        from subscriptionio.services.plan_change_service import PlanChangeService

        result = PlanChangeService.schedule_downgrade(
            self.company,
            subscription_price=self.starter_price,
        )
        self.assertEqual(result["target_plan"]["title"], "Starter")
        self.assertTrue(
            ScheduledPlanChange.objects.filter(
                company=self.company,
                status="SCHEDULED",
            ).exists()
        )
