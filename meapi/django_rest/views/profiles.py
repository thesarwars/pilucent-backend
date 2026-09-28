from rest_framework.generics import RetrieveUpdateAPIView, UpdateAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from ..serializer.profiles import (
    PrivateMeProfileDetailSerializer,
    PrivateMeProfileChangePasswordSrializer,
)


class PrivateMeProfileDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateMeProfileDetailSerializer
    # permission_classes = [IsGroupPermission]

    def get_object(self):
        return self.request.user


class PrivateMeProfileChangePasswordView(UpdateAPIView):
    serializer_class = PrivateMeProfileChangePasswordSrializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return self.request.user
