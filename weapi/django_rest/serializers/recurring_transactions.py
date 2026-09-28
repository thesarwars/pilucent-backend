"""Serializers for Recurring Transaction templates (Phase 1: Bill).

A template is a parent/child aggregate: the header + embedded schedule on
``RecurringTemplate`` and its category/item rows on ``RecurringTemplateLine``.
The write serializer accepts lines inline and, on save, recomputes the cached
total and the first/next run date via the scheduling engine.

See ``docs/updated-prompts/Balanzify_Recurring_Transactions_Bill.md`` sections 9 & 12.
"""

from decimal import Decimal

from django.db import transaction

from rest_framework.serializers import (
    BooleanField,
    CharField,
    DateField,
    FloatField,
    IntegerField,
    ModelSerializer,
    Serializer,
    JSONField,
    SerializerMethodField,
    SlugRelatedField,
    ValidationError,
)

from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from customerio.models import Customer

from fileroomio.choices import FileItemConnectorModelKindChoices
from fileroomio.django_rest.services.files import FileService
from fileroomio.models import FileItemConnector
from paymentio.choices import PaymentMethodStatusChoices
from paymentio.models import PaymentMethod
from productio.models import Product
from supplierio.models import Supplier
from termio.models import Term
from wirehouseio.models import Warehouse

from recurringio.choices import (
    RecurringEndTypeChoices,
    RecurringLineTypeChoices,
    RecurringTemplateStatusChoices,
    RecurringTemplateTypeChoices,
    RecurringTxnTypeChoices,
)
from recurringio.models import RecurringTemplate, RecurringTemplateLine
from recurringio.services import scheduling
from recurringio.services.totals import compute_totals

_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Several types name the shared settlement account differently on the wire: a
# refund goes OUT of `refund_from`, a payment lands IN `deposit_to`. Same column
# either way -- direction is a property of the txn_type, not of the account --
# so accept the aliases on input and echo them on output rather than carrying
# near-duplicate FKs.
_REFUND_INPUT_ALIASES = {
    "refund_from": "payment_account",
    "deposit_to": "payment_account",
    "term": "terms",
    "message_on_invoice": "message_on_estimate",
    "customer_email": "email_to",
    "email": "email_to",
    "cc_emails": "email_cc",
    "bcc_emails": "email_bcc",
    "message_on_receipt": "message_on_estimate",
    "message_on_credit_memo": "message_on_estimate",
}



def _party_name(party):
    """Display name for a customer/supplier, falling back to the name parts.

    ``display_name`` is nullable on both models while ``first_name`` is not, so
    reading it directly returns null for any party saved without one -- which is
    most of them. Every name shown on a recurring screen goes through here.
    """
    if party is None:
        return None
    display = (getattr(party, "display_name", "") or "").strip()
    if display:
        return display
    parts = [
        (getattr(party, "first_name", "") or "").strip(),
        (getattr(party, "middle_name", "") or "").strip(),
        (getattr(party, "last_name", "") or "").strip(),
    ]
    joined = " ".join(part for part in parts if part)
    return joined or (getattr(party, "company_name", "") or "").strip() or None

from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)

class PrivateWeRecurringTemplateLineSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    """A single category or item line on a template."""

    charter_account = SlugRelatedField(
        slug_field="uid", queryset=ChartOfAccount.objects.selectable().all(), required=False, allow_null=True
    )
    product = SlugRelatedField(
        slug_field="uid", queryset=Product.objects.all(), required=False, allow_null=True
    )
    tax = SlugRelatedField(
        slug_field="uid", queryset=AgencyTax.objects.all(), required=False, allow_null=True
    )
    customer = SlugRelatedField(
        slug_field="uid", queryset=Customer.objects.selectable().all(), required=False, allow_null=True
    )
    # DEPOSIT fund rows: the payer and instrument live on the LINE, because a
    # deposit has no document-level party.
    supplier = SlugRelatedField(
        slug_field="uid", queryset=Supplier.objects.selectable(), required=False, allow_null=True
    )
    payment_method = SlugRelatedField(
        slug_field="uid", queryset=PaymentMethod.objects.all(), required=False,
        allow_null=True,
    )

    # Read-only display helpers (None-safe: DRF returns null when the FK is unset)
    charter_account_title = CharField(source="charter_account.title", read_only=True)
    product_title = CharField(source="product.title", read_only=True)
    customer_name = SerializerMethodField()
    supplier_name = SerializerMethodField()
    payment_method_title = CharField(source="payment_method.title", read_only=True)

    def get_customer_name(self, obj):
        return _party_name(obj.customer)

    def get_supplier_name(self, obj):
        return _party_name(obj.supplier)

    class Meta:
        model = RecurringTemplateLine
        fields = [
            "uid",
            "line_type",
            "position",
            "description",
            "quantity",
            "rate",
            "amount",
            "is_billable",
            "charter_account",
            "charter_account_title",
            "product",
            "product_title",
            "tax",
            "customer",
            "customer_name",
            "supplier",
            "supplier_name",
            "payment_method",
            "payment_method_title",
            "reference_number",
        ]


