from rest_framework import permissions, filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
    RetrieveAPIView,
)
from django_filters.rest_framework import DjangoFilterBackend

from payrollio.models import PayrollContactInfoSetting
from weapi.django_rest.serializers.payroll.contact_info_setting import (
    PayrollContactInfoSettingSerializer,
    PayrollContactInfoSettingSerializerDetailUpdateSerializer,
)
from rest_framework.response import Response
from rest_framework import status

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


class PayrollContactInfoSettingCreateView(ListCreateAPIView):
    serializer_class = PayrollContactInfoSettingSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = [
        "contact_first_name",
        "contact_last_name",
        "contact_email",
        "contact_phone",
    ]

    def get_queryset(self):
        return PayrollContactInfoSetting.objects.filter(
            company=self.request.user.get_active_company()
        )


class PayrollContactInfoSettingDetailUpdateView(RetrieveUpdateDestroyAPIView):
    serializer_class = PayrollContactInfoSettingSerializerDetailUpdateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        uid = self.kwargs.get("uid")
        return get_object_or_404(
            PayrollContactInfoSetting,
            uid=uid,
            company=self.request.user.get_active_company(),
        )
