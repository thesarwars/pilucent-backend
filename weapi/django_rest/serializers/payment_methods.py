from rest_framework.serializers import ModelSerializer, ValidationError

from common.django_rest.helpers.decorators import set_auditlog_actor

from paymentio.models import PaymentMethod
from paymentio.choices import PaymentMethodStatusChoices


class PrivateWePaymentMethodListSerializer(ModelSerializer):
	class Meta:
		model = PaymentMethod
		fields = [
			"uid",
			"title",
			"status",
		]

		read_only_fields = ["uid", "status", "created_at", "updated_at"]

	def validate(self, attrs):
		company = self.context["request"].user.get_active_company()
		if PaymentMethod.objects.get_status_all().filter(title=attrs["title"], company=company).exists():
			raise ValidationError(
				"Payment method with this title already exists in your company"
			)
		attrs["company"] = company
		attrs["status"] = PaymentMethodStatusChoices.ACTIVE
		return super().validate(attrs)

	@set_auditlog_actor
	def create(self, validated_data):
		return super().create(validated_data)


class PrivateWePaymentMethodDetailsSerializer(ModelSerializer):
	class Meta:
		model = PaymentMethod
		fields = [
			"uid",
			"title",
			"status",
		]

		read_only_fields = ["uid", "created_at", "updated_at"]

	@set_auditlog_actor
	def update(self, instance, validated_data):
		validated_data["company"] =self.context["request"].user.get_active_company()
		return super().update(instance, validated_data)