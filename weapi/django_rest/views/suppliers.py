from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction

from rest_framework import filters
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription


from fileroomio.choices import FileItemStatusChoices
from fileroomio.models import FileItem


from purchaseio.models import Purchase

from supplierio.models import Supplier
from supplierio.choices import SupplierStatusChoices

from ..serializers.suppliers import (
    PrivateWeSupplierListSerializer,
    PrivateWeSupplierDetailsSerializer,
    PrivateWeSupplierBulkCreateSerializer,
    PrivateWeSupplierFileListSerializer,
    PrivateWeSupplierFileDetailsSerializer,
    PrivateWeSupplierTransactionListSerializer,
    PrivateWeSupplierPurchaseListSerializer,
)


class PrivateWeSupplierList(ListCreateAPIView):
    serializer_class = PrivateWeSupplierListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DateFromToRangeFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "title",
        "first_name",
        "last_name",
        "display_name",
        "email",
        "mobile_number",
    ]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return Supplier.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeSupplierDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSupplierDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_object(self):
        return get_object_or_404(
            Supplier.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Retire the supplier. Touch nothing in the ledger.

        The twin of the customer path fixed in c213f2b7 -- the customer version
        was copied from this one, comment and all. It did three things beyond
        setting a status, and each was a separate fault.

        IT VOIDED THEIR ENTIRE HISTORY. `JournalEntry.objects.filter(
        journalentryconnector__supplier=instance).update(status=REMOVED)` marked
        every entry the supplier had ever appeared in as removed -- every bill,
        payment and vendor credit -- in one bulk update. No reversing entry, so
        no audit trail of what happened or why; and nothing sets an entry's
        status back, so it was not reversible through the API. Cost and tax
        recognised in closed periods silently vanished from every report. The
        supplier row itself was only soft-deleted, so the record survived while
        its accounting history did not.

        IT MOVED TWO ACCOUNT BALANCES WITH NO JOURNAL ENTRY -- root cause R2. One
        of the two was "Other Miscellaneous Expense", which has no relationship
        to a supplier's payable.

        AND NEITHER ACCOUNT WAS GUARDED. `get_chart_of_account` returns a dict, so
        a company lacking either name yielded None and
        `update_opening_balance(None, ...)` raised -- a 500 on retiring a
        supplier.

        Retiring a supplier is a master-data change with no accounting
        consequence: their bills remain valid, their balance remains in A/P, and
        the ageing report still shows them. A document that genuinely should not
        stand is voided individually, through the paths that write reversing
        entries.
        """
        instance.status = SupplierStatusChoices.REMOVED
        instance.save()


class PrivateWeSupplierBulkCreate(CreateAPIView):
    serializer_class = PrivateWeSupplierBulkCreateSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_supplier_management"

    def get_queryset(self):
        return Supplier.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeSupplierFileList(ListAPIView):
    serializer_class = PrivateWeSupplierFileListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_queryset(self):
        kwargs = {
            "uid": self.kwargs.get("uid", None),
            "company": self.request.user.get_active_company(),
        }

        return FileItem.objects.filter(
            id__in=get_object_or_404(Supplier, **kwargs)
            .fileitemconnector_set.filter()
            .values_list("file_item_id", flat=True)
        ).exclude(status=FileItemStatusChoices.REMOVED)


class PrivateWeSupplierFileDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSupplierFileDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_object(self):
        kwargs = {
            "uid": self.kwargs.get("uid", None),
            "company": self.request.user.get_active_company(),
        }
        return get_object_or_404(
            FileItem.objects.filter(
                id__in=get_object_or_404(Supplier, **kwargs)
                .fileitemconnector_set.filter()
                .values_list("file_item_id", flat=True)
            ).exclude(status=FileItemStatusChoices.REMOVED),
            uid=self.kwargs.get("file_uid", None),
        )

    def perform_destroy(self, instance):
        instance.status = FileItemStatusChoices.REMOVED
        instance.save()


class PrivateWeSupplierTransactionList(ListAPIView):
    serializer_class = PrivateWeSupplierTransactionListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_queryset(self):
        supplier_uid = self.kwargs.get("uid")
        queryset = Purchase.objects.filter(
            supplier__uid=supplier_uid,
            supplier__company=self.request.user.get_active_company(),
        )
        return queryset


class PrivateWeSupplierPurchaseList(ListAPIView):
    serializer_class = PrivateWeSupplierPurchaseListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_queryset(self):
        supplier_uid = self.kwargs.get("uid")
        queryset = Purchase.objects.filter(
            supplier__uid=supplier_uid,
            supplier__company=self.request.user.get_active_company(),
        )
        return queryset


class PrivateWeSupplierPurchaseDetails(ListAPIView):
    serializer_class = PrivateWeSupplierPurchaseListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_supplier_management"

    def get_queryset(self):
        supplier_uid = self.kwargs.get("uid")
        queryset = Purchase.objects.filter(
            supplier__uid=supplier_uid,
            supplier__company=self.request.user.get_active_company(),
        )
        return queryset
