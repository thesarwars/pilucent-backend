from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    DestroyAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination

from payrollio.models import (
    PayrollStateTaxInfoSetting,
    PayrollStateTaxPaymentSchedule,
    PayrollUnemploymentInsuranceTaxInfo,
    PayrollFederalLoanInterestPaymentSchedule,
    PayrollReemploymentOrWorkforceServiceFund,
    PayrollMCTMTZone,
)
from rest_framework.response import Response
from rest_framework import status, permissions

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
from weapi.django_rest.serializers.payroll.state_tax_setting import (
    PayrollStateTaxInfoSettingSerializer,
    PayrollStateTaxInfoDetailsUpdateSettingSerializer,
)


class PrivateWePayrollStateTaxSettingView(ListCreateAPIView):
    serializer_class = PayrollStateTaxInfoSettingSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    pagination_class = CustomPageNumberPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.OrderingFilter,
        filters.SearchFilter,
    ]
    filterset_fields = ["state", "company"]
    search_fields = ["state", "win_number"]
    ordering_fields = ["state", "created_at"]

    def get_queryset(self):
        return PayrollStateTaxInfoSetting.objects.filter(
            company=self.request.user.get_active_company()
        )


class PrivateWePayrollStateTaxSettingDetailsUpdateView(RetrieveUpdateDestroyAPIView):
    serializer_class = PayrollStateTaxInfoDetailsUpdateSettingSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        uid = self.kwargs.get("uid")
        return get_object_or_404(
            PayrollStateTaxInfoSetting,
            uid=uid,
            company=self.request.user.get_active_company(),
        )


class PrivateWePayrollStateTaxRelatedDeleteView(DestroyAPIView):
    """
    API endpoint to delete a related payroll object by uid, searching all four models.
    """
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    # Named explicitly: this view gives the permission resolver no model to
    # infer from, so it returned [] (or raised) and refused every user who is
    # not a superuser or `is_admin`. See adminio/tests_permission_resolution.py.
    required_permissions = ["delete_payrollstatetaxinfosetting"]

    def delete(self, request, uid):
        company = request.user.get_active_company()
        models_to_search = [
            PayrollStateTaxPaymentSchedule,
            PayrollUnemploymentInsuranceTaxInfo,
            PayrollReemploymentOrWorkforceServiceFund,
            PayrollFederalLoanInterestPaymentSchedule,
            PayrollMCTMTZone,
        ]
        obj = None
        for model in models_to_search:
            try:
                candidate = model.objects.get(uid=uid)
                if candidate.payroll_state_tax_info.company == company:
                    obj = candidate
                    break
            except model.DoesNotExist:
                continue
        if obj:
            obj.delete()
            return Response(
                {"message": "Deleted successfully."}, status=status.HTTP_204_NO_CONTENT
            )
        return Response(
            {"message": "Item not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
