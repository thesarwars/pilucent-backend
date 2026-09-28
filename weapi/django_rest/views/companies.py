from rest_framework.generics import CreateAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from ..serializers.companies import PrivateWeCompanySerializer


class PrivateWeCompanyList(CreateAPIView):
    serializer_class = PrivateWeCompanySerializer
    permission_classes = [IsGroupPermission]
