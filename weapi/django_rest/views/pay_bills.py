from django.db import transaction

from rest_framework import filters
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from journalio.models import JournalEntry

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.models import FileItem
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer

from weapi.django_rest.helpers.pay_bill_posting import (
    reverse_pay_bill_item_postings,
    reverse_pay_bill_postings,
)

from purchaseio.choices import PayBillStatusChoices
from purchaseio.models import PayBill, PayBillItem

from tagio.django_rest.serializers.common import PrivateTagSlimSerializer
from tagio.models import Tag

from ..serializers.pay_bills import (
    PrivateWePayBillListSerializer,
    PrivateWePayBillDetailsSerializer,
    PrivateWePayBillItemListSerializer,
    PrivateWePayBillItemDetailsSerializer,
)


class PrivateWePayBillList(ListCreateAPIView):
    serializer_class = PrivateWePayBillListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return PayBill.objects.filter(company=self.request.user.get_active_company())


class PrivateWePayBillDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePayBillDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            PayBill.objects.filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Undo the whole payment before removing it.

        Every payee line, then whatever journal entry is left. Deleting the
        payment cascades to its items and their applications, so without this
        the bills keep the payment and lose every trace of it -- while A/P, the
        vendor balances and the funding account keep a payment that no longer
        exists.
        """
        assert_not_reconciled(
            JournalEntry.objects.filter(pay_bill=instance), action="delete"
        )
        reverse_pay_bill_postings(instance)
        super().perform_destroy(instance)


class PrivateWePayBillItemList(ListCreateAPIView):
    serializer_class = PrivateWePayBillItemListSerializer
    permission_classes = [IsGroupPermission]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uid"] = self.kwargs.get("uid")
        return context

    def get_queryset(self):
        return PayBillItem.objects.filter(
            pay_bill__uid=self.kwargs["uid"],
            pay_bill__company=self.request.user.get_active_company(),
        )


class PrivateWePayBillItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePayBillItemDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            PayBillItem.objects.filter(
                pay_bill__uid=self.kwargs["uid"],
                pay_bill__company=self.request.user.get_active_company(),
                uid=self.kwargs["item_uid"],
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Undo everything this payee line did before removing it.

        The bills it paid, the journal legs it wrote, the control-account
        balances they moved, and the vendor balance. Deleting a payee line used
        to remove the row and leave all of that standing, so the books said
        money had been paid that had not.

        Atomic with the delete: a reversal that commits without it leaves a
        payment on the books with no effect, which is worse than either state.
        """
        # `reverse_pay_bill_item_postings` HARD-DELETES this line's legs
        # (`pay_bill_posting.py:114-116`) and then the entry when the line was
        # the last on it. Unlike the six guarded document deletes nothing is
        # appended -- the signed-off row is simply gone, leaving the closed
        # session one cleared line short with no record of why.
        assert_not_reconciled(
            JournalEntry.objects.filter(pay_bill=instance.pay_bill),
            action="delete",
        )
        reverse_pay_bill_item_postings(instance)
        super().perform_destroy(instance)


class PrivateWePayBillFileItemList(ListCreateAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return FileItem.objects.filter(
            id__in=(
                get_object_or_404(
                    PayBill.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.PAY_BILL
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWePayBillFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [IsGroupPermission]

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                PayBill.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.PAY_BILL,
                file_item__uid=self.kwargs["file_uid"],
            )
            .first()
        )

    def get_object(self):
        if file_item_connector := self.get_file_item_connector():
            return file_item_connector.file_item

    def perform_destroy(self, instance):
        file_item_connector = self.get_file_item_connector()
        return file_item_connector.delete()


class PrivateWePaybillTagList(ListAPIView):
    serializer_class = PrivateTagSlimSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return Tag.objects.filter(
            id__in=(
                get_object_or_404(
                    PayBill.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )
