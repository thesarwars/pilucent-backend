from datetime import date, timedelta

from rest_framework import filters, response
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django.db import transaction

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from journalio.models import JournalEntry

from ..helpers.sale_payment_posting import (
    unapply_sale_payment_items,
    void_sale_payment_postings,
)
from django.db.models import Count, Q, Sum
from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer
from fileroomio.models import FileItem

from common.django_rest.permissions.company_subscription import HaveSubscription
from journalio.choices import JournalEntryConnectorRequestKindChoices


from salesio.choices import (
    SalesStatusChoices,
    SaleReceptKindChoices,
    SaleItemStatusChoices,
    SalePaymentReceiveStatusChoices,
)
from creditnoteio.choices import CreditNoteKindChoices
from creditnoteio.models import CreditNote

from salesio.models import Sale, SalePaymentReceive, SalesTax

from tagio.django_rest.serializers.common import PrivateTagSlimSerializer
from tagio.models import Tag

from ..helpers.sale_posting import (
    post_sale_document,
    recalculate_sale_totals,
    reverse_sale_postings,
    void_sale_postings,
)
from ..helpers.sales_documents import (
    document_matches_search,
    get_sale_document_type,
)
from ..serializers.creditnotes import PrivateWeCreditNoteListSerializer
from ..serializers.sales import (
    PrivateWeSaleListSerializer,
    PrivateWeSaleDetailsSerializer,
    PrivateWeSalesItemListSerializer,
    PrivateWeSalesItemDetailsSerializer,
    PrivateWeSalePaymentReceiveListSerializer,
    PrivateWeSalePaymentReceiveDetailsSerializer,
    PrivateWeSalesPaymentReceiveItemListSerializer,
    PrivateWeSaleSettingDetailsSerializer,
    PrivateWeSalesTaxListCreateSerializer,
)

SALE_TYPES = frozenset({"invoice", "estimate", "sale_receipt", "refund_receipt"})


