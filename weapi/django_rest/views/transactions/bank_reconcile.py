from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    get_object_or_404,
    RetrieveAPIView,
)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum

from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from common.django_rest.helpers.ledger_balances import to_natural

from transactionio.django_rest.helpers.reconciliation import (
    candidate_documents,
    reconciled_through,
    cleared_totals,
    reconciliation_difference,
)
from transactionio.models import BankReconciliation, TransactionRules
from weapi.django_rest.serializers.transactions.bank_reconcile import (
    BankReconciliationListCreateSerializer,
    PrivateWeReconciliationUndoSerializer,
    PrivateWeReconciliationLineTickSerializer,
    PrivateWeTransactionMatchSerializer,
    BankReconciliationSummarySerializer,
)


def _with_natural_amount(documents, account):
    """Add each document's movement in the account's own direction.

    Computed here rather than annotated in SQL because the sign depends on the
    account's kind, which is one value for the whole query -- a CASE expression
    over every row would restate a constant.
    """
    rows = list(documents)
    for row in rows:
        row["amount"] = to_natural(row["debit"], row["credit"], account.kind)
    return rows


class PrivateWeBankReconcileListCreateView(ListCreateAPIView):
    """
    List and create bank reconciliations for the authenticated user's active company.

    GET  / — Returns a paginated list of bank reconciliations.
        Supports filtering by bank account, statement ending date, closed status, and creator.
        Supports searching by bank account title, code, beginning balance, and statement ending balance.
        Supports ordering by created_at and statement_ending_date.

    POST / — Creates a new bank reconciliation.
        Required fields:
            - bank_account_uid: UID of an active ChartOfAccount (the bank account being reconciled).
            - beginning_balance: The opening balance of the bank statement.
            - statement_ending_balance: The closing balance on the bank statement.
            - statement_ending_date: The date of the bank statement ending.
        Auto-assigned fields:
            - company: Derived from the authenticated user's active company.
            - created_by: The employee record of the authenticated user.
    """

    serializer_class = BankReconciliationListCreateSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at", "statement_ending_date"]
    filterset_fields = [
        "bank_account__uid",
        "statement_ending_date",
        "status",
        "created_by__uid",
    ]
    search_fields = [
        "bank_account__title",
        "bank_account__code",
        "beginning_balance",
        "statement_ending_balance",
    ]

    def get_queryset(self):
        """Return bank reconciliations scoped to the current user's active company."""
        return BankReconciliation.objects.filter(
            company=self.request.user.get_active_company()
        ).select_related(
            "bank_account",
            "company",
            "created_by",
            "created_by__user",
        )


class PrivateWeReconcileTransactionsView(APIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    # Named explicitly because this view has neither `queryset` nor
    # `serializer_class` for the permission layer to infer a model from, and
    # `_resolve_required_permissions` fails CLOSED on an empty result
    # (`group_permissions.py:85-86`). Without this line every caller who is not
    # a superuser or `is_admin` got a 403 -- and this endpoint is where the
    # entire zero-difference guard lives, so the guard was unreachable in
    # production. Closing a session is a change, hence `change_`.
    required_permissions = ["change_bankreconciliation"]
    """
    Complete (close) a bank reconciliation by marking transactions as matched.

    POST /complete
        Request body:
            - reconciliation_id: UID of the BankReconciliation to close.
            - journal_entry_ids: JournalEntry UIDs to clear against this session.

        Behaviour:
            1. Validates that the reconciliation and all transactions exist.
            2. Ensures every transaction belongs to the same company as the reconciliation.
            3. Atomically clears every ledger leg of those documents on this account.
            4. Moves the reconciliation to CLOSED and records today's date as reconciled_on.

        Returns:
            200 OK with a success message on completion.
    """

    def post(self, request):
        # `context` is not optional: the serializer scopes both the
        # reconciliation and its transactions to the caller's company, and it
        # reads the request to know which company that is.
        serializer = PrivateWeTransactionMatchSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Reconciliation complete."}, status=status.HTTP_200_OK
        )


