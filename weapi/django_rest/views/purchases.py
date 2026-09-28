import logging
from decimal import Decimal

from rest_framework import filters
from rest_framework.exceptions import NotFound
from rest_framework import response

from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django_filters.rest_framework import DjangoFilterBackend
from datetime import date, timedelta
from django.db import transaction
from django.db.models import Count, Q, Sum

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from currencyio.models import CurrencyConnector

from common.django_rest.permissions.company_subscription import HaveSubscription

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.serializers.common import PrivateFileItemSerializer
from fileroomio.models import FileItem

from purchaseio.choices import (
    ExpenseStatusChoices,
    PurchaseStatus,
    PurchaseItemStatus,
    PurchasePaymentStatusChoices,
    PurchasePaymentItemStatusChoices,
    PurchaseItemkind,
)
from purchaseio.django_rest.serializers.common import PrivatePurchaseSlimSerializer
from purchaseio.models import Purchase, Expense, PurchasePayment, ExpenseConnector

from common.django_rest.helpers.quantity_helpers import update_quantity

from ..helpers.expense_posting import void_expense_postings
from ..helpers.purchase_payment_posting import (
    restore_supplier_balance,
    unapply_purchase_payment_items,
    void_purchase_payment_postings,
)

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled

from weapi.django_rest.helpers.purchase_void import (
    assert_bill_not_paid,
    restore_purchase_inventory,
    void_purchase_postings,
)
from weapi.django_rest.helpers.purchase_void import (
    restore_supplier_balance as restore_supplier_balance_for_bill,
)

from journalio.models import JournalEntry

from weapi.django_rest.helpers.purchase_item_helpers import (
    record_purchase_line_movement,
)
from common.django_rest.helpers.balance_helpers import amend_leg

from journalio.models import JournalEntry, JournalEntryConnector
from journalio.django_rest.services.journals import (
    assert_entry_balances,
    reverse_item_connectors,
)
from journalio.choices import (
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
)

from tagio.django_rest.serializers.common import PrivateTagSlimSerializer
from tagio.models import Tag

from ..serializers.purchases import (
    funding_account_for_line_add,
    PrivateWePurchaseListSerializer,
    PrivateWePurchaseDetailsSerializer,
    PrivateWePurchaseItemListSerializer,
    PrivateWePurchaseItemDetailsSerializer,
    PrivateWeExpenseListSerializer,
    PrivateWeExpenseDetailsSerializer,
    PrivateWePurchasePaymentListSerializer,
    PrivateWePurchasePaymentDetailsSerializer,
    PrivateWePurchasePaymentItemListSerializer,
    PrivateWePurchaseSettingDetailsSerializer,
    PrivateWePurchasePaymentItemsDetailsSerializer,
)

logger = logging.getLogger(__name__)


class PrivateWePurchaseList(ListCreateAPIView):
    serializer_class = PrivateWePurchaseListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    filterset_fields = [
        "supplier__uid",
        "bill_date",
        "due_date",
        "is_bill",
        "is_cheque",
        "status",
        "is_via_expense",
    ]
    search_fields = filterset_fields + [
        "title",
        "purchase_id",
        "tracking_number",
        "cheque_number",
        "supplier__first_name",
        "supplier__last_name",
        "supplier__middle_name",
        "supplier__display_name",
        "supplier__company_name",
        "supplier__email",
    ]

    def get_queryset(self):
        queryset = Purchase.objects.filter(
            company=self.request.user.get_active_company()
        )
        currency_uid = self.request.query_params.get("currency__uid")
        if currency_uid:
            queryset = queryset.filter(
                id__in=CurrencyConnector.objects.filter(
                    currency__uid=currency_uid
                ).values_list("purchase_id", flat=True)
            )
        return queryset

    def list(self, request, *args, **kwargs):
        today = date.today()
        two_days_ago = date.today() - timedelta(days=2)
        return (
            response.Response(
                self.get_queryset().aggregate(
                    bill_count=Count(
                        "id",
                        filter=Q(is_bill=True),
                    ),
                    bill_total=Sum(
                        "total",
                        filter=Q(is_bill=True),
                    ),
                    over_due_count=Count(
                        "id",
                        filter=Q(due_date__lt=today),
                    ),
                    over_due_total=Sum(
                        "total",
                        filter=Q(due_date__isnull=False) & Q(due_date__lt=today),
                    ),
                    recently_paid_count=Count(
                        "id",
                        filter=Q(updated_at__lt=two_days_ago)
                        & Q(status=PurchaseStatus.OPEN),
                    ),
                    paid_total=Sum(
                        "total",
                        filter=Q(updated_at__lt=two_days_ago)
                        & Q(status=PurchaseStatus.OPEN),
                    ),
                )
            )
            if request.query_params.get("keywords", None) == "overview"
            else super().list(request, *args, **kwargs)
        )


class PrivateWePurchaseDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePurchaseDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_object(self):
        return get_object_or_404(
            Purchase.objects.filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            ).exclude(status=PurchaseStatus.REMOVED)
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Take back the goods and the ledger, then retire the bill.

        This was the two lines below and nothing else. The A/P leg stayed
        PUBLISHED, so a bill that no longer existed went on saying money was
        owed; the goods stayed received; the cost layer stayed spendable; and
        the supplier's own balance kept the figure the posting put there.

        Three refusals before anything is written, cheapest first: a closed
        reconciliation, a bill something has already paid, and goods that have
        since been sold. A bill sits at the head of two chains -- payments and
        stock -- and neither can be unwound from here without rewriting a second
        posted document, so this refuses more often than it reverses. That is
        the right answer: a bill that has been paid or whose goods have gone is
        history to correct with a new document, not a mistake to erase.

        Inventory is restored before the journal is reversed, because inventory
        is the half that can still refuse once the cheap checks have passed.
        """
        purchase = Purchase.objects.select_for_update().get(pk=instance.pk)
        if purchase.status == PurchaseStatus.REMOVED:
            return

        assert_not_reconciled(
            JournalEntry.objects.filter(purchase=purchase), action="delete"
        )
        assert_bill_not_paid(purchase)

        restore_purchase_inventory(purchase)
        _, supplier_amount = void_purchase_postings(
            purchase, created_by=self.request.user.get_employee()
        )
        restore_supplier_balance_for_bill(purchase, supplier_amount)

        purchase.status = PurchaseStatus.REMOVED
        purchase.save(update_fields=["status"])


class PrivateWePurchaseItemList(ListCreateAPIView):
    serializer_class = PrivateWePurchaseItemListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    pagination_class = None
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status", "kind"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uid"] = self.kwargs.get("uid")
        return context

    def get_queryset(self):
        return (
            get_object_or_404(
                Purchase.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .purchaseitem_set.filter()
            .exclude(status=PurchaseItemStatus.REMOVED)
            .select_related("product", "tax")
        )


class PrivateWePurchaseItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePurchaseItemDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "sku"]
    filterset_fields = ["status", "kind"]

    def get_object(self):
        return get_object_or_404(
            get_object_or_404(
                Purchase.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .purchaseitem_set.filter(
                uid=self.kwargs["item_uid"], status=PurchaseItemStatus.PUBLISHED
            )
            .select_related("product", "tax")
        )

    def perform_destroy(self, instance):
        """Remove a purchase line, and everything it put in the ledger.

        Three things were wrong with the version this replaces.

        IT REVERSED A HAND-PICKED PAIR OF ACCOUNTS -- Inventory Asset for a
        product line, the line's own charter account for an expense line -- then
        deleted the line. A leg on any account outside that pair was never
        reversed, and `JournalEntryConnector.purchase_item` is CASCADE, so the
        row went with the line while the stored balance kept the movement its
        ledger line used to explain. Which accounts a line touches is not a fixed
        list, so `reverse_item_connectors` enumerates the legs that actually
        exist and derives each undo from the leg's own stored kind -- which also
        unwinds rows written before the sides were corrected.

        THE EXPENSE BRANCH SELECTED BY ACCOUNT, NOT BY LINE
        (`filter(account=charter_account)`), reversed `instance.total` once
        however many rows it had matched, and took the direction from
        `.first().kind` -- and `.first()` is the NEWEST row, since ordering is
        `("-created_at",)`. Two lines coded to one account meant deleting either
        one deleted BOTH legs and moved the balance by one line's figure. It is
        scoped to `purchase_item=instance` here, like the product branch.

        THE FUNDING LEG WAS NEVER TOUCHED. A bill credits Accounts Payable, a
        cheque credits the account it is drawn on, an Expense credits the account
        it was paid from -- once, for the whole document. Removing a line deleted
        the line's debit and left that credit at its original figure, so the
        entry was permanently short by exactly the line. Same shape as the
        credit-note fix in 33f27fb8.

        The funding reduction is sized from the LEDGER, not from `instance.total`:
        the debits actually removed, less any credits removed. A line whose legs
        were amended after posting therefore unwinds by what is really there, and
        a line with no legs of its own does not have the funding leg pulled out
        from under legs that are still standing -- which matters today, because
        expense lines are still posted untagged.
        """
        product = instance.product
        purchase = instance.purchase
        company = self.request.user.get_active_company()

        posted_entries = self._posted_entries(purchase, company)

        # Before the first mutating statement. This method deletes the line's
        # own legs and then deletes or shrinks the document's funding leg --
        # which for a cheque or an expense-funded purchase is the bank leg.
        #
        # `_posted_entries` yields `(entry, funding_accounts)` pairs, not
        # entries, so the guard takes the first half of each.
        assert_not_reconciled(
            [entry for entry, _accounts in posted_entries], action="delete"
        )

        # Stock came in once per line, so it goes back out once. A bill later
        # paid through an Expense has two entries and the Expense create adds the
        # quantity a second time, so deducting per entry would cancel that
        # double-add by accident and over-deduct the moment it is fixed. One
        # deduction leaves that overstatement exactly as it already was.
        if product and instance.kind == PurchaseItemkind.PRODUCT and posted_entries:
            update_quantity(
                product,
                "deduction",
                instance.quantity,
                0,
            )

            # And take the units off the ledger too, from the layer this line
            # created. Deleting a bill line removed the stock and left its cost
            # layer standing, so the goods could still be "sold" at a price from
            # a document that no longer exists.
            record_purchase_line_movement(
                purchase, instance, product, instance.quantity,
                inbound=False, unit_cost=instance.purchase_price,
                note="Reversed by deleting this line.",
            )

        for journal_entry, funding_accounts in posted_entries:
            line_legs = journal_entry.journalentryconnector_set.filter(
                purchase_item=instance
            )
            posted_totals = line_legs.aggregate(
                debit=Sum("debit"), credit=Sum("credit")
            )
            removed_debit = Decimal(str(posted_totals["debit"] or 0))
            removed_credit = Decimal(str(posted_totals["credit"] or 0))

            reversed_legs = reverse_item_connectors(line_legs)

            if not reversed_legs:
                logger.warning(
                    "purchase %s: line %s has no legs of its own in entry %s, so "
                    "nothing was reversed and the funding leg was left alone. "
                    "Expense lines are still posted untagged -- serializers/"
                    "purchases.py:428, :1632, :2178 pass a 5-tuple, so "
                    "`purchase_item` is never set -- and their cost leg outlives "
                    "the line.",
                    purchase.pk,
                    instance.pk,
                    journal_entry.pk,
                )

            # What the entry is now short by on the debit side.
            shortfall = removed_debit - removed_credit
            taken = Decimal("0")

            if shortfall > 0:
                taken = self._reduce_funding_legs(
                    journal_entry, funding_accounts, shortfall, instance
                )
            elif shortfall < 0:
                logger.warning(
                    "purchase %s: line %s took a net CREDIT of %s out of entry "
                    "%s. A purchase line debits, so this entry was already the "
                    "wrong way round; the funding leg was left alone.",
                    purchase.pk,
                    instance.pk,
                    -shortfall,
                    journal_entry.pk,
                )

            # Moved with the legs, never ahead of them: `amount` reading right
            # while the legs behind it did not is what made the credit-note
            # version of this bug invisible.
            if taken:
                journal_entry.amount = max(
                    Decimal("0"),
                    Decimal(str(journal_entry.amount or 0)) - taken,
                )
                journal_entry.save()

            assert_entry_balances(journal_entry)

        self._detach_foreign_legs(instance, [entry.pk for entry, _ in posted_entries])

        instance.delete()

    def _posted_entries(self, purchase, company):
        """Every entry this document posted, each with the accounts funding it.

        Not one entry. `is_bill` / `is_cheque` and `is_via_expense` are not
        exclusive: paying a bill through an Expense sets `is_via_expense` and
        leaves `is_bill` True (the closing `purchases.update(...)` of the Expense
        create in serializers/purchases.py), so the line has legs in the bill's
        PURCHASE entry AND in the EXPENSE entry. The `if/elif` this replaces saw
        the Expense entry only and left the bill's legs to the CASCADE.

        Every funding account listed is demonstrably posted, in order:

        * bill -- CREDIT Accounts Payable for the unpaid part, and CREDIT the
          account named on the document for a deposit;
        * cheque -- CREDIT the account it is drawn on, which is that same
          `purchase.charter_account`;
        * Expense -- CREDIT `expense.payment_account`, once per purchase covered.

        `funding_account_for_line_add` is reused on purpose: it is the account the
        add-a-line path credits, so a line is unwound by the same rule that
        posted it, from a single definition.
        """
        entries = []

        if purchase.is_bill or purchase.is_cheque:
            entry = (
                JournalEntry.objects.filter(
                    purchase=purchase,
                    kind=(
                        JournalEntryKindChoices.CHEQUE
                        if purchase.is_cheque
                        else JournalEntryKindChoices.PURCHASE
                    ),
                    company=company,
                )
                .select_related("purchase")
                .first()
            )
            if entry:
                entries.append(
                    (
                        entry,
                        self._unique_accounts(
                            [
                                funding_account_for_line_add(purchase, company),
                                # The deposit leg, when the bill was part-paid on
                                # creation. Absent on a bill with no deposit, in
                                # which case there is simply no leg to find.
                                purchase.charter_account,
                            ]
                        ),
                    )
                )

        if purchase.is_via_expense:
            expense_connector = ExpenseConnector.objects.filter(
                purchase=purchase
            ).first()
            entry = (
                JournalEntry.objects.filter(
                    expense=expense_connector.expense,
                    kind=JournalEntryKindChoices.EXPENSE,
                    company=company,
                )
                .select_related("expense")
                .first()
                if expense_connector
                else None
            )
            if entry:
                entries.append(
                    (
                        entry,
                        self._unique_accounts(
                            [
                                getattr(entry.expense, "payment_account", None),
                                # A line added after the conversion credited the
                                # BILL's funding account into this same entry --
                                # `funding_account_for_line_add` tests `is_bill`
                                # first -- so that leg can be here too.
                                funding_account_for_line_add(purchase, company),
                            ]
                        ),
                    )
                )

        return entries

    def _unique_accounts(self, accounts):
        """The accounts that exist, in the order given, without repeats."""
        seen = set()
        unique = []
        for account in accounts:
            if account is None or account.pk in seen:
                continue
            seen.add(account.pk)
            unique.append(account)
        return unique

    def _reduce_funding_legs(
        self, journal_entry, funding_accounts, shortfall, instance
    ):
        """Bring the document's funding leg down by what the line took with it.

        Returns the amount actually taken off.

        A bill / cheque / Expense credits what it owes or paid ONCE for the whole
        document, so removing a line has to shrink that credit or the entry is
        left short by exactly the line. A document can carry more than one such
        leg -- a bill with a deposit credits A/P for the unpaid part and the bank
        for the deposit, and every line added after the document posted appended
        a funding leg of its own -- so this takes what it can from each in turn.
        A leg the reduction covers whole is unwound rather than left at zero,
        which is what removing the last line of a document does.

        Only CREDIT-side untagged legs are eligible. The side is read off the
        money COLUMN, which IS the accounting side and needs no kind lookup.
        Untagged, so another line's own leg can never be taken. And no fallback
        to the debit side, for two reasons: an expense line coded to the funding
        account leaves an unrelated DEBIT leg there, and reducing that would
        deepen the shortfall instead of closing it; while a funding leg that
        really did post as a debit belongs to an entry that was born unbalanced
        (pre-fix, funded from a credit card), which taking more off the same side
        cannot repair.

        Legs on one account and one side are interchangeable for both the entry
        and the account's balance -- the connector records no purchase -- so
        largest-first is arbitrary but deterministic, and touches fewest rows.
        """
        residual = shortfall
        taken = Decimal("0")

        for account in funding_accounts:
            if residual <= 0:
                break

            candidates = [
                leg
                for leg in journal_entry.journalentryconnector_set.filter(
                    account=account, purchase_item__isnull=True
                )
                if leg.credit
            ]
            candidates.sort(key=lambda leg: Decimal(str(leg.credit)), reverse=True)

            for leg in candidates:
                if residual <= 0:
                    break

                posted = Decimal(str(leg.credit))
                take = posted if posted <= residual else residual

                if take >= posted:
                    # Nothing left to reduce: the last line, or one that covers
                    # this leg whole. Unwind the leg instead of leaving an empty
                    # or negative one behind.
                    reverse_item_connectors(
                        journal_entry.journalentryconnector_set.filter(pk=leg.pk)
                    )
                else:
                    remaining = posted - take
                    # `amend_leg` moves the stored balance by the DELTA in the
                    # direction that shrinks a credit leg, derived from the
                    # account's kind -- the same rule the posting used.
                    amend_leg(
                        account,
                        JournalEntryConnectorKindChoices.CREDIT,
                        remaining,
                        posted,
                    )
                    leg.credit = remaining
                    leg.debit = 0
                    leg.total = remaining
                    leg.last_balance = account.opening_balance
                    leg.save_dirty_fields()

                residual -= take
                taken += take

        if residual > 0:
            logger.warning(
                "purchase %s: entry %s has no funding leg left to reduce for "
                "line %s -- %s stands unmatched, so the entry will not balance. "
                "Accounts offered: %s.",
                instance.purchase_id,
                journal_entry.pk,
                instance.pk,
                residual,
                [account.title for account in funding_accounts] or "none",
            )

        return taken

    def _detach_foreign_legs(self, instance, handled_entry_pks):
        """Keep the CASCADE from taking another document's legs with this line.

        `JournalEntryConnector.purchase_item` is CASCADE (journalio/models.py),
        and the SALE side writes it: a sale's cost-of-sales debit and its
        inventory-relief credit record the FIFO layer they consumed, which is a
        purchase line (`as_purchase_item`, used by
        weapi/django_rest/helpers/sale_posting.py and by the invoice / sales
        receipt importers, which tag the revenue leg with it too). Those rows sit
        in SALE, SALE_RECEPT and REFUND_RECEIPT entries this view never looks at,
        so deleting the line removed them unreversed -- the sale's accounts kept
        movements with no ledger line behind them, and an imported invoice was
        left as a lone receivable debit.

        They are NOT reversed here. They belong to the sale: reversing them would
        take a sale's cost of goods out of the books because a purchase line was
        removed. Clearing the pointer keeps the rows and their entries whole --
        it is provenance only, and `stockio` already holds the same link as
        SET_NULL. A line whose stock has been sold is arguably a delete that
        should be refused outright; until it is, this at least does not destroy
        the sale, and it says so.
        """
        foreign = JournalEntryConnector.objects.filter(
            purchase_item=instance
        ).exclude(journal_id__in=handled_entry_pks)

        entry_pks = sorted(set(foreign.values_list("journal_id", flat=True)))
        if not entry_pks:
            return 0

        detached = foreign.update(purchase_item=None)
        logger.error(
            "purchase line %s is cited by %s leg(s) in entries %s that this "
            "document did not post -- FIFO layer provenance on sale-side "
            "entries. The pointer was cleared so the CASCADE cannot delete "
            "them, but stock this line brought in has been sold and the line "
            "is going.",
            instance.pk,
            detached,
            entry_pks,
        )
        return detached


class PrivateWePurchaseTagList(ListAPIView):
    serializer_class = PrivateTagSlimSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
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
                    Purchase.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )


class PrivateWePurchaseFileItemList(ListAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title"]
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return FileItem.objects.filter(
            id__in=(
                get_object_or_404(
                    Purchase.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.PURCHASE
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWePurchaseFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                Purchase.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.PURCHASE,
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


class PrivateWeExpenseList(ListCreateAPIView):
    serializer_class = PrivateWeExpenseListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "reference_number", "date"]
    filterset_fields = ["supplier__uid"]

    def get_queryset(self):
        return Expense.objects.filter(
            supplier__company=self.request.user.get_active_company()
        )


class PrivateWeExpenseDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeExpenseDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_object(self):
        # REMOVED is excluded, as every sibling detail view already does.
        # Without it a retired expense stayed fetchable and PATCHable, and
        # since `perform_destroy` began posting a reversal there are now TWO
        # entries under `expense=` with the same kind -- so an amend on a
        # deleted expense could pick up the reversal and rewrite that instead.
        return get_object_or_404(
            Expense.objects.filter(
                supplier__company=self.request.user.get_active_company(),
                uid=self.kwargs["uid"],
            ).exclude(status=ExpenseStatusChoices.REMOVED)
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Reverse what the expense posted, then retire it. Never erase it.

        There was no `perform_destroy` here at all, so DRF ran
        `instance.delete()`. `JournalEntry.expense` is CASCADE and
        `JournalEntryConnector.journal` is CASCADE, so that took the entry and
        every leg with it -- while leaving every `opening_balance` those legs had
        moved exactly where it was. Deleting an expense silently dropped its
        cost and its funding out of the register and out of every report, moved
        no balance back, and left nothing behind to say it had happened.

        Every sibling document already soft-deletes. This one could not: it had
        no `perform_destroy` to do it in.
        """
        if instance.status == ExpenseStatusChoices.REMOVED:
            return
        void_expense_postings(
            instance, created_by=self.request.user.get_employee()
        )
        instance.status = ExpenseStatusChoices.REMOVED
        instance.save(update_fields=["status"])


