from django.db import transaction

from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    SerializerMethodField,
    ValidationError,
    CharField,
)

from accounts.choices import ChartOfAccountStatusChoices, ChartOfAccountKindChoices
from decimal import Decimal

from common.django_rest.helpers.ledger_balances import (
    DerivedRunningBalanceMixin,
    is_debit_natural,
    register_column_labels,
)
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from accounts.models import ChartOfAccount

from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
from categoryio.django_rest.serializers.common import PublicCategorySlimSerializer
from categoryio.models import Category

from common.django_rest.helpers.chart_of_account_helpers import (
    assert_account_identity_is_free,
    assert_parent_is_not_a_cycle,
    derive_account_kind,
    get_chart_of_account,
    validate_detail_type_belongs_to,
)
from common.django_rest.helpers.balance_helpers import (
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)
from common.django_rest.helpers.decorators import set_auditlog_actor

from customerio.django_rest.serializers.common import PrivateCustomerSlimSerializer

from supplierio.models import Supplier

from transactionio.choices import BankReconciliationStatusChoices

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.serializers.common import PrivateJournalEntrySlimSerializer
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry, JournalEntryConnector


def _is_receivable_or_payable(account_type):
    """True when this account type is the A/R or A/P control account.

    Matched on the taxonomy title rather than a system key: the check has to
    fire on an account being CREATED, which has no key yet, and the account type
    is the only thing that identifies what it will be.
    """
    title = (getattr(account_type, "title", "") or "").strip().lower()
    return title in {
        "accounts receivable (a/r)",
        "accounts payable (a/p)",
        "accounts receivable",
        "accounts payable",
    }


class PrivateWeChartOfAccountListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    parent = PrivateChartOfAccountSlimSerializer(read_only=True)
    parent_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all(),
        write_only=True,
        required=False,
        # Explicit null must be accepted, or an account that has been parented
        # wrongly can never be returned to the top level -- which is what made a
        # cycle unrecoverable through the API rather than merely wrong.
        allow_null=True,
    )

    # Account type related
    account_type = PublicCategorySlimSerializer(read_only=True)
    account_type_slug = SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.filter(
            status=CategoryStatusChoices.ACTIVE,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        ),
        write_only=True,
    )

    # Detail type related
    detail_type = PublicCategorySlimSerializer(read_only=True)
    detail_type_slug = SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.filter(
            status=CategoryStatusChoices.ACTIVE,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        ),
        write_only=True,
    )

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "date",
            "code",
            "status",
            "kind",
            # Account type related
            "account_type",
            "account_type_slug",
            # Detail type related
            "detail_type",
            "detail_type_slug",
            "opening_balance",
            "currency",
            "description",
            "parent",
            "parent_uid",
            "is_fixed",
            "bank_balance",
            "bank_id",
            "is_money_account",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "kind", "is_fixed", "created_at", "updated_at"]

    def validate(self, validated_data):
        company = self.context["request"].user.get_active_company()
        assert_account_identity_is_free(
            company,
            title=validated_data.get("title"),
            code=validated_data.get("code"),
        )

        # The account type must resolve to one of the five kinds -- see
        # derive_account_kind for what used to get through.
        account_type = validated_data.get("account_type_slug")
        if derive_account_kind(account_type) is None:
            raise ValidationError(
                {
                    "account_type_slug": (
                        f"{getattr(account_type, 'title', account_type)!r} is not a "
                        "valid account type. Choose one of the types listed under "
                        "Assets, Liabilities, Equities, Incomes or Expenses."
                    )
                }
            )

        # An income or expense account cannot carry an opening balance. Those
        # accounts measure activity over a period and start every period at
        # zero; the accumulated result lives in Retained Earnings.
        #
        # This is not merely conceptual: create() only posts the opening-balance
        # journal entry for ASSETS, LIABILITIES and EQUITIES. An income or
        # expense account was still created with the balance stored on the row,
        # with no journal entry behind it -- an account whose stored balance
        # disagreed with its own (empty) ledger from the moment it existed.
        #
        # Checked here on the way in rather than in save()/clean(): the column
        # IS the running balance the posting engine mutates on every entry, so a
        # model-level guard would reject every invoice, refund and COGS posting.
        opening_balance = validated_data.get("opening_balance") or 0
        if opening_balance and derive_account_kind(account_type) in {
            ChartOfAccountKindChoices.INCOMES,
            ChartOfAccountKindChoices.EXPENSES,
        }:
            raise ValidationError(
                {
                    "opening_balance": (
                        "Income and expense accounts cannot have an opening "
                        "balance. They start each period at zero; prior results "
                        "belong in Retained Earnings."
                    )
                }
            )

        # COA-171. A receivable or payable balance is the SUM of the documents
        # behind it, and those documents are what the subledger and the ageing
        # report read. Typing a figure straight onto the control account puts a
        # number there that no customer or supplier owns, so the control account
        # and its subledger disagree by exactly that amount from the moment it
        # is entered -- which is the shape of the 2,399,995 discrepancy already
        # measured on company 165.
        #
        # The remedy is the same one the specification gives: enter the open
        # invoices and bills. That is also what the customer-creation path does,
        # so the two agree.
        if opening_balance and _is_receivable_or_payable(account_type):
            raise ValidationError(
                {
                    "opening_balance": (
                        "Accounts Receivable and Accounts Payable cannot take an "
                        "opening balance directly. Enter the open invoices and "
                        "bills instead, so the customer and supplier balances "
                        "add up to this account."
                    )
                }
            )

        validate_detail_type_belongs_to(
            account_type, validated_data.get("detail_type_slug")
        )

        validated_data["company"] = company
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        validated_data["parent"] = validated_data.pop("parent_uid", None)
        validated_data["account_type"] = validated_data.pop("account_type_slug", None)
        validated_data["detail_type"] = validated_data.pop("detail_type_slug", None)

        # Safe by now -- validate() has already proved the account type resolves
        # to one of the five kinds.
        #
        # Bound to a local as well as onto validated_data because the opening
        # balance block below reads it three times. An earlier change replaced
        # the two lines that derived it with this one and left those reads
        # behind, so `opening_balance != 0` -- which short-circuits the name away
        # when the balance is zero -- was the only thing standing between an
        # ordinary account creation and a NameError.
        chart_of_account_kind = derive_account_kind(validated_data["account_type"])
        validated_data["kind"] = chart_of_account_kind
        opening_balance = validated_data.get("opening_balance", 0)
        chart_of_accounts = get_chart_of_account(
            ["Opening Balance Equity"],
            company,
        )
        opening_balance_equity_charter_account = chart_of_accounts.get(
            "Opening Balance Equity"
        )

        # A company with no Opening Balance Equity account cannot take an opening
        # balance, and must say so rather than fail on it.
        #
        # `get_chart_of_account` returns a dict, so `.get()` yields None here.
        # The code below then did `None.opening_balance += ...` -- an
        # AttributeError, so a 500 on ordinary account creation rather than a
        # validation error the client can act on. Every industry seed ships this
        # account, so a company missing it is recoverable: create it and retry.
        if opening_balance != 0 and opening_balance_equity_charter_account is None:
            raise ValidationError(
                {
                    "opening_balance": (
                        "This company has no 'Opening Balance Equity' account, so "
                        "an opening balance cannot be journaled. Create that "
                        "account first, or create this one with no opening "
                        "balance."
                    )
                }
            )

        # Create chart of account
        chart_of_account = ChartOfAccount.objects.create(**validated_data)

        connector_data = []
        if opening_balance != 0 and chart_of_account_kind in [
            ChartOfAccountKindChoices.ASSETS,
            ChartOfAccountKindChoices.LIABILITIES,
            ChartOfAccountKindChoices.EQUITIES,
        ]:
            # An opening balance on an ASSET is funded by equity going up; on a
            # LIABILITY or EQUITY account it is funded by equity coming down.
            # That single difference was two near-identical branches, and it is
            # the only thing that differed between them.
            obe_action = (
                "addition"
                if chart_of_account_kind == ChartOfAccountKindChoices.ASSETS
                else "substraction"
            )

            # Through the helper, not `+=` then `save_dirty_fields()`.
            #
            # This is the one row every account creation in a company touches, so
            # it is the most contended balance in the schema -- and it was the
            # one doing an unlocked read-modify-write. Two concurrent creations
            # both read the same figure and wrote back their own total, so one
            # increment was simply lost. `update_opening_balance` was given an
            # `F()` increment and a `refresh_from_db()` under P1.4 to close
            # exactly this, and this call site never adopted it.
            #
            # `refresh_from_db()` inside the helper is also why the connector
            # below can read `opening_balance` straight afterwards and get the
            # new figure rather than a stale one.
            update_opening_balance(
                opening_balance_equity_charter_account,
                balance_operation_for_action(obe_action),
                opening_balance,
                0,
            )

            connector_data += [
                (
                    chart_of_account,
                    "addition",
                    opening_balance,
                    opening_balance,
                    None,
                ),
                (
                    opening_balance_equity_charter_account,
                    obe_action,
                    opening_balance,
                    opening_balance_equity_charter_account.opening_balance,
                    None,
                ),
            ]
            journal_entry = JournalEntry.objects.create(
                amount=opening_balance,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
                is_journal_entry=False,
                is_transaction=True,
                company=validated_data["company"],
            )
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=opening_balance,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                created_by=self.context["request"].user.get_employee(),
            )
        # The instance, not the payload dict. Returning the dict made DRF render
        # the 201 body from it, so the response carried no `uid` -- the client
        # had just created something it could not address.
        return chart_of_account

class PrivateWeChartOfAccountDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    parent = PrivateChartOfAccountSlimSerializer(read_only=True)
    parent_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all(),
        write_only=True,
        required=False,
        # Explicit null must be accepted, or an account that has been parented
        # wrongly can never be returned to the top level -- which is what made a
        # cycle unrecoverable through the API rather than merely wrong.
        allow_null=True,
    )

    # Account type related
    account_type = PublicCategorySlimSerializer(read_only=True)
    account_type_slug = SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.filter(
            status=CategoryStatusChoices.ACTIVE,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        ),
        write_only=True,
    )

    # Detail type related
    detail_type = PublicCategorySlimSerializer(read_only=True)
    detail_type_slug = SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.filter(
            status=CategoryStatusChoices.ACTIVE,
            kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        ),
        write_only=True,
    )

    # Told to the client rather than inferred by it. The register renders two
    # amount columns from the row's `deposit` and `payment`, and what those are
    # CALLED depends on the account -- a bank deposits and pays, a credit card is
    # charged and paid down, everything else increases and decreases. The client
    # was deciding this by matching the account type title against
    # /credit\s*card/i: a user-editable string, in a regex, to label money.
    is_debit_natural = SerializerMethodField(read_only=True)
    is_control_account = SerializerMethodField(read_only=True)
    column_labels = SerializerMethodField(read_only=True)
    reconciled_through = SerializerMethodField(read_only=True)

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "date",
            "code",
            "status",
            "kind",
            # Account type related
            "account_type",
            "account_type_slug",
            # Detail type related
            "detail_type",
            "detail_type_slug",
            "opening_balance",
            "currency",
            "description",
            "parent",
            "parent_uid",
            "is_fixed",
            "is_control_account",
            "bank_balance",
            "bank_id",
            "is_money_account",
            "is_debit_natural",
            "column_labels",
            "reconciled_through",
            "created_at",
            "updated_at",
        ]
        # `opening_balance` is read-only on update. It is a *running balance* the
        # posting engine maintains, not a settable field: writing it here moved
        # the stored figure with no journal entry behind it, which is precisely
        # how an account's balance comes to disagree with its own lines. It is
        # set once at create (which posts the matching Opening Balance Equity
        # entry); later corrections are a dated journal entry.
        #
        # `system_key` is deliberately absent from `fields` above, so it is
        # already unwritable, and `journalio/tests.py` asserts that absence
        # because it is stronger than read-only. Do not add it, in either form:
        # the posting engine resolves control accounts by it, and letting a
        # client move it would repoint posting at a different account.
        #
        # `is_control_account` below answers the only question a client had for
        # it -- whether to badge this account -- without handing over the key
        # itself. `is_fixed` cannot answer it: it means "came from the seed" and
        # is true of nearly every account, including Cash on Hand.
        # `kind` is DERIVED from account_type (see the create serializer), never
        # supplied by a client. It was writable here and update() never
        # re-derived it, so a PATCH could set it to anything -- including a value
        # outside ChartOfAccountKindChoices, which Django does not enforce on
        # save(). An account whose kind does not match its account_type
        # disappears from every balance-sheet bucket.
        read_only_fields = [
            "uid",
            "kind",
            # Writable here, though the list serializer has always had it
            # read-only. It says whether the ledger binds to this account, which
            # is a fact about the posting engine and not something a request may
            # assert -- and setting it is one-way: `validate()` below then
            # refuses every subsequent modification, and the DELETE view refuses
            # to remove it. A client could freeze an account permanently, by
            # intent or by replaying a GET payload back as a PUT, with no route
            # in the API to undo it.
            "is_fixed",
            "opening_balance",
            "created_at",
            "updated_at",
        ]

    def get_is_control_account(self, instance):
        """Whether the posting engine resolves this account by name.

        Derived from `system_key` without exposing it. The key is what
        `get_chart_of_account()` looks up, so it stays unreadable and
        unwritable; whether one exists is a fact a UI legitimately needs, to
        badge the account and to explain why editing and deleting are refused.
        """
        return bool(instance.system_key)

    def get_is_debit_natural(self, instance):
        """Whether a debit increases this account. The sign behind the columns."""
        return is_debit_natural(instance.kind)

    def get_column_labels(self, instance):
        """`{"deposit": ..., "payment": ...}` -- headings for the row's two
        amount fields, keyed to those field names so the mapping is obvious."""
        return register_column_labels(instance)

    def get_reconciled_through(self, instance):
        """The statement date of the latest closed reconciliation, or null.

        QuickBooks shows this in the register header and it was computable but
        unreachable: `reconciled_through` had exactly one caller, the undo view,
        so the only way to learn the watermark was to destroy a reconciliation.

        Null means nothing has ever closed on this account -- a different fact
        from a date in the past, and not to be flattened into one.
        """
        from transactionio.django_rest.helpers.reconciliation import (
            reconciled_through,
        )

        return reconciled_through(instance.company, instance)

    def validate(self, validated_data):
        if self.instance.is_fixed == True:
            raise ValidationError({"message": "Fixed account cannot be modified."})
        if validated_data.get("parent_uid") == self.instance:
            raise ValidationError({"message": "An account cannot be its own parent."})

        # ...and not its own grandparent either. Comparing one link let two
        # PATCHes build a cycle that no API sequence could then undo.
        if "parent_uid" in validated_data:
            assert_parent_is_not_a_cycle(self.instance, validated_data["parent_uid"])

        # Removal has to go through DELETE, which refuses to remove an account
        # still used as a parent. Setting the status directly skipped that guard
        # and orphaned the children.
        if (
            validated_data.get("status") == ChartOfAccountStatusChoices.REMOVED
            and self.instance.status != ChartOfAccountStatusChoices.REMOVED
        ):
            raise ValidationError(
                {
                    "status": (
                        "Use DELETE on this account to remove it. That path "
                        "checks whether other accounts still use it as a parent."
                    )
                }
            )

        # Same reasoning for retiring. Deactivation has three preconditions --
        # zero balance, no live mapping pointing at it, no active children --
        # and a PATCH straight to the status honours none of them.
        if (
            validated_data.get("status") == ChartOfAccountStatusChoices.INACTIVE
            and self.instance.status != ChartOfAccountStatusChoices.INACTIVE
        ):
            raise ValidationError(
                {
                    "status": (
                        "Use the deactivate endpoint to make this account "
                        "inactive. That path checks the balance, what still "
                        "maps to it, and its sub-accounts."
                    )
                }
            )

        # Reclassifying a posted account restates every period it appears in.
        # The model blocks this for every writer; catching it here turns what
        # would be a 500 into a field-level 400.
        if self.instance.pk and self.instance.has_journal_lines():
            attempted = {
                "account_type": validated_data.get("account_type_slug"),
                "detail_type": validated_data.get("detail_type_slug"),
            }
            changed = [
                field
                for field, value in attempted.items()
                if value is not None and value != getattr(self.instance, field)
            ]
            if changed:
                raise ValidationError(
                    {
                        field: (
                            "Cannot change this on an account that already has "
                            "journal entries. Create a new account and move the "
                            "balance with a dated journal entry instead."
                        )
                        for field in changed
                    }
                )

        # Renaming onto another account's title or code was unguarded -- only
        # create() checked. Excluding the row itself so keeping your own name is
        # not a collision.
        assert_account_identity_is_free(
            self.instance.company,
            title=validated_data.get("title"),
            code=validated_data.get("code"),
            exclude_pk=self.instance.pk,
        )

        # A PATCH may send either half, so the other comes from the row.
        validate_detail_type_belongs_to(
            validated_data.get("account_type_slug") or self.instance.account_type,
            validated_data.get("detail_type_slug") or self.instance.detail_type,
        )

        return super().validate(validated_data)

    @set_auditlog_actor
    def update(self, instance, validated_data):
        user = self.context["request"].user
        validated_data["company"] = user.get_active_company()
        # `in`, not a truthy walrus: a PATCH sending `parent_uid: null` means
        # "move this to the top level", and the walrus silently discarded it.
        if "parent_uid" in validated_data:
            validated_data["parent"] = validated_data.pop("parent_uid")
        if account_type_slug := validated_data.pop("account_type_slug", None):
            validated_data["account_type"] = account_type_slug
            # `kind` is derived from the account type, and only `create()` was
            # deriving it. A PATCH that moved an account to a different type
            # left `kind` behind, so the two disagreed: the statement engines
            # bucket on `account_type` while `kind` is what most other code
            # reads, and an account whose pair does not match belongs to no
            # section of either statement while its journal lines stay in the
            # ledger.
            #
            # The model's own guard does not cover this -- it refuses to
            # reclassify an account that HAS posted lines, so a not-yet-posted
            # account could be retyped freely and only diverge once it was used.
            derived = derive_account_kind(account_type_slug)
            if derived is None:
                # Only the create path checked this. An account type whose
                # parent is not one of the five kinds cannot yield a valid
                # account, and writing the None would be worse than the stale
                # value it replaces.
                raise ValidationError(
                    {
                        "account_type_slug": (
                            f"{account_type_slug.title!r} is not a valid account "
                            "type. Choose one of the types listed under Assets, "
                            "Liabilities, Equities, Incomes or Expenses."
                        )
                    }
                )
            validated_data["kind"] = derived
        if detail_type_slug := validated_data.pop("detail_type_slug", None):
            validated_data["detail_type"] = detail_type_slug
        return super().update(instance, validated_data)


