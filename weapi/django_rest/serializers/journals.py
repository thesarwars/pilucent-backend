from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from datetime import date
from rest_framework.serializers import (
    ModelSerializer,
    ListField,
    CharField,
    FileField,
    JSONField,
    DictField,
    BooleanField,
    DecimalField,
    ValidationError,
)
from agencyio.models import AgencyTax
from accounts.models import ChartOfAccount
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from common.django_rest.helpers.decorators import set_auditlog_actor

from customerio.models import Customer
from customerio.django_rest.serializers.common import PrivateCustomerSlimSerializer

from fileroomio.choices import (
    FileItemKindChoices,
    FileItemStatusChoices,
    FileItemConnectorModelKindChoices,
)
from fileroomio.models import FileItem, FileItemConnector

from journalio.choices import (
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
)
from journalio.models import JournalEntry, JournalEntryConnector
from journalio.django_rest.serializers.common import (
    JournalEntryConnectorListSerializer,
    PrivateJournalEntryConnectorSlimSerializer,
    PrivateJournalEntrySlimSerializer,
)

from supplierio.models import Supplier
from supplierio.django_rest.serializers.common import PrivateSupplierSlimSerializer

from tagio.choices import TagKindChoices, TagStatusChoices
from tagio.models import Tag, TagConnector

from wirehouseio.models import Warehouse

from common.django_rest.helpers.reconciliation_guard import assert_not_reconciled
from weapi.django_rest.helpers.journal_entry_posting import (
    leg_amount,
    move_leg_balance,
)

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from decimal import Decimal


# Fields a client may set on a journal line through `PATCH /we/journals/{uid}`.
#
# `journal_items` is a raw `JSONField`, so whatever the payload happened to name
# used to be handed straight to `.update(**item)`. Everything absent from this
# set is either derived (`total`, `last_balance`), owned by the posting engine
# (`request_kind`, `transaction_id`, `parent`, the four document-line FKs) or
# owned by the reconciliation flow (`reconciliation`, `cleared_on`) -- and a
# client able to name that last pair could mark a line reconciled without ever
# opening a reconciliation, or strand it on a session that undo will then skip.
# `date` is deliberately NOT here. Header-authoritative dating (2026-09-02)
# makes `JournalEntry.date` the truth and every leg inherit it, which is what
# `create_journal_entry_connector` has always done by default. This was the only
# path that could give a leg a date of its own, and a leg dated away from its
# header puts one document in two accounting periods -- so each period is
# individually unbalanced, and no period-scoped balance sheet can ever tie out.
# Change the entry's date instead; the legs follow.
EDITABLE_JOURNAL_LINE_FIELDS = frozenset(
    {"debit", "credit", "kind", "description"}
)


class PrivateWeJournalEntryListSerializer(ModelSerializer):
    journal_items = PrivateJournalEntryConnectorSlimSerializer(
        many=True, write_only=True
    )
    files = ListField(required=False, allow_null=True)
    tag_title_list = JSONField(required=False, write_only=True)
    journal_items_set = JournalEntryConnectorListSerializer(
        many=True, source="journalentryconnector_set", read_only=True
    )

    class Meta:
        model = JournalEntry
        fields = [
            "uid",
            "date",
            "entry_number",
            "description",
            "amount",
            "status",
            "journal_items",
            "journal_items_set",
            "tag_title_list",
            "files",
            # "file_description",
        ]
        read_only_fields = ["uid"]

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        attrs["company"] = company
        return super().validate(attrs)

    @set_auditlog_actor
    def create(self, validated_data):
        journal_items = validated_data.pop("journal_items", [])
        files = validated_data.pop("files", None)
        tag_title_list = validated_data.pop("tag_title_list", None)
        # `kind` is not a client field and never was, so every entry written
        # here took the model default -- PURCHASE. Every other member of that
        # enum names the document an entry was posted from, and this one has no
        # document, so a hand-keyed entry read as a bill. Nothing looked until
        # the register's Type column did.
        validated_data["kind"] = JournalEntryKindChoices.JOURNAL_ENTRY
        journal_entry = JournalEntry.objects.create(**validated_data)

        if tag_title_list:
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.JOURNAL_ENTRY,
                        "company": validated_data["company"],
                    },
                )[0]
                for title in tag_title_list
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        journal_entry=journal_entry,
                    )
                    for tag_item in tag_items
                ]
            )

        for item in journal_items:
            co_acc = item.pop("account")

            item["journal"] = journal_entry
            item["account"] = co_acc

            # `update_opening_balance`'s second argument is add/subtract against
            # the stored balance in the account's *own* direction -- not an
            # accounting side (see its docstring). Hard-coding the opposite side
            # happens to land correctly on assets and expenses and is backwards
            # on every liability, equity and income account, where a debit
            # decreases the balance rather than increasing it. Derive it the way
            # the rest of the posting paths do.
            side = item["kind"]
            amount = Decimal(
                item["debit"]
                if side == JournalEntryConnectorKindChoices.DEBIT
                else item["credit"]
            )
            update_opening_balance(
                co_acc,
                balance_operation_for_action(action_for_side(co_acc.kind, side)),
                amount,
                0,
            )
            item["date"] = validated_data.get("date", date.today())

        JournalEntryConnector.objects.bulk_create(
            [JournalEntryConnector(**item) for item in journal_items]
        )
        if files:
            file_items = FileItem.objects.in_bulk(files, field_name="uid")
            # print('file_items', file_items.values())
            FileItemConnector.objects.bulk_create(
                [
                    FileItemConnector(
                        model_kind=FileItemConnectorModelKindChoices.JOURNAL_ENTRY,
                        journal_entry=journal_entry,
                        file_item=file_uid,
                    )
                    for file_uid in file_items.values()
                ]
            )
        return journal_entry


