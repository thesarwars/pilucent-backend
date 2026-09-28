from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from payrollio.models import PayrollGeneralTaxSetting
from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
from weapi.django_rest.serializers.payroll.general_tax_setting import (
    PrivateWePayrollGeneralTaxSettingListCreateSerializer,
    PrivateWePayrollGeneralTaxSettingDetailUpdateSerializer,
)

class PrivateWePayrollGeneralTaxSettingListCreateView(ListCreateAPIView):
    serializer_class = PrivateWePayrollGeneralTaxSettingListCreateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ["title", "address", "city", "state", "zip_code", "ein_number"]
    filterset_fields = [
        "company_type",
    ]

    def get_queryset(self):
        return PayrollGeneralTaxSetting.objects.filter(
            company=self.request.user.get_active_company()
        )

class PrivateWePayrollGeneralTaxSettingDetailUpdateView(RetrieveUpdateAPIView):
    serializer_class = PrivateWePayrollGeneralTaxSettingDetailUpdateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        uid = self.kwargs.get("uid")
        return get_object_or_404(
            PayrollGeneralTaxSetting,
            uid=uid,
            company=self.request.user.get_active_company()
        )
