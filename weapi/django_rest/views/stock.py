from datetime import date

from django.db import transaction

from rest_framework import filters, response

from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from django_filters.rest_framework import DjangoFilterBackend

from journalio.models import JournalEntry

from stockio.models import StockAdjustment, StockAdjustmentItem, StockAlert
from stockio.choices import (
    StockAdjustmentStatusChoices,
    StockAlertStatusChoices,
)

from weapi.django_rest.helpers.stock_adjustment_posting import (
    restore_stock_adjustment_inventory,
    void_stock_adjustment_postings,
)
from weapi.django_rest.serializers.stock import (
    PrivateWeStockLevelSerializer,
    PrivateWeStockLevelDetailSerializer,
    PrivateWeStockAdjustmentSerializer,
    PrivateWeStockAdjustmentDetailSerializer,
    PrivateWeStockAdjustmentItemSerializer,
)


class PrivateWeStockLevel(ListCreateAPIView):
    serializer_class = PrivateWeStockLevelSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["description"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return StockAlert.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeStockLevelDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeStockLevelDetailSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            StockAlert.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = StockAlertStatusChoices.REMOVED
        instance.save()


class PrivateWeStockAdjustment(ListCreateAPIView):
    serializer_class = PrivateWeStockAdjustmentSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["description", "reference_number"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return StockAdjustment.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeStockAdjustmentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeStockAdjustmentDetailSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            StockAdjustment.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Put the stock and the ledger back, then retire the adjustment.

        This was the two lines below and nothing else, on the one document whose
        entire purpose is to move inventory: the units stayed on hand, the cost
        layers stayed created or spent, and both journal legs stayed PUBLISHED,
        so the adjustment account went on carrying a write-up for a document
        that no longer existed.

        Inventory is restored **before** the journal is reversed, because the
        inventory half is the half that can refuse -- stock this adjustment
        added may already have been sold. Reversing the journal first would mean
        a refusal had to unwind legs it had just written; instead nothing at all
        is posted unless the stock can honestly come back.

        Locked for the same reason the payment deletes lock: the status is read
        here and acted on below, and two concurrent deletes would otherwise both
        pass the check and both reverse.
        """
        adjustment = StockAdjustment.objects.select_for_update().get(pk=instance.pk)
        if adjustment.status == StockAdjustmentStatusChoices.REMOVED:
            return

        assert_not_reconciled(
            JournalEntry.objects.filter(stock_adjustment=adjustment), action="delete"
        )

        restore_stock_adjustment_inventory(adjustment)
        void_stock_adjustment_postings(
            adjustment, created_by=self.request.user.get_employee()
        )

        adjustment.status = StockAdjustmentStatusChoices.REMOVED
        adjustment.save(update_fields=["status"])


class PrivateWeStockAdjustmentItemList(ListAPIView):
    serializer_class = PrivateWeStockAdjustmentItemSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["quantity", "description"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return StockAdjustmentItem.objects.get_status_all().filter(
            stock_adjustment__company=self.request.user.get_active_company(),
            stock_adjustment__uid=self.kwargs["uid"],
        )