class PrivateWeChartOfAccountTreeSerializer(ModelSerializer):
    children = SerializerMethodField()
    # Account type related
    account_type = PublicCategorySlimSerializer(read_only=True)

    # Detail type related
    detail_type = PublicCategorySlimSerializer(read_only=True)

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "slug",
            "title",
            "date",
            "code",
            "status",
            "kind",
            "account_type",
            "detail_type",
            "opening_balance",
            "currency",
            "description",
            "children",
        ]

    def get_children(self, instance):
        return PrivateWeChartOfAccountTreeSerializer(
            instance.parents.get_status_all(), many=True
        ).data


class RegisterSupplierSerializer(ModelSerializer):
    """`PrivateSupplierSlimSerializer` without its per-row aggregate.

    That serializer carries `total_credit = CharField(source="get_credit_count")`,
    which runs a `Sum` over the supplier's credit notes -- one query per row.
    Measured on a ten-row page: thirteen queries, ten of them this one. It is
    also not a property of a ledger line; how much credit a supplier holds says
    nothing about the payment on this row, and the register never showed it.

    The shared serializer is left alone: it is mounted on many endpoints where
    the figure is the point.
    """

    class Meta:
        model = Supplier
        fields = [
            "uid",
            "currency",
            "first_name",
            "last_name",
            "email",
            "mobile_number",
            "image",
            "display_name",
            "company_name",
            "opening_balance",
        ]
        read_only_fields = fields


