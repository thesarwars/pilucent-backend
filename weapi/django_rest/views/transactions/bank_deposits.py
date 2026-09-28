from rest_framework import filters

from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django_filters.rest_framework import DjangoFilterBackend
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from transactionio.choices import BankDepositStatusChoices
from transactionio.models import BankDeposit, BankDepositItem

from weapi.django_rest.serializers.transactions.bank_deposits import (
    PrivateWeBankDepositListCreateSerializer,
)


class PrivateWeBankDepositListCreateView(ListCreateAPIView):
    serializer_class = PrivateWeBankDepositListCreateSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at", "date"]
    filterset_fields = [
        "bank_chart_of_account__uid",
        "date",
        "status",
        "created_by__uid",
    ]
    search_fields = filterset_fields + [
        "description",
        "cash_back_memo",
        "bank_chart_of_account__title",
        "bank_chart_of_account__code",
    ]

    def get_queryset(self):
        """Get bank deposits for the current company"""
        return (
            BankDeposit.objects.filter(company=self.request.user.get_active_company())
            .exclude(status=BankDepositStatusChoices.REMOVED)
            .select_related(
                "bank_chart_of_account",
                "cash_back_account",
                "created_by",
                "created_by__user",
            )
            .prefetch_related(
                "deposit_items",
                "deposit_items__customer",
                "deposit_items__supplier",
                "deposit_items__received_from_account",
                "deposit_items__payment_method",
            )
        )

    def list(self, request, *args, **kwargs):
        """List bank deposits with additional statistics"""
        response = super().list(request, *args, **kwargs)

        # Add summary statistics
        queryset = self.get_queryset()

        # Calculate totals
        total_deposits = queryset.filter(
            status=BankDepositStatusChoices.COMPLETED
        ).count()
        total_amount = sum(
            deposit.total_deposit_amount
            for deposit in queryset.filter(status=BankDepositStatusChoices.COMPLETED)
        )
        pending_deposits = queryset.filter(
            status=BankDepositStatusChoices.PENDING
        ).count()
        draft_deposits = queryset.filter(status=BankDepositStatusChoices.DRAFT).count()

        response.data["summary"] = {
            "total_deposits": total_deposits,
            "total_amount": total_amount,
            "pending_deposits": pending_deposits,
            "draft_deposits": draft_deposits,
        }

        return response
