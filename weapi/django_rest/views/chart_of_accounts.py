from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from django.db import transaction
from django.db.models import Prefetch

from common.django_rest.helpers.account_references import (
    active_children,
    blocking_references,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money

from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    LedgerAmountRangeFilter,
    LedgerDateRangeFilter,
    ReconciliationStatusFilter,
)
from common.django_rest.permissions.company_subscription import HaveSubscription

from journalio.choices import JournalEntryStatusChoices
from journalio.models import JournalEntryConnector
from common.django_rest.helpers.ledger_balances import ledger_balance_subquery

from ..serializers.chart_of_accounts import (
    PrivateWeChartOfAccountListSerializer,
    PrivateWeChartOfAccountDetailsSerializer,
    PrivateWeChartOfAccountTreeSerializer,
    PrivateWeChartOfAccountSessionListSerializer,
    PrivateWeTransactedChartOfAccountSerializer,
)

from accounts.filters import ChartOfAccountFilter


# Every view in this file that names `required_permissions` does so because it
# has neither `queryset` nor `serializer_class` for the permission layer to
# infer a model from. `_resolve_required_permissions` returns [] in that case
# and `HasCompanyPermission.has_permission` fails CLOSED, so the endpoint was a
# 403 for every user who is not a superuser or `is_admin` -- which is every
# invited co-worker and every employee, the exact population the roles exist
# for. Same defect as the reconciliation endpoints (`7f4ee89c`).

class PrivateWeChartOfAccountList(ListCreateAPIView):
    serializer_class = PrivateWeChartOfAccountListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_chart_of_account"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    search_fields = [
        "uid",
        "title",
        "account_type__uid",
        "account_type__slug",
        "detail_type__uid",
        "detail_type__slug",
        "account_type__title",
        "detail_type__title",
        "kind",
    ]
    filterset_class = ChartOfAccountFilter

    # `?tranjacted=true` picked the serializer while `?transacted=true` filtered
    # the queryset, so a caller sending either got half the feature and no error:
    # the right serializer over an unfiltered list, or the right list rendered by
    # the wrong serializer. Both spellings now mean the same thing, and the
    # misspelling stays accepted because clients send it.
    TRANSACTED_PARAMS = ("transacted", "tranjacted")

    def _wants_transacted(self):
        return any(
            self.request.query_params.get(name) == "true"
            for name in self.TRANSACTED_PARAMS
        )

    def get_serializer_class(self):
        return (
            PrivateWeTransactedChartOfAccountSerializer
            if self._wants_transacted()
            else super().get_serializer_class()
        )

    def get_queryset(self):
        queryset = ChartOfAccount.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )
        
        # Transacted CAO
        if self._wants_transacted():
            start_date = self.request.query_params.get("start_date")
            end_date = self.request.query_params.get("end_date")
            queryset = queryset.filter(
                journalentryconnector__isnull=False,
            ).distinct()

            if start_date and end_date:
                queryset = queryset.filter(
                    journalentryconnector__created_at__range=[start_date, end_date]
                )
        return queryset