class PrivateWeSalesDocumentList(ListAPIView):
    """Unified sales documents list: invoices, estimates, receipts, credit notes, payments."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    # Named explicitly: this view gives the permission resolver no model to
    # infer from, so it returned [] (or raised) and refused every user who is
    # not a superuser or `is_admin`. See adminio/tests_permission_resolution.py.
    required_permissions = ["view_sale"]

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        sale_type = request.query_params.get("sale_type", "all")
        context = {"request": request}
        records = []

        if sale_type in SALE_TYPES | {"all"}:
            sales = (
                Sale.objects.get_status_all()
                .filter(company=company)
                .select_related(
                    "customer",
                    "created_by",
                    "warehouse",
                    "payment_method",
                    "receivable_charter_account",
                    "payable_charter_account",
                )
            )
            for sale in sales:
                item_sale_type = get_sale_document_type(sale)
                if sale_type != "all" and item_sale_type != sale_type:
                    continue
                data = PrivateWeSaleListSerializer(sale, context=context).data
                data["sale_type"] = item_sale_type
                records.append((sale.created_at, data))

        if sale_type in {"credit_note", "all"}:
            credit_notes = (
                CreditNote.objects.get_status_all()
                .filter(company=company, kind=CreditNoteKindChoices.SALE)
                .select_related("customer", "supplier")
            )
            for credit_note in credit_notes:
                data = PrivateWeCreditNoteListSerializer(
                    credit_note, context=context
                ).data
                data["sale_type"] = "credit_note"
                records.append((credit_note.created_at, data))

        if sale_type in {"payment_received", "all"}:
            payments = (
                SalePaymentReceive.objects.get_status_all()
                .filter(company=company)
                .select_related("customer", "payment_method", "deposit_to")
            )
            for payment in payments:
                data = PrivateWeSalePaymentReceiveListSerializer(
                    payment, context=context
                ).data
                data["sale_type"] = "payment_received"
                data.setdefault("created_at", payment.created_at)
                data.setdefault("updated_at", payment.updated_at)
                records.append((payment.created_at, data))

        search = request.query_params.get("search")
        if search:
            search_lower = search.lower()
            records = [
                record
                for record in records
                if document_matches_search(record[1], search_lower)
            ]

        ordering = request.query_params.get("ordering", "-created_at")
        reverse = ordering.startswith("-")
        sort_field = ordering.lstrip("-")
        if sort_field == "created_at":
            records.sort(key=lambda record: record[0] or "", reverse=reverse)
        else:
            records.sort(
                key=lambda record: record[1].get(sort_field) or "",
                reverse=reverse,
            )

        items = [record[1] for record in records]
        page = self.paginate_queryset(items)
        if page is not None:
            return self.get_paginated_response(page)
        return response.Response(items)


class PrivateWeSaleList(ListCreateAPIView):
    serializer_class = PrivateWeSaleListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["tracking_number", "customer__email", "customer__display_name"]
    filterset_fields = [
        "status",
        "kind",
        "discount_kind",
        "tax_kind",
        "is_invoice",
        "is_estimated",
        "is_sale_receipt",
        "customer__uid",
    ]

    def get_queryset(self):
        queryset = Sale.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
        return (
            queryset.filter(due_total__gt=0)
            if self.request.query_params.get("due_total__gt", None) == 0
            else queryset
        )

    def list(self, request, *args, **kwargs):
        today = date.today()
        two_days_ago = date.today() - timedelta(days=2)
        queryset = self.get_queryset()
        data = None
        customer_uid = request.query_params.get("customer__uid", None)
        if request.query_params.get("keywords", None) == "overview":
            data = queryset.aggregate(
                estimated_count=Count(
                    "id",
                    filter=Q(is_estimated=True),
                ),
                estimated_total=Sum(
                    "total",
                    filter=Q(is_estimated=True),
                ),
                over_due_count=Count(
                    "id",
                    filter=Q(due_date__lt=today),
                ),
                over_due_total=Sum(
                    "total",
                    filter=Q(due_date__isnull=False) & Q(due_date__lt=today),
                ),
                invoice_count=Count(
                    "id",
                    filter=Q(is_invoice=True) & Q(status=SalesStatusChoices.OPEN),
                ),
                invoice_total=Sum(
                    "total",
                    filter=Q(is_invoice=True) & Q(status=SalesStatusChoices.OPEN),
                ),
                sale_receipt_count=Count(
                    "id",
                    filter=Q(is_sale_receipt=True) & Q(kind=SaleReceptKindChoices.SALE),
                ),
                sale_receipt_total=Sum(
                    "total",
                    filter=Q(is_sale_receipt=True) & Q(kind=SaleReceptKindChoices.SALE),
                ),
                refund_receipt_count=Count(
                    "id",
                    filter=Q(is_sale_receipt=True)
                    & Q(kind=SaleReceptKindChoices.REFUND),
                ),
                refund_receipt_total=Sum(
                    "total",
                    filter=Q(is_sale_receipt=True)
                    & Q(kind=SaleReceptKindChoices.REFUND),
                ),
                recently_paid_count=Count(
                    "id",
                    filter=Q(updated_at__gte=two_days_ago)
                    & Q(status=SalesStatusChoices.PAID),
                ),
                invoice_paid_total=Sum(
                    "total",
                    filter=Q(updated_at__gte=two_days_ago)
                    & Q(status=SalesStatusChoices.PAID),
                ),
            )
        if (
            request.query_params.get("open_invoice_reports", None) == "true"
            and customer_uid
        ):
            data = queryset.aggregate(
                total_open_balance=Sum(
                    "due_total",
                    filter=Q(is_invoice=True, customer__uid=customer_uid),
                ),
            )
        return (
            response.Response(data) if data else super().list(request, *args, **kwargs)
        )


class PrivateWeSaleDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSaleDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_object(self):
        return get_object_or_404(
            Sale.objects.get_status_all().filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Void the document; never erase it.

        This used to assign REMOVED to the in-memory instance and then hard
        delete the row anyway -- the assignment was never saved, so it was dead
        code. `JournalEntry.sale` is CASCADE, so the delete took the entry and
        every one of its lines with it, while leaving every `opening_balance`
        those lines had moved exactly where it was. The books kept the effect of
        an invoice that no longer existed, and because the entry was gone too,
        there was nothing left to measure the damage against.

        A posted document is now reversed by a posted reversal and the row is
        marked REMOVED. `SalesQuerySet.get_status_all()` already excludes those,
        so it disappears from every list while its history stays intact.
        """
        if instance.is_estimated == False:
            void_sale_postings(
                instance, created_by=self.request.user.get_employee()
            )
        instance.status = SalesStatusChoices.REMOVED
        instance.save(update_fields=["status", "updated_at"])