class PrivateWeExpenseItemList(ListAPIView):
    serializer_class = PrivatePurchaseSlimSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_queryset(self):
        # `Expense` carries no company column, so the expense itself cannot be
        # scoped directly -- any uid resolves. The purchases it fans out to are
        # scoped instead, which is what the endpoint actually returns.
        #
        # Purchase is RLS-protected, so this was not leaking rows; but that
        # policy is permissive when the request carries no company claim, and a
        # filter that only the database enforces is one deployment change away
        # from being no filter at all.
        company = self.request.user.get_active_company()
        purchase_ids = get_object_or_404(
            Expense.objects.filter(uid=self.kwargs["uid"])
        ).expenseconnector_set.values_list("purchase_id", flat=True)
        return Purchase.objects.filter(id__in=purchase_ids, company=company)


class PrivateWePurchasePaymentList(ListCreateAPIView):
    serializer_class = PrivateWePurchasePaymentListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = [
        "bill_number",
        "supplier__first_name",
        "supplier__last_name",
        "supplier__display_name",
    ]
    filterset_fields = ["status"]

    def get_queryset(self):
        return PurchasePayment.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWePurchasePaymentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePurchasePaymentDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_object(self):
        return get_object_or_404(
            PurchasePayment.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs["uid"],
            )
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Reverse what the payment did, then retire it.

        This was the two lines below and nothing else. The document vanished
        from its list -- `get_status_all()` excludes REMOVED -- while
        `JournalEntry.status` was untouched, so both legs stayed PUBLISHED and
        the payment stayed in the bank register, in its balance, and in the set
        `/reconcile/complete` offers to tick. The bills it settled stayed
        settled, and the credit notes it consumed stayed consumed.

        Locked for the same reason the reconcile close path locks: the status is
        read here and acted on below, and two concurrent deletes would otherwise
        both pass the check and both reverse.
        """
        payment = PurchasePayment.objects.select_for_update().get(pk=instance.pk)
        if payment.status == PurchasePaymentStatusChoices.REMOVED:
            return

        assert_not_reconciled(
            JournalEntry.objects.filter(purchase_payment=payment), action="delete"
        )

        _, supplier_amount = void_purchase_payment_postings(
            payment, created_by=self.request.user.get_employee()
        )
        restore_supplier_balance(payment, supplier_amount)
        unapply_purchase_payment_items(payment)

        payment.status = PurchasePaymentStatusChoices.REMOVED
        payment.save(update_fields=["status"])


class PrivateWePurchasePaymentItemsList(ListCreateAPIView):
    serializer_class = PrivateWePurchasePaymentItemListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    pagination_class = None
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["bill_number"]
    filterset_fields = ["status"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["uid"] = self.kwargs.get("uid")
        return context

    def get_queryset(self):
        return (
            get_object_or_404(
                PurchasePayment.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .purchasepaymentitem_set.all()
            .select_related("purchase", "credit_note")
        )


class PrivateWePurchasePaymentItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWePurchasePaymentItemsDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["bill_number"]
    filterset_fields = ["status"]

    def get_object(self):
        return get_object_or_404(
            get_object_or_404(
                PurchasePayment.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .purchasepaymentitem_set.filter(uid=self.kwargs["item_uid"])
            .select_related("purchase", "credit_note")
        )

    def perform_destroy(self, instance):
        instance.status = PurchasePaymentItemStatusChoices.REMOVED
        instance.save()


class PrivateWePurchasePaymentTagList(ListAPIView):
    serializer_class = PrivateTagSlimSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
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
                    PurchasePayment.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                ).tagconnector_set.values_list("tag_id", flat=True)
            )
        )


class PrivateWePurchasePaymentFileItemList(ListAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"
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
                    PurchasePayment.objects.filter(
                        company=self.request.user.get_active_company(),
                        uid=self.kwargs["uid"],
                    )
                )
                .fileitemconnector_set.filter(
                    model_kind=FileItemConnectorModelKindChoices.PURCHASE_PAYMENT
                )
                .values_list("file_item_id", flat=True)
            )
        )


class PrivateWePurchasePaymentFileItemDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateFileItemSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_file_item_connector(self):
        return (
            get_object_or_404(
                PurchasePayment.objects.get_status_all().filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                )
            )
            .fileitemconnector_set.filter(
                model_kind=FileItemConnectorModelKindChoices.PURCHASE_PAYMENT,
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


class PrivateWePurchaseSettingDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWePurchaseSettingDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_expense"

    def get_object(self):
        purchase_setting = self.request.user.get_company_purchase_setting()
        if not purchase_setting:
            raise NotFound(detail="Company not found.")
        return purchase_setting