class PrivateWeChartOfAccountDeactivate(APIView):
    """Retire an account from data entry without touching the books.

    The state two shipped error messages already tell users to reach for: the
    control-account delete refusal says "Make it inactive instead", and the 409
    on deleting an account with history says "Deactivate it instead". Neither
    had anywhere to send them -- `FRONTEND_INSTRUCTIONS_COA.md` s5 currently has
    to tell the frontend not to build the button.

    POST   /we/chart-of-accounts/{uid}/deactivate     make inactive
    DELETE /we/chart-of-accounts/{uid}/deactivate     make active again

    Three preconditions, per spec BLZ-FIN-COA-SPEC-001 s9.4, each refusing with
    its own code so the client can act on it rather than show a sentence:

    * **COA-150** the balance must be zero. The spec offers an adjusting journal
      to Opening Balance Equity as an alternative; that is not built here --
      writing a journal entry as a side effect of a status change deserves its
      own decision, and refusing is the safe half.
    * **COA-151** nothing may still *map* to it. History does not count and must
      not: an inactive account keeps every document it ever appeared on. See
      `account_references.py` for why the 40 reverse relations split 18/22.
    * **COA-152** sub-accounts must be retired first, or `cascade=true`.

    A control account (`is_fixed`) is refused outright. The ledger resolves it by
    `system_key` and would keep posting to it, so hiding it from pickers would
    make the chart lie rather than make the account safe.
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_chart_of_account"
    required_permissions = ["change_chartofaccount"]

    def get_object(self):
        return get_object_or_404(
            self.request.user.get_active_company().chartofaccount_set.filter(
                uid=self.kwargs.get("uid")
            )
        )

    def post(self, request, *args, **kwargs):
        account = self.get_object()
        cascade = str(request.data.get("cascade", "")).lower() in ("true", "1", "yes")

        # Keyed off `system_key`, NOT `is_fixed`. The two are meant to describe
        # the same twelve accounts and do not: seeding stamps `is_fixed=True` on
        # every row it creates, so 3,573 of 3,759 live accounts carry it while
        # only 780 are control accounts. Refusing on `is_fixed` refused
        # "Cash on Hand", "Savings Account" and "Equipment & Machinery" -- and
        # left this endpoint usable on 4% of the chart.
        #
        # `system_key` is the honest test: it is what `get_chart_of_account()`
        # resolves, so it names exactly the accounts that would keep receiving
        # entries after being hidden.
        if account.system_key:
            raise ValidationError(
                {
                    "code": "COA-153",
                    "message": (
                        "This is a control account the ledger posts to. Making "
                        "it inactive would hide it while it kept receiving "
                        "entries."
                    ),
                }
            )

        if account.status == ChartOfAccountStatusChoices.INACTIVE:
            return Response(
                {"message": "This account is already inactive."},
                status=status.HTTP_200_OK,
            )

        balance = quantize_money(account.opening_balance or 0)
        if balance:
            raise ValidationError(
                {
                    "code": "COA-150",
                    "message": (
                        f"This account still holds a balance of {balance}. "
                        "Move it to another account first; an inactive account "
                        "keeps its balance and would carry that figure out of "
                        "sight."
                    ),
                    "balance": str(balance),
                }
            )

        references = blocking_references(account)
        if references:
            raise ValidationError(
                {
                    "code": "COA-151",
                    "message": (
                        f"{sum(r['count'] for r in references)} setting(s) still "
                        "use this account. Point them somewhere else first."
                    ),
                    "references": references,
                }
            )

        children = list(active_children(account))
        if children and not cascade:
            raise ValidationError(
                {
                    "code": "COA-152",
                    "message": (
                        f"This account has {len(children)} active sub-account(s). "
                        "Deactivate them first, or resend with cascade to "
                        "deactivate the whole subtree."
                    ),
                    "children": [
                        {"uid": str(c.uid), "title": c.title} for c in children
                    ],
                }
            )

        with transaction.atomic():
            retired = self._deactivate(account, cascade=cascade)

        return Response(
            {
                "message": f"{account.title} is now inactive.",
                "deactivated": retired,
            },
            status=status.HTTP_200_OK,
        )

    def _deactivate(self, account, *, cascade):
        """Retire `account`, and its subtree when asked. Returns how many.

        Depth-first so a child is retired before its parent, which keeps the
        tree valid at every step -- an inactive parent over an active child is
        the orphan state COA-152 exists to avoid.
        """
        count = 0
        if cascade:
            for child in active_children(account):
                count += self._deactivate(child, cascade=True)

        account.status = ChartOfAccountStatusChoices.INACTIVE
        account.save(update_fields=["status", "updated_at"])
        return count + 1

    def delete(self, request, *args, **kwargs):
        """Reactivate. Single action, no preconditions -- s9.4.5.

        Nothing to check: the account kept its number the whole time, so
        uniqueness cannot have been taken in the meantime.
        """
        account = self.get_object()
        if account.status != ChartOfAccountStatusChoices.INACTIVE:
            raise ValidationError(
                {"message": "This account is not inactive."}
            )

        account.status = ChartOfAccountStatusChoices.ACTIVE
        account.save(update_fields=["status", "updated_at"])
        return Response(
            {"message": f"{account.title} is active again."},
            status=status.HTTP_200_OK,
        )


class PrivateWeChartOfAccountDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeChartOfAccountDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_chart_of_account"

    def get_object(self):
        return get_object_or_404(
            self.request.user.get_active_company().chartofaccount_set.filter(
                uid=self.kwargs.get("uid")
            )
        )

    def perform_destroy(self, instance):
        """Retire an account, unless it is one the ledger depends on.

        `perform_destroy` does not run the serializer, so the `is_fixed` guard in
        `PrivateWeChartOfAccountDetailsSerializer.validate` never fired here. A
        control account -- Accounts Receivable, Accounts Payable, Opening Balance
        Equity -- could be removed through DELETE while the serializer refused
        every other kind of change to it.

        The delete is soft and `JournalEntryConnector.account` is PROTECT, so the
        history survived. The damage was the interaction: `get_chart_of_account`
        excludes REMOVED, so posting stopped resolving the account, and restoring
        it meant PATCHing `status` back -- which `is_fixed` blocks. A control
        account could be removed and then could not be put back through the API
        at all.

        **The remaining preconditions arrived later, and separately.** The gap
        analysis specified the `is_fixed` guard *and* a journal-history check;
        only the first shipped, and its coverage hid the omission -- seeding
        marks nearly every account `is_fixed`, so the accounts that could reach
        the rest of this method were the few a tenant had made themselves. The
        checks below are what the specification asks of delete (s9.5: "zero
        postings ever, no children, no references"), and what deactivation has
        enforced since it existed.
        """
        if instance.is_fixed:
            raise ValidationError(
                {
                    "message": (
                        "This is a control account the ledger posts to and "
                        "cannot be deleted. Make it inactive instead if you do "
                        "not want it offered."
                    )
                }
            )

        if ChartOfAccount.objects.get_status_all().filter(parent=instance).exists():
            raise ValidationError(
                {
                    "message": "This account cannot be deleted as it is being used as a parent account."
                }
            )

        # Spec s9.5: delete is for hygiene only -- "allowed when the account has
        # zero postings ever, no children, no references, and is not a system
        # account. Everything else is soft-only through deactivation."
        #
        # None of the following was checked. `is_fixed` above was the only real
        # gate, and it happens to cover most of the chart because seeding sets
        # it on every row -- so the gap stayed hidden. Where it does not cover,
        # an account holding posted history could be removed outright: the
        # `JournalEntryConnector` rows survive (the FK is PROTECT), but PROTECT
        # guards a HARD delete and this is a status flip, so it never fires.
        # `get_status_all()` then drops the account from the balance sheet while
        # its lines stay in the ledger, and the statement stops balancing with
        # nothing raising anywhere.
        #
        # These refuse rather than cascade, and every message names deactivation
        # -- which now exists, enforces the same three preconditions, and is the
        # correct destination for an account with a past.
        if instance.has_journal_lines():
            raise ValidationError(
                {
                    "code": "COA-154",
                    "message": (
                        "This account has posted entries and cannot be deleted; "
                        "removing it would take its balance off the reports "
                        "while its journal lines stayed in the ledger. Make it "
                        "inactive instead — it keeps its history and stops "
                        "being offered on new documents."
                    ),
                }
            )

        balance = quantize_money(instance.opening_balance or 0)
        if balance:
            raise ValidationError(
                {
                    "code": "COA-150",
                    "message": (
                        f"This account still holds a balance of {balance}. Move "
                        f"it to another account first."
                    ),
                    "balance": str(balance),
                }
            )

        references = blocking_references(instance)
        if references:
            raise ValidationError(
                {
                    "code": "COA-151",
                    "message": (
                        f"{sum(r['count'] for r in references)} setting(s) still "
                        "use this account. Point them somewhere else first."
                    ),
                    "references": references,
                }
            )

        instance.status = ChartOfAccountStatusChoices.REMOVED
        instance.save()


class ChartOfAccountTreeView(ListAPIView):
    serializer_class = PrivateWeChartOfAccountTreeSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_chart_of_account_tree"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    search_fields = ["uid", "title", "account_type__uid", "detail_type__uid", "kind"]
    filterset_fields = ["status", "account_type__uid", "detail_type__uid", "kind"]

    def get_queryset(self):
        return ChartOfAccount.objects.get_status_all().filter(
            company=self.request.user.get_active_company(), parent__isnull=True
        )


class PrivateWeChartOfAccountSessionList(ListAPIView):
    serializer_class = PrivateWeChartOfAccountSessionListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    # This is an account's own history, so it is guarded as the account is.
    #
    # Without an explicit list, `_resolve_required_permissions` infers the
    # codename from `serializer_class.Meta.model` -- here `JournalEntryConnector`
    # -- and asked for `view_journalentryconnector`. That codename is granted by
    # no role, seed or catalogue entry anywhere in the repo, and the resolver
    # fails closed, so the register was a 403 for every user who is not a
    # superuser or `is_admin`: every invited co-worker, which is the population
    # roles exist for. It was not even discoverable in the role builder, whose
    # menu shows model permissions by name -- nobody picks
    # "journal entry connector" to grant a Bank Register.
    #
    # `view_chartofaccount` is what the feature catalogue already declares for
    # both chart-of-account features (`subscriptionio/feature_catalog.py:19,26`),
    # and it is the permission the account header beside this grid requires. If
    # you can see the account, you can see what it did.
    required_permissions = ["view_chartofaccount"]
    # Was `is_chart_of_account_tree`, copy-pasted from `ChartOfAccountTreeView`.
    # The tree is a different feature; a plan carrying Chart of Accounts but not
    # the tree rendered the account header and 403'd the register under it.
    required_feature = "is_chart_of_account"
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        LedgerDateRangeFilter,
        LedgerAmountRangeFilter,
        ReconciliationStatusFilter,
    ]
    # `title` was in this list and is a real column -- inherited from
    # BaseModelWithUID -- which is why it never raised. Nothing has ever written
    # it on a journal leg, so searching matched a raw uid or the literal strings
    # DEBIT / CREATED and nothing else: a search box that returned no rows for
    # every memo, payee and reference anyone typed, with a 200 and no error to
    # explain it.
    search_fields = [
        "uid",
        "description",
        "journal__entry_number",
        "journal__description",
        "customer__first_name",
        "customer__last_name",
        "customer__company_name",
        "supplier__first_name",
        "supplier__last_name",
        "supplier__display_name",
        "supplier__company_name",
        "employee__first_name",
        "employee__last_name",
    ]
    filterset_fields = [
        # `kind` here is the POSTING SIDE (DEBIT/CREDIT), not the transaction
        # type -- a long-standing name collision kept for compatibility.
        # `journal__kind` is the Type column's filter.
        "kind",
        "journal__kind",
        "request_kind",
        "journal__uid",
        "supplier__uid",
        "customer__uid",
        "tax__uid",
    ]

    def get_account(self):
        """The account whose register this is, or 404.

        It used to be a filter clause rather than a lookup, so an unknown uid,
        another tenant's uid and an account with no postings were the same
        answer: `200 {"count": 0}`. The account status exclusion went with it --
        a REMOVED or DRAFT account returned an empty register rather than its
        history, and since the API create path never sets a status, every
        API-created account had a permanently empty one.
        """
        if not hasattr(self, "_account"):
            self._account = get_object_or_404(
                ChartOfAccount.objects.all(),
                uid=self.kwargs.get("uid"),
                company=self.request.user.get_active_company(),
            )
        return self._account

    def ledger_queryset(self, account):
        """The lines that are on the books for this account.

        `journal__status` was never filtered here, so soft-deleted entries
        (`perform_destroy` sets REMOVED and reverses nothing) and drafts stayed
        in the register *and* in its running balance. Reconcile takes the
        opposite view -- `candidate_connectors` requires PUBLISHED, "a draft is
        not on the books" -- so the two screens disagreed on which lines exist
        by construction, and no reconciliation could tie out.
        """
        return JournalEntryConnector.objects.filter(
            account=account,
            journal__status=JournalEntryStatusChoices.PUBLISHED,
        )

    def get_serializer_context(self):
        """The register is one account, so its direction is a constant.

        `deposit`/`payment` and the column labels depend on whether a debit
        increases this account. The row carries no account of its own, so
        without this the client is left inferring it -- today by regexing the
        account type title for "credit card".
        """
        context = super().get_serializer_context()
        context["account"] = self.get_account()
        return context

    def get_queryset(self):
        account = self.get_account()
        return (
            self.ledger_queryset(account)
            # The serializer nests journal, customer, supplier and reads
            # employee; without these each is a query per row. The document
            # joins feed the derived Store column, and `reconciliation` feeds
            # the U/C/R status, which reads the session's own state.
            .select_related(
                "account",
                "journal",
                "customer",
                "supplier",
                "employee",
                "reconciliation",
                "journal__sale__warehouse",
                "journal__purchase__warehouse",
                "journal__credit_note__warehouse",
            )
            # The contra account, in one extra query for the whole page rather
            # than one per row. `order_by("id")` is not decoration: the model
            # declares no Meta, so it inherits `ordering = ("-created_at",)`
            # from BaseModelWithUID and a prefetch would sort every sibling set.
            .prefetch_related(
                Prefetch(
                    "journal__journalentryconnector_set",
                    queryset=JournalEntryConnector.objects.select_related(
                        "account"
                    ).order_by("id"),
                    to_attr="sibling_legs",
                )
            )
            .annotate(
                running_balance=ledger_balance_subquery(
                    self.ledger_queryset(account), account.kind
                )
            )
            # Newest first: the register opened on the oldest ten rows, and a
            # four-thousand-line account needed ?page=400 to reach today. Safe
            # to order freely now the balance is a subquery rather than a
            # window -- it no longer depends on the order rows come back in.
            .order_by("-date", "-id")
        )