class PrivateWeSalesItemList(ListAPIView):
    serializer_class = PrivateWeSalesItemListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status"]
    pagination_class = None

    def get_queryset(self):
        return (
            get_object_or_404(
                Sale.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .saleitem_set.exclude(status=SaleItemStatusChoices.REMOVED)
            .select_related("product", "tax")
        )


class PrivateWeSalesItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSalesItemDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_object(self):
        return get_object_or_404(
            get_object_or_404(
                Sale.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            ).saleitem_set.filter(uid=self.kwargs["sale_item_uid"])
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Drop one line, then let the document repost itself.

        This was ~265 lines that tried to unwind a single line's postings by
        hand: walk its connectors, infer how much stock to hand back to each
        lot, adjust three accounts, and delete the rows it had matched. It is
        the same patch-in-place approach that made amendment wrong, with the
        same failure modes -- it could only find the connectors it recognised,
        and anything it missed stayed in the ledger.

        The document already knows how to post itself from its lines. So mark
        the line REMOVED, reverse what the document posted, and post it again
        without it. The result is identical to the sale having been entered
        that way, which is exactly what deleting a line means.
        """
        sale = instance.sale

        # Deleting ONE line reverses and reposts the WHOLE document, and the
        # reverse half deletes its entries outright. So removing line 2 of a
        # three-line sale destroys the legs of lines 1 and 3 as well -- a
        # reconciled bank leg among them, on a line the user never touched.
        assert_not_reconciled(
            JournalEntry.objects.filter(sale=sale), action="change"
        )

        instance.status = SaleItemStatusChoices.REMOVED
        instance.save(update_fields=["status", "updated_at"])

        if sale.is_estimated == False:
            reverse_sale_postings(sale)
            # No payload accompanies a DELETE, so the header has to be derived
            # from what is left or A/R keeps debiting for the removed line.
            recalculate_sale_totals(sale)
            post_sale_document(
                sale,
                created_by=self.request.user.get_employee(),
                request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
            )


class PrivateWeSaleTagList(ListAPIView):
    serializer_class = PrivateTagSlimSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return Tag.objects.filter(
            id__in=(
                get_object_or_404(
                    Sale.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )


class PrivateWeSaleFileItemList(ListAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
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
                    Sale.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.SALE
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWeSalesFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                Sale.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.SALE,
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


class PrivateWeSalePaymentReceiveList(ListCreateAPIView):
    serializer_class = PrivateWeSalePaymentReceiveListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "reference_number",
        "customer__company_email",
        "customer__first_name",
        "customer__last_name",
        "customer__company_name",
    ]
    filterset_fields = ["status"]

    def get_queryset(self):
        return SalePaymentReceive.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeSalePaymentReceiveDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSalePaymentReceiveDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_object(self):
        return get_object_or_404(
            SalePaymentReceive.objects.get_status_all().filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Reverse what the payment did, then retire it.

        This used to be the two lines below and nothing else. The document
        vanished from its list -- `get_status_all()` excludes REMOVED -- while
        `JournalEntry.status` was untouched, so both legs stayed PUBLISHED and
        the payment stayed in the bank register, in its balance, and in the set
        of documents `/reconcile/complete` offers to tick. A deleted payment
        the user is still asked to reconcile is a transaction they can neither
        remove nor honestly account for.

        Refused outright when a closed reconciliation already signed off one of
        those legs: deleting it would leave that session asserting a zero
        difference against lines that no longer exist. Undo it first.
        """
        if instance.status == SalePaymentReceiveStatusChoices.REMOVED:
            return
        assert_not_reconciled(
            JournalEntry.objects.filter(sale_payment_receive=instance),
            action="delete",
        )
        void_sale_payment_postings(
            instance, created_by=self.request.user.get_employee()
        )
        unapply_sale_payment_items(instance)
        instance.status = SalePaymentReceiveStatusChoices.REMOVED
        instance.save(update_fields=["status"])


class PrivateWeSalePaymentReceiveItemList(ListAPIView):
    serializer_class = PrivateWeSalesPaymentReceiveItemListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return (
            get_object_or_404(
                SalePaymentReceive.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .salepaymentreceiveitem_set.all()
            .select_related("sale", "credit_note")
        )


class PrivateWeSalePaymentReceiveFileItemList(ListAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
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
                    SalePaymentReceive.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.SALE_PAYMENT_RECEIVE
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWeSalesPaymentReceiveFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                SalePaymentReceive.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.SALE_PAYMENT_RECEIVE,
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


class PrivateWeSalesTaxCreateList(ListCreateAPIView):
    serializer_class = PrivateWeSalesTaxListCreateSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["sales_tax_period"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return SalesTax.objects.filter(company=self.request.user.get_active_company())


class PrivateWeSellSettingDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeSaleSettingDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"

    def get_object(self):
        sell_setting = self.request.user.get_company_sale_setting()
        if not sell_setting:
            raise NotFound(detail="Sale settings not found.")
        return sell_setting


class InvoiceDashboardOverview(ListAPIView):
    queryset = Sale.objects.all()
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_sales"
    pagination_class = None

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        queryset = Sale.objects.get_status_all().filter(
            company=company,
            kind=SaleReceptKindChoices.SALE,
            is_invoice=True,
        )

        # Optional date range filtering (expects YYYY-MM-DD)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            queryset = queryset.filter(invoice_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(invoice_date__lte=end_date)

        # Ensure we use defined choice constants when available, fall back to literal strings
        statuses = {
            "draft": getattr(SalesStatusChoices, "DRAFT", "draft"),
            "pending": getattr(SalesStatusChoices, "PENDING", "pending"),
            "open": getattr(SalesStatusChoices, "OPEN", "open"),
            "accepted": getattr(SalesStatusChoices, "ACCEPTED", "accepted"),
            "paid": getattr(SalesStatusChoices, "PAID", "paid"),
        }

        result = {}
        for key, val in statuses.items():
            agg = queryset.aggregate(
                invoice_count=Count("id", filter=Q(status=val)),
                amount=Sum("total", filter=Q(status=val)),
            )
            result[key] = {
                "invoice_count": agg.get("invoice_count") or 0,
                "amount": float(agg.get("amount") or 0),
            }

        # Totals across the requested statuses
        total_agg = queryset.aggregate(
            invoice_count=Count("id", filter=Q(status__in=list(statuses.values()))),
            amount=Sum("total", filter=Q(status__in=list(statuses.values()))),
        )
        result["total"] = {
            "invoice_count": total_agg.get("invoice_count") or 0,
            "amount": float(total_agg.get("amount") or 0),
        }

        result["date_range"] = {"start_date": start_date, "end_date": end_date}

        return response.Response(result)
