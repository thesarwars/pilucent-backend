from django.contrib.auth.tokens import PasswordResetTokenGenerator

from rest_framework import serializers

from accounts.models import User

from ..helpers.emails import send_forget_password_link_email


class ForgetPasswordSendLinkSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True, required=True)

    def validate(self, attrs):
        user = User.objects.filter(email=attrs["email"]).first()
        if not user:
            raise serializers.ValidationError({"message":"Account dosn't exist with this email."})
        attrs["user"] = user
        return super().validate(attrs)

    def create(self, validated_data):
        user = validated_data.pop("user")
        token = PasswordResetTokenGenerator().make_token(user)
        send_forget_password_link_email(validated_data["email"], user.uid, token)
        return validated_data


class ForgetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, required=True)
