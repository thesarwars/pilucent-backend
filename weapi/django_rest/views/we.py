from rest_framework.exceptions import NotFound

from rest_framework.generics import RetrieveUpdateAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from ..serializers.we import PrivateWeDetailsSerializer, PrivateWeSettingSerializer


class PrivateWeDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeDetailsSerializer
    # permission_classes = [IsGroupPermission]

    def get_object(self):
        company = self.request.user.get_active_company()
        if not company:
            raise NotFound(detail="Company not found.")
        return company


class PrivateWeSettingDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeSettingSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_company_setting"

    def get_object(self):
        company_setting = self.request.user.get_company_setting()
        if not company_setting:
            raise NotFound(detail="Company setting not found.")
        return company_setting
