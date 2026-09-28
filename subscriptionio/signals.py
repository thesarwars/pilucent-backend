from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.models import CompanySubscription, PlanFeature, PlanLimit, PlanVersion


def _invalidate_for_subscription(subscription_id):
    from subscriptionio.models import CompanySubscription

    company_ids = CompanySubscription.objects.filter(
        subscription_price__subscription_id=subscription_id
    ).values_list("company_id", flat=True)
    for company_id in company_ids:
        invalidate_entitlement_cache(company_id)


@receiver(post_save, sender=CompanySubscription)
@receiver(post_delete, sender=CompanySubscription)
def invalidate_on_company_subscription_change(sender, instance, **kwargs):
    invalidate_entitlement_cache(instance.company_id)


@receiver(post_save, sender=PlanVersion)
@receiver(post_delete, sender=PlanVersion)
def invalidate_on_plan_version_change(sender, instance, **kwargs):
    _invalidate_for_subscription(instance.subscription_id)


@receiver(post_save, sender=PlanFeature)
@receiver(post_delete, sender=PlanFeature)
def invalidate_on_plan_feature_change(sender, instance, **kwargs):
    _invalidate_for_subscription(instance.plan_version.subscription_id)


@receiver(post_save, sender=PlanLimit)
@receiver(post_delete, sender=PlanLimit)
def invalidate_on_plan_limit_change(sender, instance, **kwargs):
    _invalidate_for_subscription(instance.plan_version.subscription_id)
