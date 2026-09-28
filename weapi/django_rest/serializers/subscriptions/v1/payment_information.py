from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    ValidationError,
)

from django.db import transaction
from django.utils.timezone import now

from accounts.django_rest.serializers.common import PriateUserSlimSerializer

from common.django_rest.helpers.payment_helpers import (
    complete_stripe_payment,
    get_stripe_payment,
)
from common.django_rest.helpers.decorators import set_auditlog_actor

from paymentio.choices import (
    PaymentInformationStatusChoices,
    PaymentInformationKindChoices,
)
from paymentio.django_rest.serializers.common import PrivatePaymentMethodSlimSerializer
from paymentio.models import PaymentInformation

from subscriptionio.choices import CompanySubscriptionStatusChoices
from subscriptionio.models import SubscriptionPrice, CompanySubscription

from publicapi.django_rest.serializers.subscription_plan import (
    PublicSubscriptionListSerializer,
    PublicSubscriptionPriceListSerializer,
)


class PrivateWeSubscriptionPaymentInformationListSerializer(ModelSerializer):
    subscription_price_slug = SlugRelatedField(
        slug_field="slug",
        queryset=SubscriptionPrice.objects.all(),
        required=False,
    )

    class Meta:
        model = PaymentInformation
        fields = [
            "uid",
            "amount",
            "currency",
            "status",
            "kind",
            "subscription_price_slug",
            "payment_intent_id",
            "client_secret",
            'is_subscription_completed',
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "amount",
            "status",
            "kind",
            "company",
            "currency",
            "payment_by",
            "payment_intent_id",
            "client_secret",
            "is_subscription_completed",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        from weapi.django_rest.helpers.billing import resolve_billing_company

        company = resolve_billing_company(self.context["request"])
        subscription_price = validated_data.pop("subscription_price_slug", None)
        subscription_kind = subscription_price.subscription.kind
        if not subscription_price:
            raise ValidationError({"message": "Subscription price is required!"})

        if CompanySubscription.objects.filter(
            company=company,
            status=CompanySubscriptionStatusChoices.ACTIVE,
            kind=subscription_kind,
        ).exists():
            raise ValidationError(
                {"message": "You already have an active subscription!"}
            )
        validated_data["subscription_price"] = subscription_price
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        subscription_price = validated_data["subscription_price"]
        total = subscription_price.price
        subscription_kind = subscription_price.subscription.kind
        validated_data["kind"] = subscription_kind
        company_subscription_status = CompanySubscriptionStatusChoices.ACTIVE
        payment_information_status = PaymentInformationStatusChoices.SUCCEEDED
        if total > 0:
            total = total - subscription_price.discount
            company_subscription_status = CompanySubscriptionStatusChoices.PENDING
            payment_information_status = PaymentInformationStatusChoices.PENDING
        validated_data["amount"] = total
        user = self.context["request"].user
        validated_data["payment_by"] = user
        from weapi.django_rest.helpers.billing import resolve_billing_company

        company = resolve_billing_company(self.context["request"])

        company_subscription, company_subscription_created = (
            CompanySubscription.objects.get_or_create(
                company=company,
                # subscription_price=subscription_price,
                # status=company_subscription_status,
                defaults={
                    "subscription_price": subscription_price,
                    "status": company_subscription_status,
                    "created_by": user.get_employee(),
                },
                kind=subscription_kind,
            )
        )

        # Create payment information
        if (company_subscription_created and total > 0) or (
            not company_subscription.subscription_price.subscription.paymentinformation_set.filter(
                is_subscription_completed=False,
                kind=PaymentInformationKindChoices.COMPANY_SUBSCRIPTION,
            )
            and total > 0
        ):
            data = {
                "currency": subscription_price.subscription.currency,
                "slug": subscription_price.subscription.slug,
                "total": total,
                "kind": subscription_kind,
            }

            # Create payment intent
            payment_intent = complete_stripe_payment(data)
            validated_data["payment_intent_id"] = payment_intent["id"]
            validated_data["client_secret"] = payment_intent["client_secret"]
            validated_data["response_payload"] = payment_intent

        payment_information, _ = PaymentInformation.objects.get_or_create(
            subscription=subscription_price.subscription,
            company=company,
            status=payment_information_status,
            defaults=validated_data,
            kind=subscription_kind,
            is_subscription_completed=False,
        )
        return payment_information


class PrivateWeSubscriptionPaymentInformationDetailsSerializer(ModelSerializer):
    payment_by = PriateUserSlimSerializer(read_only=True)
    payment_method = PrivatePaymentMethodSlimSerializer(read_only=True)
    subscription = PublicSubscriptionListSerializer(read_only=True)
    subscription_price = PublicSubscriptionPriceListSerializer(read_only=True)

    class Meta:
        model = PaymentInformation
        fields = [
            "uid",
            "amount",
            "currency",
            "status",
            "kind",
            "subscription",
            "subscription_price",
            "payment_by",
            "payment_method",
            "payment_intent_id",
            "client_secret",
            "is_subscription_completed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "amount",
            "currency",
            "status",
            "kind",
            "payment_by",
            "payment_method",
            "client_secret",
            "is_subscription_completed",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        payment_intent_id = validated_data["payment_intent_id"]
        payment_intent = get_stripe_payment(payment_intent_id)
        if (
            self.instance.payment_intent_id != payment_intent_id
            or payment_intent["status"] != "succeeded"
            or self.instance.status != PaymentInformationStatusChoices.PENDING
        ):
            raise ValidationError(
                {"message": "Something wrong, contact to Balanbzify."}
            )
        validated_data["response_payload"] = payment_intent
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        company_subscription = company.companysubscription_set.first()
        if instance.status == PaymentInformationStatusChoices.PENDING:
            company_subscription.start_date = now()
        instance.status = PaymentInformationStatusChoices.SUCCEEDED
        instance.save()

        # Updating status of company subscription
        company_subscription.status = CompanySubscriptionStatusChoices.ACTIVE
        company_subscription.save_dirty_fields()
        return super().update(instance, validated_data)
    # azan ta sesh hok
