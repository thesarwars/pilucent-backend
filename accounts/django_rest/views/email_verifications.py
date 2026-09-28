from rest_framework.generics import CreateAPIView, UpdateAPIView

from ..serializers.email_verifications import UserEmailVerificationSentOtpSerializer, UserEmailVerificationSentSerializer


class UserEmailVerificationSendOTPView(CreateAPIView):
    serializer_class = UserEmailVerificationSentOtpSerializer

class UserEmailVerificationView(CreateAPIView):
    serializer_class = UserEmailVerificationSentSerializer

