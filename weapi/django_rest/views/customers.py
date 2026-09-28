import logging

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.db import transaction
from rest_framework.generics import (
    CreateAPIView,
    ListCreateAPIView,
    ListAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework import filters, status

from common.django_rest.helpers.customer_references import (
    active_children,
    blocking_references,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.crud_logger import CrudAction, crud_log
from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription

from customerio.models import Customer
from customerio.choices import CustomerStatusChoices

from fileroomio.choices import FileItemStatusChoices
from fileroomio.models import FileItem


from salesio.models import Sale
from django.db.models import Sum

from ..serializers.customers import (
    PrivateWeCustomerListSerializer,
    PrivateWeCustomerDetailsSerializer,
    PrivateWeCustomerBulkCreateSerializer,
    PrivateWeCustomerFileListSerializer,
    PrivateWeCustomerTransactionListSerializer,
    PrivateWeSaleInvoiceListByCustomerSerializer,
)

logger = logging.getLogger(__name__)


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeCustomerList(ListCreateAPIView):
    serializer_class = PrivateWeCustomerListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_customer"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DateFromToRangeFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    filterset_fields = ["status", "currency"]
    search_fields = ["first_name", "last_name", "email", "mobile_number"]

    def get_queryset(self):
        return Customer.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        company = self.request.user.get_active_company()
        crud_log(
            logger,
            CrudAction.CREATED,
            instance,
            actor=self.request.user,
            extra={"company_uid": str(getattr(company, "uid", ""))},
        )


class PrivateWeCustomerDeactivate(APIView):
    """Retire a customer from data entry without touching their books.

    The product spec lists "Mark Customer as Inactive" as a customer action and
    expects the list to offer an "include inactive customers" toggle. Neither
    existed, so delete was the only way to retire a customer -- which is what
    made the ledger-voiding `perform_destroy` reachable at all, before c213f2b7
    reduced it to a status change.

    POST   /we/customers/{uid}/deactivate     make inactive
    DELETE /we/customers/{uid}/deactivate     make active again

    Deliberately weaker than the chart-of-account equivalent, in one specific
    way: **there is no balance precondition.** An account holding a balance is
    refused because retiring it carries that figure off the reports. A customer
    is the opposite -- CUSTOMER_INDUSTRY_STANDARD.md section 4, and QuickBooks
    and Xero both: their invoices stay valid, their balance stays in A/R, and
    the ageing report still shows them. A customer who has stopped buying but
    still owes money is the ordinary reason to reach for this, so refusing until
    they have paid would make it useless exactly when it is wanted.

    * **CUST-151** something still routes future documents at them -- a
      recurring template or a bank rule. History never blocks.
    * **CUST-152** sub-customers must be retired first, or `cascade`.
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_customer"
    required_permissions = ["change_customer"]

    def get_object(self):
        return get_object_or_404(
            Customer.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def post(self, request, *args, **kwargs):
        customer = self.get_object()
        cascade = str(request.data.get("cascade", "")).lower() in ("true", "1", "yes")

        if customer.status == CustomerStatusChoices.INACTIVE:
            return Response(
                {"message": "This customer is already inactive."},
                status=status.HTTP_200_OK,
            )

        references = blocking_references(customer)
        if references:
            raise ValidationError(
                {
                    "code": "CUST-151",
                    "message": (
                        f"{sum(r['count'] for r in references)} setting(s) would "
                        "still create documents for this customer. Point them "
                        "somewhere else first."
                    ),
                    "references": references,
                }
            )

        children = list(active_children(customer))
        if children and not cascade:
            raise ValidationError(
                {
                    "code": "CUST-152",
                    "message": (
                        f"This customer has {len(children)} active sub-customer(s). "
                        "Deactivate them first, or resend with cascade."
                    ),
                    "children": [
                        {"uid": str(c.uid), "title": c.display_name or c.first_name}
                        for c in children
                    ],
                }
            )

        with transaction.atomic():
            retired = self._deactivate(customer, cascade=cascade)

        return Response(
            {
                "message": "Customer is now inactive. Their history is unchanged.",
                "deactivated": retired,
            },
            status=status.HTTP_200_OK,
        )

    def _deactivate(self, customer, *, cascade):
        """Retire `customer`, and the subtree when asked. Returns how many.

        Depth-first, so a child is retired before its parent and the tree is
        never left with an inactive parent over an active child.
        """
        count = 0
        if cascade:
            for child in active_children(customer):
                count += self._deactivate(child, cascade=True)

        customer.status = CustomerStatusChoices.INACTIVE
        customer.save(update_fields=["status", "updated_at"])
        return count + 1

    def delete(self, request, *args, **kwargs):
        """Reactivate. No preconditions -- nothing was given up on the way in."""
        customer = self.get_object()
        if customer.status != CustomerStatusChoices.INACTIVE:
            raise ValidationError({"message": "This customer is not inactive."})

        customer.status = CustomerStatusChoices.ACTIVE
        customer.save(update_fields=["status", "updated_at"])
        return Response(
            {"message": "Customer is active again."}, status=status.HTTP_200_OK
        )


class PrivateWeCustomerDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCustomerDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_customer"

    def get_object(self):
        return get_object_or_404(
            Customer.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def retrieve(self, request, *args, **kwargs):
        customer = self.get_object()
        if self.request.query_params.get("keywords") == "due_total":
            due_total = Sale.objects.filter(
                customer=customer,
            ).aggregate(due_total=Sum("due_total"))
            return Response(
                {"due_total": due_total["due_total"], "currency": customer.currency}
            )

        serializer = self.get_serializer(customer)
        return Response(serializer.data)

    @transaction.atomic
    def perform_destroy(self, instance):
        """Retire the customer. Touch nothing in the ledger.

        This used to do three other things, and each was a separate fault.

        IT VOIDED THEIR ENTIRE HISTORY. `JournalEntry.objects.filter(
        journalentryconnector__customer=instance).update(status=REMOVED)` marked
        every entry the customer had ever appeared in as removed -- every
        invoice, payment, credit note and refund -- in one bulk update. No
        reversing entry, so no audit trail of what happened or why; and nothing
        sets an entry's status back, so it was not reversible through the API.
        Revenue, tax and cost recognised in closed periods silently vanished from
        every report. The customer row itself was only soft-deleted, so the
        record survived while its accounting history did not -- exactly the wrong
        way round.

        IT MOVED TWO ACCOUNT BALANCES WITH NO JOURNAL ENTRY, which is root cause
        R2: a stored balance moving with no ledger line to explain it. One of the
        two was "Service", an income account with no relationship to a customer's
        receivable. The comment above it read "When deleting a supplier", because
        it was copied from the supplier path.

        AND NEITHER ACCOUNT WAS GUARDED. `get_chart_of_account` returns a dict,
        so a company lacking either name yielded None and
        `update_opening_balance(None, ...)` raised -- a 500 on retiring a
        customer.

        Retiring a customer is a master-data change. It has no accounting
        consequence: their invoices remain valid, their balance remains in A/R,
        and the ageing report still shows them. If a document genuinely should
        not stand, it is voided individually through the document paths, which
        write reversing entries. That is never a side effect of tidying a list.
        """
        instance.status = CustomerStatusChoices.REMOVED
        instance.save()


class PrivateWeCustomerBulkCreate(CreateAPIView):
    serializer_class = PrivateWeCustomerBulkCreateSerializer
    permission_classes = [IsGroupPermission]


class PrivateWeCustomerFileList(ListAPIView):
    serializer_class = PrivateWeCustomerFileListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        kwargs = {
            "uid": self.kwargs.get("uid", None),
            "company": self.request.user.get_active_company(),
        }
        return FileItem.objects.filter(
            id__in=get_object_or_404(Customer, **kwargs)
            .fileitemconnector_set.filter()
            .values_list("file_item_id", flat=True)
        ).exclude(status=FileItemStatusChoices.REMOVED)


class PrivateWeCustomerFileDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCustomerFileListSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        kwargs = {
            "uid": self.kwargs.get("uid", None),
            "company": self.request.user.get_active_company(),
        }
        return get_object_or_404(
            FileItem.objects.filter(
                id__in=get_object_or_404(Customer, **kwargs)
                .fileitemconnector_set.filter()
                .values_list("file_item_id", flat=True)
            ).exclude(status=FileItemStatusChoices.REMOVED),
            uid=self.kwargs.get("file_uid", None),
        )

    def perform_destroy(self, instance):
        instance.status = FileItemStatusChoices.REMOVED
        instance.save_dirty_fields()


class PrivateWeCustomerTransactionList(ListAPIView):
    serializer_class = PrivateWeCustomerTransactionListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DateFromToRangeFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    filterset_fields = [
        "status",
        "is_invoice",
        "is_estimated",
    ]
    search_fields = ["invoice_id"]

    def get_queryset(self):
        customer_uid = self.kwargs.get("uid")
        queryset = Sale.objects.filter(
            customer__uid=customer_uid,
            customer__company=self.request.user.get_active_company(),
        )
        return queryset


class PrivateWeSaleInvoiceListByCustomer(ListAPIView):
    serializer_class = PrivateWeSaleInvoiceListByCustomerSerializer
    permission_classes = [IsGroupPermission]
    def get_queryset(self):
        return (
            Sale.objects.get_status_all()
            .filter(
                company=self.request.user.get_active_company(),
                customer__uid=self.kwargs["uid"],
            )
            .filter(Q(is_invoice=True) | Q(is_estimated=True))
        )


class PrivateWeSaleReceiptsInvoiceListByCustomer(ListAPIView):
    serializer_class = PrivateWeSaleInvoiceListByCustomerSerializer
    permission_classes = [IsGroupPermission]
    def get_queryset(self):
        return (
            Sale.objects.get_status_all()
            .filter(
                company=self.request.user.get_active_company(),
                customer__uid=self.kwargs["uid"],
            )
            .filter(Q(is_invoice=False) & Q(is_estimated=False))
        )
