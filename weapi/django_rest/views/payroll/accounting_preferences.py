from django.db.models import Prefetch
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission


from payrollio.models import (
    PayrollAccountingPreferencesSetting,
    PayrollAccountExpenseAccountComponent,
)

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)
from weapi.django_rest.serializers.payroll.accounting_preferences import (
    PrivateWePayrollAccountingPreferencesListCreateSerializer,
)


class PrivateWePayrollAccountingPreferencesListCreateView(ListCreateAPIView):
    serializer_class = PrivateWePayrollAccountingPreferencesListCreateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ["company__name"]
    filterset_fields = [
        "wage_expense_type",
        "company_contribution_expense_type",
        "employer_tax_expense_type",
        "tax_liability_expense_type",
    ]
    pagination_class = None

    def get_queryset(self):
        expense_type = self.request.query_params.get("expense_type")
        if expense_type:
            expense_accounts_prefetch = Prefetch(
                "expense_accounts",
                queryset=PayrollAccountExpenseAccountComponent.objects.filter(
                    payroll_accounting_preferences_type=expense_type
                ),
            )
            return PayrollAccountingPreferencesSetting.objects.filter(
                company=self.request.user.get_active_company()
            ).prefetch_related(expense_accounts_prefetch)
        else:
            return PayrollAccountingPreferencesSetting.objects.filter(
                company=self.request.user.get_active_company()
            ).prefetch_related("expense_accounts")