class PrivateWeJournalEntryDetailsSerializer(ModelSerializer):
    journal_items = JSONField(
        required=False,
        write_only=True,
    )
    journal_item = JournalEntryConnectorListSerializer(
        many=True, source="journalentryconnector_set", read_only=True
    )
    tag_title_list = JSONField(required=False, write_only=True)
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(required=False)

    class Meta:
        model = JournalEntry
        fields = [
            "uid",
            "date",
            "entry_number",
            "description",
            "amount",
            "status",
            "journal_items",
            "journal_item",
            "tag_title_list",
            "files",
            "file_description",
        ]
        read_only_fields = ["uid", "status", "journal_item"]

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()
        attrs["company"] = company
        return super().validate(attrs)

    @staticmethod
    def _scoped_relation(model, uid, company, field_name, required=False):
        """Resolve one related object within `company`, or fail as a 400.

        Three of the five relations here were a bare `.get(uid=...)` with no
        company clause, so a uid belonging to another tenant resolved and was
        written onto the line. A missing or malformed uid raised `DoesNotExist`
        or `ValueError` and surfaced as a 500; it is a client error and now
        reads as one.
        """
        if not uid:
            if required:
                raise ValidationError({field_name: "This field is required."})
            return None
        try:
            return model.objects.get(uid=uid, company=company)
        except (model.DoesNotExist, DjangoValidationError, ValueError):
            raise ValidationError(
                {field_name: f"No {model.__name__} {uid} for this company."}
            )

    @set_auditlog_actor
    def update(self, instance, validated_data):
        # The most direct instance of the gap: a bookkeeper editing a hand-keyed
        # entry whose bank leg a closed statement already signed off. The line
        # loop below rewrites `debit`, `credit`, `kind`, `date` AND `account` on
        # the existing rows through a queryset `.update()`, so the ticked leg can
        # even change which account it belongs to while still pointing at the
        # session that cleared it.
        assert_not_reconciled(
            JournalEntry.objects.filter(pk=instance.pk), action="change"
        )

        tag_titles = validated_data.pop("tag_title_list", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        journal_items = validated_data.pop("journal_items", [])
        instance = super().update(instance, validated_data)
        if tag_titles:
            TagConnector.objects.filter(journal_entry=instance).delete()
            tag_items = [
                Tag.objects.get_or_create(
                    title=title,
                    defaults={
                        "status": TagStatusChoices.ACTIVE,
                        "kind": TagKindChoices.JOURNAL_ENTRY,
                        "company": instance.company,
                    },
                )[0]
                for title in tag_titles
            ]
            TagConnector.objects.bulk_create(
                [
                    TagConnector(
                        tag=tag_item,
                        journal_entry=instance,
                    )
                    for tag_item in tag_items
                ]
            )
        company = instance.company
        for item in journal_items:
            # Built from scratch rather than filtered in place: `item` is raw
            # client JSON and anything outside the allow-list must not reach the
            # model. See EDITABLE_JOURNAL_LINE_FIELDS.
            fields = {
                key: value
                for key, value in item.items()
                if key in EDITABLE_JOURNAL_LINE_FIELDS
            }

            side = fields.get("kind")
            if side is not None and side not in JournalEntryConnectorKindChoices.values:
                raise ValidationError(
                    {"journal_items": f"{side!r} is not a posting side."}
                )

            fields["journal"] = instance
            fields["account"] = self._scoped_relation(
                ChartOfAccount, item.get("account_uid"), company, "account_uid",
                required=True,
            )
            fields["supplier"] = self._scoped_relation(
                Supplier, item.get("supplier_uid"), company, "supplier_uid"
            )
            fields["customer"] = self._scoped_relation(
                Customer, item.get("customer_uid"), company, "customer_uid"
            )
            fields["warehose"] = self._scoped_relation(
                Warehouse, item.get("warehouse_uid"), company, "warehouse_uid"
            )
            fields["tax"] = self._scoped_relation(
                AgencyTax, item.get("tax_uid"), company, "tax_uid"
            )

            if line_uid := item.get("uid"):
                # Scoped to this entry, not to the whole table. Without the
                # `journal=` clause any uid in `journalio_journalentryconnector`
                # resolved -- and journalio carries no RLS backstop -- so this
                # rewrote other companies' ledger legs, reparenting them onto
                # the caller's entry.
                existing = (
                    JournalEntryConnector.objects.filter(
                        uid=line_uid, journal=instance
                    )
                    .select_related("account")
                    .first()
                )
                if existing is None:
                    raise ValidationError(
                        {
                            "journal_items": (
                                f"No line {line_uid} on this journal entry."
                            )
                        }
                    )

                # Read before the write: `.update()` is a queryset call, so the
                # old figures are gone the moment it runs and the balance they
                # moved could never be found again.
                #
                # `update_opening_balance` appeared exactly once in this file --
                # in `create` -- so amending an entry rewrote the legs and left
                # every account's stored balance asserting the pre-edit figure.
                # Back the old leg out against its OLD account, because
                # `account` is itself editable here and a line moved from one
                # account to another has to be taken off the first.
                move_leg_balance(
                    existing.account,
                    existing.kind,
                    leg_amount(existing.debit, existing.credit),
                    undo=True,
                )

                JournalEntryConnector.objects.filter(
                    uid=line_uid, journal=instance
                ).update(**fields)

                # Fields the payload left out keep their existing values, so the
                # new balance move has to read through to them rather than
                # assume the client sent a whole line.
                move_leg_balance(
                    fields["account"],
                    fields.get("kind", existing.kind),
                    leg_amount(
                        fields.get("debit", existing.debit),
                        fields.get("credit", existing.credit),
                    ),
                )
            else:
                JournalEntryConnector.objects.create(**fields)
                move_leg_balance(
                    fields["account"],
                    fields.get("kind"),
                    leg_amount(fields.get("debit"), fields.get("credit")),
                )

        if files:
            FileItemConnector.objects.filter(
                model_kind=FileItemConnectorModelKindChoices.JOURNAL_ENTRY,
                journal_entry=instance,
            ).delete()
            file_items = [
                FileItem.objects.create(
                    company=instance.company,
                    status=FileItemStatusChoices.PUBLISHED,
                    file=file,
                    description=file_description,
                    kind=FileItemKindChoices.PDF,
                )
                for file in files
            ]

            FileItemConnector.objects.bulk_create(
                [
                    FileItemConnector(
                        model_kind=FileItemConnectorModelKindChoices.JOURNAL_ENTRY,
                        journal_entry=instance,
                        file_item=file_item,
                    )
                    for file_item in file_items
                ]
            )

        return instance


class PrivateWeUndepositedFundsJournalEntryConnectorSerializer(ModelSerializer):
    """
    Serializer for JournalEntryConnector with journal entry data for Undeposited Funds.
    Returns connector data along with related journal entry information.
    """

    journal = PrivateJournalEntrySlimSerializer(read_only=True)
    is_deposit = BooleanField(source="journal.is_deposit", read_only=True)
    account = PrivateChartOfAccountSlimSerializer(read_only=True)
    supplier = PrivateSupplierSlimSerializer(read_only=True)
    customer = PrivateCustomerSlimSerializer(read_only=True)

    class Meta:
        model = JournalEntryConnector
        fields = [
            "uid",
            "date",
            "debit",
            "credit",
            "kind",
            "supplier",
            "customer",
            "account",
            "journal",
            "is_deposit",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Return debit value if it's greater than 0, otherwise return credit value
        data["amount"] = instance.debit if instance.debit > 0 else instance.credit
        return data