class PrivateWeChartOfAccountSessionListSerializer(DerivedRunningBalanceMixin, ModelSerializer):
    """One row of an account register: one ledger leg.

    A leg, deliberately, not a document. Reconcile groups by document
    (`candidate_documents` sums a journal's legs) and this does not, so the two
    screens show different row counts -- an amended payment is two rows here and
    one there. Grouping was considered and rejected: `create_journal_entry` does
    `get_or_create` on the document FK, so one PayBill is one JournalEntry
    carrying every payee's legs, and grouping a bank register by journal would
    merge two suppliers' payments into a single row. `document_uid` carries the
    document identity instead, so the client can group visually and send the uid
    that `/reconcile/complete` actually accepts.
    """

    last_balance = SerializerMethodField(read_only=True)
    running_balance = SerializerMethodField(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)
    supplier = RegisterSupplierSerializer(read_only=True)
    journal = PrivateJournalEntrySlimSerializer(read_only=True)

    # The document this leg belongs to. `uid` above is the leg's own, and
    # `/reconcile/complete` resolves `journal__uid` -- sending a row's `uid`
    # there fails by name every time.
    document_uid = CharField(source="journal.uid", read_only=True)
    entry_number = CharField(source="journal.entry_number", read_only=True)
    # The transaction type. Flat, and named as the general-ledger endpoint
    # already names it. `kind` on this model is the posting side and
    # `request_kind` is the audit action -- neither is the Type column, and
    # reading `request_kind` for it is why every row said "Created".
    model_kind = CharField(source="get_model_kind", read_only=True)

    description = SerializerMethodField(read_only=True)
    payee = SerializerMethodField(read_only=True)
    deposit = SerializerMethodField(read_only=True)
    payment = SerializerMethodField(read_only=True)
    is_adjustment = SerializerMethodField(read_only=True)
    category = SerializerMethodField(read_only=True)
    warehouse = SerializerMethodField(read_only=True)
    reconciliation_status = SerializerMethodField(read_only=True)
    reconciliation_uid = CharField(source="reconciliation.uid", read_only=True, default=None)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "date",
            "document_uid",
            "entry_number",
            "model_kind",
            "debit",
            "credit",
            "deposit",
            "payment",
            "total",
            "last_balance",
            "running_balance",
            "kind",
            "request_kind",
            "is_adjustment",
            "description",
            "category",
            "warehouse",
            "payee",
            "customer",
            "supplier",
            "journal",
            "reconciliation_status",
            "reconciliation_uid",
            "cleared_on",
            "created_at",
            "updated_at",
        ]

    def _account_kind(self):
        account = self.context.get("account")
        return getattr(account, "kind", None)

    def get_description(self, instance):
        """The memo, resolved rather than raw.

        Both `JournalEntryConnector.description` and `JournalEntry.description`
        exist and their writers are disjoint -- the leg's is written by the
        manual-journal path, the payroll void and the reconciliation undo; the
        entry's by the manual-journal path and the bank-feed auto-add. Sale,
        purchase, pay-bill and deposit rows carry neither, so a register memo
        column is empty on them whichever one is read.
        """
        return instance.description or getattr(instance.journal, "description", None)

    def get_payee(self, instance):
        """Who the money moved to or from, resolved server-side.

        Three FKs can carry it and only one is ever set, but which one depends
        on the document: a payroll leg carries `employee` and nothing else, so a
        client checking only customer/supplier renders every paycheck blank.
        `created_by` is deliberately not in the chain -- that is whoever keyed
        the entry, not who was paid.
        """
        for party, kind in (
            (instance.employee, "EMPLOYEE"),
            (instance.supplier, "SUPPLIER"),
            (instance.customer, "CUSTOMER"),
        ):
            if party is None:
                continue
            name = (
                getattr(party, "display_name", None)
                or getattr(party, "company_name", None)
                # A BD employee's name (employeeio has no first/last split).
                or getattr(party, "name_en", None)
                or " ".join(
                    part
                    for part in (
                        getattr(party, "first_name", None),
                        getattr(party, "middle_name", None),
                        getattr(party, "last_name", None),
                    )
                    if part
                )
                or getattr(party, "email", None)
            )
            return {"uid": str(party.uid), "name": name or None, "kind": kind}
        return None

    def _directional(self, instance, want_increase):
        """Split the leg into money-in and money-out for *this* account.

        A debit is money in on a bank and money out on a credit card. The row
        carries no account, so the client cannot work this out on its own --
        today it guesses by regexing the account type title for "credit card".
        """
        account_kind = self._account_kind()
        if account_kind is None:
            return None
        increases = (
            instance.debit if is_debit_natural(account_kind) else instance.credit
        )
        decreases = (
            instance.credit if is_debit_natural(account_kind) else instance.debit
        )
        amount = increases if want_increase else decreases
        return f"{Decimal(str(amount or 0)):.3f}"

    def get_deposit(self, instance):
        return self._directional(instance, want_increase=True)

    def get_payment(self, instance):
        return self._directional(instance, want_increase=False)

    # The document-line FKs, most specific first. A leg carrying one of these
    # names the document *line* it came from, which is finer than the journal.
    LINE_SCOPES = (
        "pay_bill_item_id",
        "saleitem_id",
        "purchase_item_id",
        "credit_note_item_id",
    )

    def get_category(self, instance):
        """The account on the other side of this entry, or `-Split-`.

        A register shows the contra account, so a bank line reads "Sales Income"
        rather than repeating the bank. More than one distinct contra and the
        row is a split.

        Deduplicated on `account_id`, not on leg count. One leg is written per
        document line, so an ordinary three-line invoice puts three legs on Sales
        Income -- counting legs would call that a split.

        Scoped to the document *line* when the leg carries one. One PayBill is
        one JournalEntry holding every payee's legs (`create_journal_entry` does
        `get_or_create` on the document FK), so without this narrowing payee 1's
        bank line would see payee 2's bank account as a contra and every Pay
        Bills row would read `-Split-`.

        Returns None rather than raising or guessing when there is no contra at
        all: one-legged entries are reachable -- a sale whose cost account is
        missing posts neither leg of a pair, and `assert_entry_balances` logs
        rather than raises -- and the production ledger holds hundreds of them.
        """
        siblings = getattr(instance.journal, "sibling_legs", None)
        if siblings is None:
            return None

        for scope in self.LINE_SCOPES:
            line_id = getattr(instance, scope, None)
            if line_id is None:
                continue
            narrowed = [
                leg for leg in siblings if getattr(leg, scope, None) == line_id
            ]
            if narrowed:
                siblings = narrowed
            break

        contras = {
            leg.account_id: leg.account.title
            for leg in siblings
            if leg.account_id != instance.account_id
        }
        if not contras:
            return None
        if len(contras) == 1:
            return next(iter(contras.values()))
        return "-Split-"

    def get_warehouse(self, instance):
        """The store, taken from the document rather than the leg.

        `JournalEntryConnector.warehose` (sic) exists but no posting call site
        passes it, so reading it would serialize null on every posted row. The
        document knows -- but only some documents: Sale, Purchase and CreditNote
        carry a warehouse, while StockAdjustment, Expense, PayBill, BankDeposit
        and the payroll documents do not, which is most of what puts a line on a
        bank account. Expect this to be null on a bank register more often than
        not; that is the data, not a bug in the lookup.
        """
        journal = instance.journal
        for source in ("sale", "purchase", "credit_note"):
            document = getattr(journal, source, None)
            warehouse = getattr(document, "warehouse", None)
            if warehouse is not None:
                return {"uid": str(warehouse.uid), "title": warehouse.title}
        return None

    def get_reconciliation_status(self, instance):
        """U, C or R for this line.

        The pair of columns *is* the status, as `undo_reconciliation` puts it:
        reconciled means pointing at a closed session, cleared means carrying a
        tick date and no session.

        R is decided by the session's own status, never by the FK being set. A
        line can be left pointing at an UNDONE session -- undo releases through
        `candidate_connectors`, which also filters on `journal__status` and the
        statement date, so a line whose entry was soft-deleted or whose date
        moved is skipped and keeps the FK. Null-checking the FK would report
        those as reconciled forever.
        """
        session = instance.reconciliation
        if session is not None and (
            session.status == BankReconciliationStatusChoices.CLOSED
        ):
            return "R"
        if instance.cleared_on is not None:
            return "C"
        return "U"

    def get_is_adjustment(self, instance):
        """Whether this leg amends or reverses an earlier one.

        An amended payment appends a delta leg rather than rewriting the
        original, and a void appends reversing legs, so both the original and
        the correction are rows in this register. That is the ledger being
        honest, but a client showing them as two unrelated payments is not.
        """
        return instance.request_kind != JournalEntryConnectorRequestKindChoices.CREATED


class PrivateWeTransactedChartOfAccountSerializer(ModelSerializer):
    total_transacted_amount = CharField(
        source="get_total_transacted_amount", read_only=True
    )

    class Meta:
        model = ChartOfAccount
        fields = [
            "uid",
            "title",
            "code",
            "kind",
            "status",
            "opening_balance",
            "total_transacted_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
