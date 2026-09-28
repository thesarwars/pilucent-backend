from dateutil.relativedelta import relativedelta

from django.utils.timezone import now

from rest_framework import permissions

from paymentio.choices import PaymentInformationKindChoices

from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    SubscriptionKindChoices,
    SubscriptionStatusChoices,
)
from subscriptionio.models import CompanySubscription

from ...helpers.payment_helpers import get_subscription_period


class HaveSubscriptionV1(permissions.IsAuthenticated):
    """Legacy subscription gate using plan boolean flags on Subscription."""

    message = (
        "Access denied! It seems like your subscription is inactive. "
        "Please activate your subscription to unlock this feature."
    )

    def _has_subscription(self, request, view):
        user = request.user
        company = user.get_active_company() if not user.is_anonymous else False
        company_subscription = CompanySubscription.objects.filter(
            company=company,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=SubscriptionKindChoices.COMPANY_SUBSCRIPTION,
        ).first()

        if not company_subscription:
            return False

        start_date = company_subscription.start_date
        subscription_price = company_subscription.subscription_price

        if now() > start_date + relativedelta(
            months=get_subscription_period(subscription_price.billing_frequency)
        ):
            company_subscription.status = CompanySubscriptionStatusChoices.PENDING
            company_subscription.save()

            company_subscription.subscription_price.subscription.paymentinformation_set.filter(
                is_subscription_completed=False,
                kind=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
            ).update(is_subscription_completed=True)

            return False

        return getattr(
            (
                subscription_price.subscription
                if subscription_price.subscription.status
                == SubscriptionStatusChoices.PUBLISHED
                else None
            ),
            view.required_feature,
            False,
        )

    def has_permission(self, request, view):
        return self._has_subscription(request, view)

    def has_object_permission(self, request, view, obj):
        return self._has_subscription(request, view)
