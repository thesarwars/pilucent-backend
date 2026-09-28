import logging

from django.db import transaction

from django_filters.rest_framework import DjangoFilterBackend
from decimal import Decimal

logger = logging.getLogger(__name__)

from rest_framework.generics import (
    ListCreateAPIView,
    ListAPIView,
    RetrieveDestroyAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework import filters

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer
from fileroomio.models import FileItem

from creditnoteio.models import CreditNote, CreditNoteItem
from creditnoteio.choices import CreditNoteStatusChoices, CreditNoteKindChoices

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.quantity_helpers import update_quantity
from common.django_rest.helpers.balance_helpers import amend_balance, amend_leg
from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from weapi.django_rest.helpers.credit_note_void import (
    assert_credit_not_applied,
    restore_credit_note_inventory,
    restore_party_balance,
    void_credit_note_postings,
)

from journalio.models import JournalEntry
from journalio.django_rest.services.journals import (
    assert_entry_balances,
    reverse_item_connectors,
)
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
)

from ..serializers.creditnotes import (
    PrivateWeCreditNoteListSerializer,
    PrivateWeCreditNoteDetailsSerializer,
    PrivateCreditNoteItemListSerializer,
    PrivateCreditNoteItemDetailsSerializer,
)

from tagio.django_rest.serializers.common import PrivateTagSlimSerializer
from tagio.models import Tag


class PrivateWeCreditNoteList(ListCreateAPIView):
    serializer_class = PrivateWeCreditNoteListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = [
        "uid",
        "date",
        "credit_note_number",
        "customer__first_name",
        "customer__last_name",
        "customer__middle_name",
        "customer__company_name",
        "customer__email",
        "supplier__first_name",
        "supplier__last_name",
        "supplier__middle_name",
        "supplier__display_name",
        "supplier__company_name",
        "supplier__email",
    ]
    ordering_fields = ["created_at"]
    filterset_fields = [
        "status",
        "kind",
        "tax_kind",
        "customer__uid",
        "supplier__uid",
    ]

    def get_queryset(self):
        queryset = CreditNote.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
        return queryset


class PrivateWeCreditNoteDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCreditNoteDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            CreditNote.objects.get_status_all().filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Give back the credit, the stock and the ledger, then retire the note.

        This was the two lines below and nothing else. The note's A/R or A/P leg
        stayed PUBLISHED, so a credit that no longer existed went on reducing
        what a customer owed or what was owed to a supplier; the goods it moved
        stayed moved; and the party balance kept the figure the posting put
        there.

        Three refusals before anything is written, in increasing cost to check:
        a closed reconciliation, a credit somebody has already spent, and stock
        that has since been sold. Inventory is restored before the journal is
        reversed, because inventory is the half that can still refuse once the
        cheap checks have passed -- so nothing is posted unless the stock can
        honestly come back.

        Locked for the same reason the other delete paths lock: the status is
        read here and acted on below, and two concurrent deletes would otherwise
        both pass the check and both reverse.
        """
        note = CreditNote.objects.select_for_update().get(pk=instance.pk)
        if note.status == CreditNoteStatusChoices.REMOVED:
            return

        assert_not_reconciled(
            JournalEntry.objects.filter(credit_note=note), action="delete"
        )
        assert_credit_not_applied(note)

        restore_credit_note_inventory(note)
        _, party_amount = void_credit_note_postings(
            note, created_by=self.request.user.get_employee()
        )
        restore_party_balance(note, party_amount)

        note.status = CreditNoteStatusChoices.REMOVED
        note.save(update_fields=["status"])


class PrivateWeCreditNoteItemsList(ListCreateAPIView):
    serializer_class = PrivateCreditNoteItemListSerializer
    permission_classes = [IsGroupPermission]
    pagination_class = None
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uid"] = self.kwargs.get("uid")
        return context

    def get_queryset(self):
        return (
            get_object_or_404(
                CreditNote.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .creditnoteitem_set.all()
            .select_related("product", "tax")
        )


class PrivateWeCreditNoteItemsDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateCreditNoteItemDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uid"] = self.kwargs.get("uid")
        return context

    def get_object(self):
        return get_object_or_404(
            CreditNoteItem.objects.filter(
                credit_note__uid=self.kwargs["uid"],
                credit_note__company=self.request.user.get_active_company(),
                uid=self.kwargs["item_uid"],
            ).select_related("product", "tax")
        )

    def perform_destroy(self, instance):
        """Remove a line, and everything it put in the ledger.

        This used to reverse a hand-picked list of accounts -- income, product
        asset and cost of sales for a sale line; inventory and the charter
        account for a purchase line -- then delete the line. Two things were
        wrong with that.

        Any leg on an account outside that list was never reversed, and the
        CASCADE on `JournalEntryConnector.credit_note_item` deleted it silently
        when the line went, so the stored balance kept a movement whose ledger
        line no longer existed. The list cannot be right in general: which
        accounts a line touches depends on the product's configuration, its tax
        groups and what the request supplied. `reverse_item_connectors`
        enumerates the legs that actually exist instead, and derives each undo
        from the leg's own stored kind -- so it also unwinds rows written before
        the sides were corrected, which a hard-coded undo gets backwards.

        The header leg was never touched at all. A credit note posts its
        receivable (or payable) once for the whole document, so removing a line
        left it at its original figure while the line's own legs disappeared --
        the entry permanently short by exactly the line total, with
        `journal_entry.amount` decremented so the header still looked right.
        """
        credit_note = instance.credit_note
        line_total = Decimal(str(instance.total or 0))

        journal_entry = JournalEntry.objects.filter(
            credit_note=credit_note, kind=JournalEntryKindChoices.CREDIT_NOTE
        ).first()

        if journal_entry:
            reverse_item_connectors(
                journal_entry.journalentryconnector_set.filter(
                    credit_note_item=instance
                )
            )

            # Bring the header leg down with it. A sale credit note CREDITS the
            # receivable and a vendor credit DEBITS the payable, so each shrinks
            # toward zero as lines are removed.
            if credit_note.kind == CreditNoteKindChoices.SALE:
                header_title = "Accounts Receivable (A/R)"
                header_side = JournalEntryConnectorKindChoices.CREDIT
            else:
                header_title = "Accounts Payable (A/P)"
                header_side = JournalEntryConnectorKindChoices.DEBIT

            header_account = get_chart_of_account(
                [header_title], credit_note.company
            ).get(header_title)

            header_leg = (
                journal_entry.journalentryconnector_set.filter(
                    account=header_account, credit_note_item__isnull=True
                ).first()
                if header_account
                else None
            )

            if header_leg is not None:
                posted = Decimal(
                    str(header_leg.debit if header_leg.debit else header_leg.credit)
                )
                remaining = posted - line_total

                if remaining <= 0:
                    # The last line, or one whose total exceeds the header.
                    # Unwind the leg rather than leave a negative one.
                    reverse_item_connectors(
                        journal_entry.journalentryconnector_set.filter(
                            pk=header_leg.pk
                        )
                    )
                else:
                    amend_leg(header_account, header_side, remaining, posted)
                    if header_side == JournalEntryConnectorKindChoices.DEBIT:
                        header_leg.debit, header_leg.credit = remaining, 0
                    else:
                        header_leg.credit, header_leg.debit = remaining, 0
                    header_leg.total = remaining
                    header_leg.last_balance = header_account.opening_balance
                    header_leg.save_dirty_fields()
            elif header_account is not None:
                logger.warning(
                    "credit note %s: removing line %s, but the entry carries no "
                    "header leg on %s to reduce. The entry will not balance.",
                    credit_note.pk, instance.pk, header_title,
                )

            # The party's own balance moves with the control account, or the
            # two diverge. `create` does `update_opening_balance(customer,
            # "debit", total, 0)` alongside the A/R leg, so a line coming off
            # has to give that back -- otherwise A/R reports one figure and the
            # sum of customer balances reports another.
            #
            # This was missed when the header-leg reduction landed: that fix
            # replaced an unbalanced entry with a balanced one, but left the
            # subledger stale, which is a quieter fault of the same kind.
            party = (
                credit_note.customer
                if credit_note.kind == CreditNoteKindChoices.SALE
                else credit_note.supplier
            )
            if party is not None and line_total:
                note_total = Decimal(str(credit_note.total or 0))
                amend_balance(
                    party,
                    JournalEntryConnectorKindChoices.DEBIT,
                    note_total - line_total,
                    note_total,
                )

            journal_entry.amount = journal_entry.amount - line_total
            journal_entry.save()

            assert_entry_balances(journal_entry)

        # Delete the instance
        instance.delete()


class PrivateWeCreditNoteTagsList(ListAPIView):
    serializer_class = PrivateTagSlimSerializer
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
        return Tag.objects.filter(
            id__in=(
                get_object_or_404(
                    CreditNote.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )


class PrivateWeCreditNoteFileItemList(ListCreateAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = ["uid", "title"]
    ordering_fields = ["created_at"]
    filterset_fields = ["status"]

    def get_queryset(self):
        return FileItem.objects.filter(
            id__in=(
                get_object_or_404(
                    CreditNote.objects.get_status_all().filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.CREDIT_NOTE
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWeCreditNoteFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [IsGroupPermission]

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                CreditNote.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.CREDIT_NOTE_ITEM,
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
