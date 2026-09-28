from rest_framework.serializers import ModelSerializer, ValidationError

from accounts.models import OTP

from common.django_rest.helpers.otp_helpers import get_otp
from common.django_rest.helpers.emails import send_user_email_verification_otp


class UserEmailVerificationSentOtpSerializer(ModelSerializer):
    class Meta:
        model = OTP
        fields = ["is_consumed"]
        read_only_fields = fields

    def create(self, validated_data):
        user = self.context["request"].user
        # Delete all existing OTPs associate with the request user
        OTP.objects.filter(user=user).delete()
        otp = get_otp()
        # Create OTP
        OTP.objects.create(user=user, otp=otp)
        send_user_email_verification_otp(user.email, user.name, otp)
        return validated_data


class UserEmailVerificationSentSerializer(ModelSerializer):
    class Meta:
        model = OTP
        fields = ["otp"]

    def validate(self, attrs):
        user = self.context["request"].user
        otp = OTP.objects.filter(user=user, otp=attrs["otp"], is_consumed=False).first()
        if not otp:
            raise ValidationError({"message":"Invalid OTP"})
        attrs["user"] = user
        attrs["otp"] = otp
        return attrs

    def create(self, validated_data):
        user = validated_data.pop("user")
        otp = validated_data.pop("otp")

        # Update otp
        otp.is_consumed = True
        otp.save_dirty_fields()

        # Update user
        user.is_email_verified = True
        user.save_dirty_fields()
        return otp