class PrivateWeReconciliationUndoView(APIView):
    """POST /reconcile/{uid}/undo -- unwind a closed reconciliation.

    Spec s16.7. LIFO: a session with a later statement period still closed on
    the same account blocks this one, and the refusal carries the list of what
    to undo first rather than a count, because a count tells the caller they are
    stuck while a list tells them what to do.
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    # Named explicitly. This view has neither `queryset` nor `serializer_class`
    # for the permission layer to infer a model from, and the resolver fails
    # CLOSED -- the defect that made the close endpoint a 403 for every invited
    # co-worker until `7f4ee89c`.
    required_permissions = ["change_bankreconciliation"]

    def post(self, request, uid):
        serializer = PrivateWeReconciliationUndoSerializer(
            data=request.data, context={"request": request, "uid": uid}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(
            {
                "message": "Reconciliation undone.",
                "released_lines": result["released_lines"],
                "reconciled_through": (
                    reconciled_through(
                        serializer.reconciliation.company,
                        serializer.reconciliation.bank_account,
                    )
                ),
            },
            status=status.HTTP_200_OK,
        )


class PrivateWeReconciliationLineTickView(APIView):
    """POST /reconcile/{uid}/lines -- tick or untick without closing.

    The gap this fills: ticking and closing were one atomic act, so a
    reconciliation could not be saved half-done. A user who ticked forty lines
    and reloaded lost forty ticks, and `/complete` refuses anything that does
    not balance to zero -- so there was no way to record partial progress at
    all.

    Documents, not legs, for the same reason `/complete` takes documents: an
    amended payment has a second leg carrying the delta, and clearing half of an
    amendment is not a thing a user can mean. Send a register row's
    `document_uid`, never its `uid`.

    Body: {"journal_uids": [...], "action": "clear" | "unclear"}
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    # Explicit for the same reason as the sibling views: this one has neither
    # `queryset` nor `serializer_class`, and the resolver fails CLOSED on an
    # empty result. Ticking a line changes the session, hence `change_`.
    required_permissions = ["change_bankreconciliation"]

    def post(self, request, uid):
        serializer = PrivateWeReconciliationLineTickSerializer(
            data=request.data, context={"request": request, "uid": uid}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)


class PrivateWeBankReconciliationSummaryView(RetrieveAPIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"
    # Same reason, different failure. `BankReconciliationSummarySerializer` is a
    # plain `Serializer` with no `Meta`, so the model lookup at
    # `group_permissions.py:55-56` raised `AttributeError` -- which DRF does not
    # convert -- and the request 500'd before the view body ran. Declaring the
    # permission short-circuits that lookup entirely.
    required_permissions = ["view_bankreconciliation"]
    """
    Retrieve a detailed reconciliation summary for a single bank reconciliation.

    GET /summary/<uid>/
        Path parameter:
            - uid: UUID of the BankReconciliation.

        Response data:
            - bank_account: Slim representation of the linked ChartOfAccount.
            - statement_ending_balance / statement_ending_date / beginning_balance: From the reconciliation record.
            - cleared_balance: Cleared movement in the account's own direction.
            - difference: statement_ending_balance − (beginning_balance + deposits − payments).
                          A difference of 0 means the reconciliation is fully balanced.
            - payments_total: Sum of 'spent' across matched transactions up to the statement ending date.
            - deposits_total: Sum of 'received' across matched transactions up to the statement ending date.
            - cleared_documents: Book documents this session has cleared.
            - uncleared_documents: Book documents on this account not yet cleared by any session.
    """

    serializer_class = BankReconciliationSummarySerializer

    def get(self, request, *args, **kwargs):
        recon_uid = kwargs.get("uid")
        company = request.user.get_active_company()

        # Scoped to the caller. Resolving by `uid` alone handed out another
        # tenant's beginning balance, statement balance and date, cleared
        # balance, difference, and both transaction lists in full.
        reconciliation = get_object_or_404(
            BankReconciliation, uid=recon_uid, company=company
        )
        account = reconciliation.bank_account

        # The candidate set is the LEDGER now, not the imported statement.
        # `candidate_documents` carries every scope this needs -- the caller's
        # company, this account, published entries only, nothing dated after the
        # statement -- and groups legs into documents, because an amended
        # payment has two legs here and is one row on a register.
        cleared = _with_natural_amount(
            candidate_documents(reconciliation, cleared=True), account
        )
        uncleared = _with_natural_amount(
            candidate_documents(reconciliation, cleared=False), account
        )

        # Totals. The difference comes from the shared helper rather than being
        # recomputed here: this endpoint's copy was the only one that existed,
        # and the close path -- which never consulted it -- let sessions finish
        # out of balance. One expression now feeds both the figure shown and the
        # rule that gates the close, so they cannot drift.
        debits, credits = cleared_totals(reconciliation)
        difference = reconciliation_difference(reconciliation)

        data = {
            "uid": reconciliation.uid,
            "bank_account": reconciliation.bank_account,
            "statement_ending_balance": reconciliation.statement_ending_balance,
            "statement_ending_date": reconciliation.statement_ending_date,
            "beginning_balance": reconciliation.beginning_balance,
            # In the account's own direction, so a credit card reads correctly.
            "cleared_balance": to_natural(debits, credits, account.kind),
            "difference": difference,
            # Raw sides. For a bank they are payments and deposits; for a credit
            # card the labels invert, which is a presentation matter.
            "payments_total": credits,
            "deposits_total": debits,
            "cleared_documents": cleared,
            "uncleared_documents": uncleared,
        }
        serializer = self.get_serializer(data)
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)