class PrivateWeRecurringTemplateListSerializer(ModelSerializer):
    """Slim row for the Recurring Transactions list."""

    supplier_name = SerializerMethodField()
    customer_name = SerializerMethodField()
    party_name = SerializerMethodField()
    interval_display = SerializerMethodField()
    line_count = IntegerField(source="lines.count", read_only=True)

    def get_supplier_name(self, obj):
        return _party_name(obj.supplier)

    def get_customer_name(self, obj):
        return _party_name(obj.customer)

    class Meta:
        model = RecurringTemplate
        fields = [
            "uid",
            "name",
            "txn_type",
            "template_type",
            "status",
            "currency_code",
            "total_amount",
            "autopay_enabled",
            "supplier_name",
            "customer_name",
            "party_name",
            "interval_display",
            "previous_run_date",
            "next_run_date",
            "line_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_interval_display(self, obj):
        return _interval_label(obj)

    def get_party_name(self, obj):
        # A DEPOSIT has no document-level party -- the payer is per fund row --
        # so the list's Customer/Vendor column would always render "-". Name it
        # the way the deposit screen's own footer does ("Deposit to {account}"),
        # falling back to a single fund row's payer when the deposit has one.
        if obj.txn_type == RecurringTxnTypeChoices.DEPOSIT:
            payers = {
                _party_name(line.customer) or _party_name(line.supplier)
                for line in obj.lines.all()
            }
            payers.discard(None)
            if len(payers) == 1:
                return payers.pop()
            return getattr(obj.payment_account, "title", None)

        # The row's counterparty: customer for a sales-side document (estimate,
        # refund receipt, payment), otherwise the vendor.
        if obj.txn_type in (
            RecurringTxnTypeChoices.ESTIMATE,
            RecurringTxnTypeChoices.REFUND_RECEIPT,
            RecurringTxnTypeChoices.PAYMENT,
            RecurringTxnTypeChoices.INVOICE,
            RecurringTxnTypeChoices.SALES_RECEIPT,
            RecurringTxnTypeChoices.CREDIT_MEMO,
        ):
            return _party_name(obj.customer)
        return _party_name(obj.supplier)


def _interval_label(obj):
    """Human-readable schedule summary (e.g. 'Every 2 months on day 15')."""
    if obj.template_type == RecurringTemplateTypeChoices.UNSCHEDULED or not obj.frequency:
        return "Unscheduled"

    every = "" if (obj.interval_count or 1) == 1 else f"{obj.interval_count} "
    freq = obj.frequency.lower()
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}.get(
        freq, freq
    )
    base = f"Every {every}{unit}{'s' if every else ''}"

    if freq == "weekly" and obj.weekday is not None:
        return f"{base} on {_WEEKDAY_LABELS[obj.weekday]}"
    if freq in ("monthly", "yearly"):
        if obj.day_mode == "WEEKDAY" and obj.ordinal and obj.weekday is not None:
            return f"{base} on the {obj.ordinal.lower()} {_WEEKDAY_LABELS[obj.weekday]}"
        if obj.day_of_month:
            return f"{base} on day {obj.day_of_month}"
    return base


class PrivateWeRecurringTemplateSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    """Create / retrieve / update a template with its lines."""

    lines = PrivateWeRecurringTemplateLineSerializer(many=True)
    # supplier is required for money-out types, customer for ESTIMATE; enforced
    # per txn_type in validate() rather than at the field level.
    supplier = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        required=False,
        allow_null=True,
        # The payee dropdown merges customers and suppliers, so a customer uid
        # can legitimately arrive here. Only vendors are valid (the generated
        # bill/cheque takes a supplier_uid), so say that instead of leaking the
        # default "Object with uid=… does not exist".
        error_messages={
            "does_not_exist": (
                "No vendor found for this id. Bills and cheques are issued to a "
                "vendor — a customer record cannot be used as the payee."
            )
        },
    )
    customer = SlugRelatedField(
        slug_field="uid", queryset=Customer.objects.selectable().all(), required=False, allow_null=True
    )
    # A purchase order ships to a CUSTOMER while its party is the supplier, so
    # this is a second customer-valued relation, not the party.
    ship_to = SlugRelatedField(
        slug_field="uid", queryset=Customer.objects.selectable().all(), required=False, allow_null=True
    )
    cash_back_account = SlugRelatedField(
        slug_field="uid", queryset=ChartOfAccount.objects.selectable().all(), required=False,
        allow_null=True,
    )
    # A purchase order ships to a CUSTOMER while its party is the supplier, so
    # this is a second customer-valued relation, not the party.
    ship_to = SlugRelatedField(
        slug_field="uid", queryset=Customer.objects.selectable().all(), required=False, allow_null=True
    )
    terms = SlugRelatedField(
        slug_field="uid", queryset=Term.objects.all(), required=False, allow_null=True
    )
    warehouse = SlugRelatedField(
        slug_field="uid", queryset=Warehouse.objects.all(), required=False, allow_null=True
    )
    payment_account = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        required=False,
        allow_null=True,
    )
    payment_method = SlugRelatedField(
        slug_field="uid",
        queryset=PaymentMethod.objects.all(),
        required=False,
        allow_null=True,
    )
    # Document-level tax rate (REFUND_RECEIPT / sales-side); also stamped onto
    # taxed lines by the client.
    tax = SlugRelatedField(
        slug_field="uid", queryset=AgencyTax.objects.all(), required=False, allow_null=True
    )

    supplier_name = SerializerMethodField()
    customer_name = SerializerMethodField()
    payment_account_title = CharField(source="payment_account.title", read_only=True)
    # Title companions for the uid-valued relations. The uids themselves stay
    # bare strings (below) because the client feeds them straight into a URL —
    # `fetchTerm(t.terms)` / `fetchWarehouse(t.warehouse)` — so a nested object
    # would 404 silently. These titles save the client those extra round-trips.
    ship_to_name = SerializerMethodField()
    cash_back_account_title = CharField(
        source="cash_back_account.title", read_only=True, default=None
    )
    # Attachments are uploaded separately (we/attachments) and referenced here
    # by uid -- this endpoint is JSON-only, so raw files cannot ride along.
    file_uids = JSONField(required=False, write_only=True)
    file_description = CharField(required=False, write_only=True, allow_blank=True)
    files = SerializerMethodField()
    terms_title = CharField(source="terms.title", read_only=True, default=None)
    warehouse_title = CharField(source="warehouse.title", read_only=True, default=None)
    payment_method_title = CharField(
        source="payment_method.title", read_only=True, default=None
    )
    # The client rebuilds its tax picker from these; without the rate the tax
    # total renders 0 until the user re-picks the rate (a long-standing
    # hydration gap on the estimate screen).
    tax_title = CharField(source="tax.title", read_only=True, default=None)
    tax_rate = FloatField(source="tax.total_rate", read_only=True, default=None)
    interval_display = SerializerMethodField()

    # Relation keys where an empty string means "not picked". The invoice
    # screen assembles its flat keys unconditionally (like the live estimate
    # mapper does for mailing_address), so `"term": ""` / `"warehouse": ""`
    # legitimately reach the wire and must read as null, not as a uid lookup
    # that 400s with "object with uid= does not exist".
    _RELATION_KEYS = (
        "supplier", "customer", "terms", "term", "warehouse",
        "payment_account", "payment_method", "tax",
        "deposit_to", "refund_from", "ship_to", "cash_back_account",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            for key in self._RELATION_KEYS:
                if data.get(key) == "":
                    data[key] = None

            # `email` is polymorphic across types: the purchase-order screen
            # sends a comma-separated STRING of recipients, while the sales
            # receipt sends the nested {customer_email, cc_emails, bcc_emails}
            # blob that we/sales itself takes. Unwrap the object form first so
            # the string alias below only ever sees a string.
            if isinstance(data.get("email"), dict):
                recipients = data.pop("email")
                for wire, model_field in (
                    ("customer_email", "email_to"),
                    ("cc_emails", "email_cc"),
                    ("bcc_emails", "email_bcc"),
                ):
                    if wire in recipients and model_field not in data:
                        data[model_field] = recipients[wire]

            # Map per-type wire names onto the shared envelope fields.
            for wire, model_field in _REFUND_INPUT_ALIASES.items():
                if wire in data and model_field not in data:
                    data[model_field] = data.pop(wire)
        return super().to_internal_value(data)

    def to_representation(self, instance):
        # Every relation reads back as a BARE UID STRING (via SlugRelatedField),
        # never a nested object: the client passes `terms` / `warehouse` straight
        # into `GET /we/terms/{uid}` / `GET /we/warehouses/{uid}`, and an object
        # there 404s inside a bare `catch {}` — the field just silently fails to
        # hydrate. Titles ride alongside as `*_title` instead.
        data = super().to_representation(instance)
        # Echo each type's settlement-account alias so its screen hydrates.
        if instance.txn_type == RecurringTxnTypeChoices.PAYMENT:
            data["deposit_to"] = data.get("payment_account")
            data["deposit_to_title"] = data.get("payment_account_title")
        if instance.txn_type == RecurringTxnTypeChoices.INVOICE:
            # The invoice screen says `term` (singular) and rebuilds its Terms
            # dropdown as {uid, title, days} — days drives the due-date preview.
            data["term"] = data.get("terms")
            data["term_title"] = data.get("terms_title")
            data["term_days"] = instance.terms.days if instance.terms else None
            data["message_on_invoice"] = data.get("message_on_estimate")
            data["deposit_to"] = data.get("payment_account")
            data["deposit_to_title"] = data.get("payment_account_title")
        if instance.txn_type == RecurringTxnTypeChoices.CREDIT_MEMO:
            data["message_on_credit_memo"] = data.get("message_on_estimate")
            data["email"] = {
                "customer_email": data.get("email_to") or "",
                "cc_emails": data.get("email_cc") or "",
                "bcc_emails": data.get("email_bcc") or "",
            }
        if instance.txn_type == RecurringTxnTypeChoices.SALES_RECEIPT:
            data["deposit_to"] = data.get("payment_account")
            data["deposit_to_title"] = data.get("payment_account_title")
            data["message_on_receipt"] = data.get("message_on_estimate")
            # Returned in the nested shape the screen sends and we/sales takes.
            data["email"] = {
                "customer_email": data.get("email_to") or "",
                "cc_emails": data.get("email_cc") or "",
                "bcc_emails": data.get("email_bcc") or "",
            }
        if instance.txn_type == RecurringTxnTypeChoices.PURCHASE_ORDER:
            data["email"] = data.get("email_to")
        if instance.txn_type == RecurringTxnTypeChoices.REFUND_RECEIPT:
            data["refund_from"] = data.get("payment_account")
            data["refund_from_title"] = data.get("payment_account_title")
            data["customer_email"] = data.get("email_to")
            data["cc_emails"] = data.get("email_cc")
            data["bcc_emails"] = data.get("email_bcc")
            data["message_on_receipt"] = data.get("message_on_estimate")
        return data

    class Meta:
        model = RecurringTemplate
        fields = [
            "uid",
            "name",
            "txn_type",
            "template_type",
            "status",
            "mailing_address",
            "memo",
            "autopay_enabled",
            "currency_code",
            "create_days_in_advance",
            "remind_days_before",
            # cheque-only
            "cheque_number",
            "print_later",
            "permit_number",
            # estimate-only / customer-side (also used by REFUND_RECEIPT)
            "email_to",
            "email_cc",
            "email_bcc",
            "auto_email",
            "message_on_estimate",
            "expiry_days",
            "internal_note",
            "when_to_charge",
            "acceptance_status",
            "cash_back_account",
            "cash_back_account_title",
            "file_uids",
            "file_description",
            "files",
            "cash_back_memo",
            "cash_back_amount",
            "track_returns",
            "shipping_from",
            "ship_to",
            "ship_to_name",
            "full_shipping_address",
            "shipping_by",
            "payment_instructions",
            "include_unbilled_charges",
            "discount_kind",
            "discount",
            "shipping_fee",
            "deposit",
            # refund-receipt settlement + document fields
            "reference_number",
            "tracking_number",
            "statement_memo",
            "tax_kind",
            "tax",
            "tax_title",
            "tax_rate",
            "total_amount",
            # schedule
            "frequency",
            "interval_count",
            "day_mode",
            "day_of_month",
            "weekday",
            "ordinal",
            "month_of_year",
            "start_date",
            "end_type",
            "end_date",
            "end_after_occurrences",
            # run state (read-only)
            "previous_run_date",
            "next_run_date",
            "occurrences_generated",
            # relations
            "supplier",
            "supplier_name",
            "customer",
            "customer_name",
            "terms",
            "terms_title",
            "warehouse",
            "warehouse_title",
            "payment_account",
            "payment_account_title",
            "payment_method",
            "payment_method_title",
            "interval_display",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "status",
            "total_amount",
            "previous_run_date",
            "next_run_date",
            "occurrences_generated",
            "acceptance_status",
            "created_at",
            "updated_at",
        ]

    def get_interval_display(self, obj):
        return _interval_label(obj)

    def get_supplier_name(self, obj):
        return _party_name(obj.supplier)

    def get_customer_name(self, obj):
        return _party_name(obj.customer)

    def get_ship_to_name(self, obj):
        return _party_name(obj.ship_to)

    def get_files(self, obj):
        """Linked attachments, in the shape the upload widget rehydrates from.

        It keys off ``uid`` and labels rows from ``title``; a bare uid list
        cannot repopulate it, so the objects are returned alongside.
        """
        connectors = FileItemConnector.objects.filter(
            recurring_template=obj
        ).select_related("file_item")
        return [
            {
                "uid": str(connector.file_item.uid),
                "title": connector.file_item.title,
                "file": (
                    connector.file_item.file.url if connector.file_item.file else None
                ),
            }
            for connector in connectors
            if connector.file_item_id
        ]

    # ---- validation ------------------------------------------------------

    def validate(self, attrs):
        # Merge incoming with existing (partial updates) so cross-field checks
        # see the effective final state.
        def effective(field, default=None):
            if field in attrs:
                return attrs[field]
            if self.instance is not None:
                return getattr(self.instance, field)
            return default

        template_type = effective("template_type", RecurringTemplateTypeChoices.SCHEDULED)
        txn_type = effective("txn_type", RecurringTxnTypeChoices.BILL)
        lines = attrs.get("lines")
        if lines is not None and not lines:
            raise ValidationError({"lines": "Add at least one line to the template."})

        # Party: money-out types quote a vendor/payee; an estimate or refund
        # receipt names a customer.
        customer_types = (
            RecurringTxnTypeChoices.ESTIMATE,
            RecurringTxnTypeChoices.REFUND_RECEIPT,
            RecurringTxnTypeChoices.PAYMENT,
            RecurringTxnTypeChoices.INVOICE,
            RecurringTxnTypeChoices.SALES_RECEIPT,
            RecurringTxnTypeChoices.CREDIT_MEMO,
        )
        # A DEPOSIT has NO document-level party at all -- the payer is per
        # fund line -- so neither a customer nor a vendor is required.
        if txn_type == RecurringTxnTypeChoices.DEPOSIT:
            pass
        elif txn_type in customer_types:
            if not effective("customer"):
                raise ValidationError(
                    {"customer": "This recurring template needs a customer."}
                )
        elif not effective("supplier"):
            raise ValidationError({"supplier": "This recurring template needs a vendor."})

        # Types that settle at recording must name the account the money moves
        # through: a payment account for an expense, the bank for a cheque, the
        # refund-from (bank/credit-card) account for a refund receipt.
        if not effective("payment_account"):
            if txn_type == RecurringTxnTypeChoices.EXPENSE:
                raise ValidationError(
                    {"payment_account": "A recurring expense needs a payment account."}
                )
            if txn_type == RecurringTxnTypeChoices.CHEQUE:
                raise ValidationError(
                    {"payment_account": "A recurring cheque needs a bank account."}
                )
            if txn_type == RecurringTxnTypeChoices.REFUND_RECEIPT:
                raise ValidationError(
                    {"refund_from": "A recurring refund needs an account to refund from."}
                )
            if txn_type == RecurringTxnTypeChoices.PAYMENT:
                raise ValidationError(
                    {"deposit_to": "A recurring payment needs an account to deposit into."}
                )

        if txn_type == RecurringTxnTypeChoices.DEPOSIT:
            deposit_to = effective("payment_account")
            if deposit_to is None:
                raise ValidationError(
                    {"deposit_to": "A recurring deposit needs a bank account."}
                )
            account_type = getattr(deposit_to, "account_type", None)
            if account_type is not None and account_type.title != "Bank":
                raise ValidationError(
                    {"deposit_to": "Deposits must land in a bank account."}
                )

            cash_back = Decimal(str(effective("cash_back_amount") or 0))
            if cash_back < 0:
                raise ValidationError(
                    {"cash_back_amount": "Cash back must not be negative."}
                )
            if cash_back > 0 and not effective("cash_back_account"):
                raise ValidationError(
                    {"cash_back_account": "Cash back needs an account to go to."}
                )

            if lines is not None:
                funded = sum(
                    (Decimal(str(line.get("amount") or 0)) for line in lines),
                    Decimal("0"),
                )
                # Cash back is taken back OUT of the deposit, so it cannot
                # exceed what was paid in -- a deposit cannot net negative.
                if cash_back > funded:
                    raise ValidationError(
                        {"cash_back_amount": "Cash back cannot exceed the deposit total."}
                    )
                for index, line in enumerate(lines):
                    if line.get("customer") and line.get("supplier"):
                        raise ValidationError(
                            {
                                "lines": (
                                    f"Line {index + 1}: a fund row is received from "
                                    "either a customer or a vendor, not both."
                                )
                            }
                        )

        # The settlement account has to be one money can actually move through.
        # `account_type` is still nullable on legacy accounts, so only reject
        # when it is set and says otherwise.
        _SETTLEMENT_ACCOUNTS = {
            # A cheque is drawn on a bank, full stop.
            RecurringTxnTypeChoices.CHEQUE: (
                ("Bank",),
                "A cheque must be drawn on a bank account.",
            ),
            # An expense may legitimately be paid by company card.
            RecurringTxnTypeChoices.EXPENSE: (
                ("Bank", "Credit Card"),
                "An expense must be paid from a bank or credit-card account.",
            ),
        }
        if txn_type in _SETTLEMENT_ACCOUNTS:
            allowed, message = _SETTLEMENT_ACCOUNTS[txn_type]
            account_type = getattr(effective("payment_account"), "account_type", None)
            if account_type is not None and account_type.title not in allowed:
                raise ValidationError({"payment_account": message})

        # A sales receipt is a cash sale: it needs a method and a bank account
        # for the cash to land in (the live screen filters deposit-to by Bank).
        if txn_type == RecurringTxnTypeChoices.SALES_RECEIPT:
            deposit_to = effective("payment_account")
            if deposit_to is None:
                raise ValidationError(
                    {"deposit_to": "A recurring sales receipt needs a deposit account."}
                )
            account_type = getattr(deposit_to, "account_type", None)
            if account_type is not None and account_type.title != "Bank":
                raise ValidationError(
                    {"deposit_to": "Receipts must be deposited into a bank account."}
                )
            method = effective("payment_method")
            if method is None:
                raise ValidationError(
                    {"payment_method": "A recurring sales receipt needs a payment method."}
                )
            if method.status != PaymentMethodStatusChoices.ACTIVE:
                raise ValidationError(
                    {"payment_method": "That payment method is no longer active."}
                )

        # A payment is charged to a stored method, so it needs one too.
        if txn_type == RecurringTxnTypeChoices.PAYMENT:
            method = effective("payment_method")
            if method is None:
                raise ValidationError(
                    {"payment_method": "A recurring payment needs a payment method."}
                )
            if method.status != PaymentMethodStatusChoices.ACTIVE:
                raise ValidationError(
                    {"payment_method": "That payment method is no longer active."}
                )

        # The real expense screen hard-requires a payment method, so a template
        # without one cannot produce a valid expense; and an inactive method
        # would fail at fire time rather than at save.
        if txn_type == RecurringTxnTypeChoices.EXPENSE:
            method = effective("payment_method")
            if method is None:
                raise ValidationError(
                    {"payment_method": "A recurring expense needs a payment method."}
                )
            if method.status != PaymentMethodStatusChoices.ACTIVE:
                raise ValidationError(
                    {"payment_method": "That payment method is no longer active."}
                )

        # A bill is an unpaid liability, so it needs the two things the real Bill
        # screen also refuses to save without: terms (which derive the due date,
        # and therefore A/P aging) and a store. Without them a template can be
        # saved but can never materialize a valid bill — reject it here rather
        # than let it fail every time it fires.
        if txn_type == RecurringTxnTypeChoices.BILL:
            if not effective("terms"):
                raise ValidationError(
                    {"terms": "A recurring bill needs payment terms."}
                )
            if not effective("warehouse"):
                raise ValidationError({"warehouse": "A recurring bill needs a store."})

        # Same reasoning as the bill: the real estimate screen refuses to submit
        # without a store, so a template lacking one cannot produce a valid
        # estimate however often it fires.
        if txn_type == RecurringTxnTypeChoices.ESTIMATE and not effective("warehouse"):
            raise ValidationError({"warehouse": "A recurring estimate needs a store."})

        # we/credit-notes hard-fails without a warehouse, so a template lacking
        # one could be saved yet never fire.
        if txn_type == RecurringTxnTypeChoices.CREDIT_MEMO and not effective("warehouse"):
            raise ValidationError(
                {"warehouse": "A recurring credit memo needs a store."}
            )

        if txn_type == RecurringTxnTypeChoices.INVOICE:
            for field in ("discount", "shipping_fee", "deposit"):
                value = effective(field)
                if value is not None and Decimal(str(value)) < 0:
                    raise ValidationError({field: "Must not be negative."})

            # A deposit has to be booked somewhere. The real invoice screen
            # requires a receivable account whenever deposit > 0; without one
            # every firing would produce an unbookable invoice.
            deposit = effective("deposit")
            if deposit and Decimal(str(deposit)) > 0 and not effective("payment_account"):
                raise ValidationError(
                    {"deposit_to": "A deposit needs an account to book it into."}
                )

            if lines is not None:
                subtotal = sum(
                    (Decimal(str(self._line_amount(line))) for line in lines),
                    Decimal("0"),
                )
                discount = effective("discount")
                if discount and Decimal(str(discount)) > subtotal:
                    raise ValidationError(
                        {"discount": "The discount cannot exceed the line subtotal."}
                    )
                # The real invoice screen refuses to save an inventory-tracked
                # product without a warehouse; a services-only invoice (the
                # common recurring case) saves without one, matching it.
                if not effective("warehouse"):
                    for index, line in enumerate(lines):
                        product = line.get("product")
                        # `tracks_stock()`, not the raw flag: production holds
                        # 20 services with is_inventory=True, and every one of
                        # them would fail this check and block a services-only
                        # template for want of a store it does not need.
                        if product is not None and product.tracks_stock():
                            raise ValidationError(
                                {
                                    "warehouse": (
                                        f"Line {index + 1} is an inventory-tracked "
                                        "product, so this template needs a store."
                                    )
                                }
                            )

        # Sales-side documents are product-only. Storing a category line on one
        # is silent data loss, not just an oddity: the edit screens filter to
        # line_type == "ITEM" on hydration, so the row would disappear from the
        # form and then be dropped by the next replace-all save.
        product_only = txn_type in (
            RecurringTxnTypeChoices.REFUND_RECEIPT,
            RecurringTxnTypeChoices.ESTIMATE,
            RecurringTxnTypeChoices.PAYMENT,
            RecurringTxnTypeChoices.INVOICE,
            RecurringTxnTypeChoices.SALES_RECEIPT,
            RecurringTxnTypeChoices.CREDIT_MEMO,
        )
        label = {
            RecurringTxnTypeChoices.REFUND_RECEIPT: "a refund receipt",
            RecurringTxnTypeChoices.PAYMENT: "a payment",
            RecurringTxnTypeChoices.INVOICE: "an invoice",
            RecurringTxnTypeChoices.SALES_RECEIPT: "a sales receipt",
            RecurringTxnTypeChoices.CREDIT_MEMO: "a credit memo",
        }.get(txn_type, "an estimate")
        if lines is not None:
            for index, line in enumerate(lines):
                line_type = line.get("line_type")
                if (
                    txn_type == RecurringTxnTypeChoices.DEPOSIT
                    and line_type == RecurringLineTypeChoices.ITEM
                ):
                    raise ValidationError(
                        {"lines": f"Line {index + 1}: a deposit takes fund rows only."}
                    )
                if product_only and line_type == RecurringLineTypeChoices.CATEGORY:
                    raise ValidationError(
                        {"lines": f"Line {index + 1}: {label} takes product lines only."}
                    )
                if line_type == RecurringLineTypeChoices.CATEGORY and not line.get(
                    "charter_account"
                ):
                    raise ValidationError(
                        {"lines": f"Line {index + 1}: a category line needs an account."}
                    )
                if line_type == RecurringLineTypeChoices.ITEM and not line.get("product"):
                    raise ValidationError(
                        {"lines": f"Line {index + 1}: an item line needs a product."}
                    )
                # Direction comes from the txn_type, never from a negative
                # number. All three money/count fields need this, not just
                # amount: a negative quantity reaches update_quantity() at fire
                # time and DECREMENTS stock on a document that nominally adds it.
                for field in ("amount", "quantity", "rate"):
                    value = line.get(field)
                    if value is not None and Decimal(str(value)) < 0:
                        raise ValidationError(
                            {"lines": f"Line {index + 1}: {field} must be positive."}
                        )

        if template_type != RecurringTemplateTypeChoices.UNSCHEDULED:
            if not effective("frequency"):
                raise ValidationError(
                    {"frequency": "A scheduled or reminder template needs a frequency."}
                )
            if not effective("start_date"):
                raise ValidationError(
                    {"start_date": "A scheduled or reminder template needs a start date."}
                )

            # Range checks. The model's PositiveIntegerFields already reject
            # negatives, but not 0 or an out-of-range day/weekday — and the
            # client's `Number(x) || fallback` coercion lets those through.
            # Only the VALUES are checked, never the presence: a REMINDER
            # template legitimately posts untouched MONTHLY defaults.
            interval_count = effective("interval_count")
            if interval_count is not None and interval_count < 1:
                raise ValidationError(
                    {"interval_count": "Repeat every must be at least 1."}
                )

            day_of_month = effective("day_of_month")
            if day_of_month is not None and not 1 <= day_of_month <= 31:
                raise ValidationError(
                    {"day_of_month": "Day of month must be between 1 and 31."}
                )

            weekday = effective("weekday")
            if weekday is not None and not 0 <= weekday <= 6:
                raise ValidationError(
                    {"weekday": "Weekday must be between 0 (Monday) and 6 (Sunday)."}
                )

            end_type = effective("end_type", RecurringEndTypeChoices.NONE)
            if end_type == RecurringEndTypeChoices.BY_DATE:
                end_date = effective("end_date")
                if not end_date:
                    raise ValidationError(
                        {"end_date": "Select an end date, or change the end condition."}
                    )
                start_date = effective("start_date")
                if start_date and end_date <= start_date:
                    raise ValidationError(
                        {"end_date": "The end date must be after the start date."}
                    )
            if end_type == RecurringEndTypeChoices.AFTER_COUNT:
                occurrences = effective("end_after_occurrences")
                if not occurrences:
                    raise ValidationError(
                        {"end_after_occurrences": "Enter how many occurrences to produce."}
                    )
                if occurrences < 1:
                    raise ValidationError(
                        {"end_after_occurrences": "Occurrences must be at least 1."}
                    )
        return attrs

    # ---- persistence -----------------------------------------------------

    def _company(self):
        return self.context["request"].user.get_active_company()

    def _employee(self):
        user = self.context["request"].user
        try:
            return user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            return None

    @staticmethod
    def _line_amount(line):
        """Authoritative amount for a line: quantity x rate on an item line.

        Client-supplied totals are advisory only. The frontends compute line
        money with ``toFixed(3)`` while the ledger is 2dp, so a trusted client
        figure will not reconcile. Category lines have no quantity or rate, so
        their amount is taken as given.
        """
        quantity, rate = line.get("quantity"), line.get("rate")
        if line.get("line_type") == RecurringLineTypeChoices.ITEM and None not in (
            quantity,
            rate,
        ):
            return Decimal(str(quantity)) * Decimal(str(rate))
        return line.get("amount") or 0

    def _write_lines(self, template, lines_data, company):
        RecurringTemplateLine.objects.bulk_create(
            [
                RecurringTemplateLine(
                    template=template,
                    company=company,
                    position=line.get("position", index),
                    line_type=line["line_type"],
                    description=line.get("description"),
                    quantity=line.get("quantity"),
                    rate=line.get("rate"),
                    amount=self._line_amount(line),
                    is_billable=line.get("is_billable", False),
                    charter_account=line.get("charter_account"),
                    product=line.get("product"),
                    tax=line.get("tax"),
                    customer=line.get("customer"),
                    supplier=line.get("supplier"),
                    payment_method=line.get("payment_method"),
                    reference_number=line.get("reference_number"),
                )
                for index, line in enumerate(lines_data)
            ]
        )

    def _refresh_derived(self, template):
        """Recompute the cached total and the first Next Date from current state.

        Shipping and discount are document-level money inputs (INVOICE), zero
        everywhere else, so folding them in changes nothing for other types.
        The deposit is money already paid — it moves due_total, not the total.
        """
        subtotal, tax = compute_totals(template.lines.all(), template.tax_kind)
        template.total_amount = (
            subtotal
            + tax
            + (template.shipping_fee or 0)
            - (template.discount or 0)
            # Cash back leaves the deposit again, so it REDUCES the total --
            # the only type where an extra amount subtracts.
            - (template.cash_back_amount or 0)
        )
        # Only (re)seed Next Date before the first run; the generation job owns it after.
        if template.previous_run_date is None:
            template.next_run_date = scheduling.compute_first_run_date(template)
        template.save(update_fields=["total_amount", "next_run_date", "updated_at"])

    def _link_files(self, template, file_uids, description, company):
        """Attach already-uploaded files to the template.

        Files are uploaded through we/attachments first; only their uids reach
        this endpoint, which is JSON-only. Absent means "leave unchanged" so a
        PATCH that omits the key cannot silently detach everything; an explicit
        empty list clears the links.
        """
        if file_uids is None:
            return
        FileItemConnector.objects.filter(recurring_template=template).delete()
        if file_uids:
            FileService.create_file_item_connector(
                file_uids=file_uids,
                description=description or "",
                company=company,
                model_kind=FileItemConnectorModelKindChoices.RECURRING_TEMPLATE,
                object=template,
            )

    @transaction.atomic
    def create(self, validated_data):
        company = self._company()
        lines_data = validated_data.pop("lines", [])
        file_uids = validated_data.pop("file_uids", None)
        file_description = validated_data.pop("file_description", "")
        template = RecurringTemplate.objects.create(
            company=company,
            created_by=self._employee(),
            **validated_data,
        )
        self._write_lines(template, lines_data, company)
        self._link_files(template, file_uids, file_description, company)
        self._refresh_derived(template)
        return template

    @transaction.atomic
    def update(self, instance, validated_data):
        company = self._company()
        lines_data = validated_data.pop("lines", None)
        file_uids = validated_data.pop("file_uids", None)
        file_description = validated_data.pop("file_description", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()
            self._write_lines(instance, lines_data, company)

        self._link_files(instance, file_uids, file_description, company)
        self._refresh_derived(instance)
        return instance


class PrivateWeRecurringTemplateUseSerializer(Serializer):
    """Input for the template 'Use' action (generate a bill now)."""

    bill_date = DateField(required=False)
    send_email = BooleanField(required=False, default=False)
