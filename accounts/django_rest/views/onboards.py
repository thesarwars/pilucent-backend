from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny

from ..serializers.onboards import EmployeeOnboardSerializer


class EmployeeOnboardView(CreateAPIView):
    serializer_class = EmployeeOnboardSerializer
    permission_classes = [AllowAny]
