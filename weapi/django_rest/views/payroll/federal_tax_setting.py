from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from payrollio.models import PayrollFederalTaxInfoSetting

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
from weapi.django_rest.serializers.payroll.federal_tax_setting import (
    PrivateWePayrollFederalTaxInfoSettingListCreateSerializer,
    PrivateWePayrollFederalTaxInfoSettingDetailUpdateSerializer,
    PrivateWePayrollFederalTaxInfoSettingItemsListCreateSerializer,
    PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateSerializer,
)


class PrivateWePayrollFederalTaxInfoSettingListCreateView(ListCreateAPIView):
    serializer_class = PrivateWePayrollFederalTaxInfoSettingListCreateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    pagination_class = None
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ["ein_number"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        return PayrollFederalTaxInfoSetting.objects.filter(
            company=self.request.user.get_active_company()
        )


class PrivateWePayrollFederalTaxInfoSettingDetailUpdateView(
    RetrieveUpdateDestroyAPIView
):
    serializer_class = PrivateWePayrollFederalTaxInfoSettingDetailUpdateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        uid = self.kwargs.get("uid")
        return get_object_or_404(
            PayrollFederalTaxInfoSetting,
            uid=uid,
            company=self.request.user.get_active_company(),
        )


class PrivateWePayrollFederalTaxInfoSettingItemsCreateListView(ListCreateAPIView):
    serializer_class = PrivateWePayrollFederalTaxInfoSettingItemsListCreateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["payroll_federal_tax_info"] = get_object_or_404(
            PayrollFederalTaxInfoSetting,
            uid=self.kwargs["uid"],
            company=self.request.user.get_active_company(),
        )
        return context

    def get_queryset(self):
        uid = self.kwargs.get("uid")
        return PayrollFederalTaxInfoSetting.objects.filter(
            uid=uid,
            company=self.request.user.get_active_company(),
        ).first().items.all()


class PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateView(
    RetrieveUpdateDestroyAPIView
):
    serializer_class = PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        return get_object_or_404(
            get_object_or_404(
                PayrollFederalTaxInfoSetting.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            ).items.filter(
                uid=self.kwargs["item_uid"],
            )
        )

    