from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny

from ..serializers.user_register import UserRegisterSerializer


class UserRegisterView(CreateAPIView):
    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny]
