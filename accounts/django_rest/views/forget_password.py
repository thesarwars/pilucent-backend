from django.contrib.auth.tokens import PasswordResetTokenGenerator

from rest_framework.response import Response

from rest_framework.generics import CreateAPIView, UpdateAPIView, get_object_or_404
from rest_framework.permissions import AllowAny

from ..serializers.forget_password import (
    ForgetPasswordSendLinkSerializer,
    ForgetPasswordSerializer,
)

from ...models import User


class ForgetPasswordSendLinkView(CreateAPIView):
    serializer_class = ForgetPasswordSendLinkSerializer
    permission_classes = [AllowAny]


class ForgetPasswordView(UpdateAPIView):
    serializer_class = ForgetPasswordSerializer
    permission_classes = [AllowAny]

    def update(self, request, *args, **kwargs):
        user = get_object_or_404(User.objects.filter(uid=self.kwargs.get("uid", None)))
        token = self.kwargs.get("token", None)
        serializer = self.get_serializer(
            user, data=request.data, context={"token": token}
        )
        if serializer.is_valid():
            if PasswordResetTokenGenerator().check_token(user, token):
                user.set_password(serializer.validated_data["password"])
                user.save()
                return Response({"message": "Password reset successful."}, status=200)
        return Response({"message": "Ivalid."}, status=400)
