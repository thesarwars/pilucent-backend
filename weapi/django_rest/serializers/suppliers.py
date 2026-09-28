from decimal import Decimal

import pandas as pd
import numpy as np
from django.db import transaction
from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    CharField,
    ValidationError,
    FileField,
    ListField,
    ChoiceField,
    IntegerField,
)

from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices
from addressio.models import Address, AddressConnector
from addressio.django_rest.serializers.common import PrivateAddressSerializer

from common.django_rest.helpers.countries import COUNTRIES

from currencyio.django_rest.serializers.common import PrivateCurrencySlimSerializer
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.decorators import set_auditlog_actor

from accounts.models import ChartOfAccount

from fileroomio.choices import (
    FileItemConnectorModelKindChoices,
    FileItemKindChoices,
    FileItemStatusChoices,
)
from fileroomio.models import FileItemConnector, FileItem

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService


from purchaseio.models import Purchase

from weapi.django_rest.helpers.opening_balance_documents import (
    opening_balance_document,
)
from purchaseio.choices import PurchaseStatus
from supplierio.models import Supplier
from supplierio.choices import SupplierkindChoices, SupplierStatusChoices

from termio.models import TermConnector, Term
from termio.choicess import TermKindChoices
from termio.django_rest.serializers.common import PrivateTermSlimSerializer


class PrivateWeSupplierListSerializer(ModelSerializer):
    street = CharField(write_only=True, required=False)
    city = CharField(write_only=True, required=False)
    province = CharField(write_only=True, required=False)
    postal_code = CharField(write_only=True, required=False)
    country = ChoiceField(write_only=True, required=False, choices=COUNTRIES)
    term = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    address = PrivateAddressSerializer(
        source="addressconnector_set.first.address", read_only=True
    )
    # Attachment realated fields
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    # Field for chart of account (expense or asset account) for opening balance
    chart_of_account = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all(),
        write_only=True,
        required=False,
    )

    file_description = CharField(write_only=True, required=False)
    file_count = IntegerField(source="get_file_item_count", read_only=True)
    total_credit = CharField(source="get_credit_count", read_only=True)

    class Meta:
        model = Supplier
        fields = [
            "uid",
            "currency",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "display_name",
            "suffix",
            "company_name",
            "email",
            "telephone_number",
            "mobile_number",
            "fax",
            "website",
            "business_id",
            "billing_rate",
            "account_number",
            "date",
            "opening_balance",
            "status",
            "kind",
            "description",
            "country",
            "street",
            "city",
            "province",
            "postal_code",
            "term",
            "address",
            "files",
            "file_description",
            "image",
            "file_count",
            "total_credit",
            "chart_of_account",
            "created_at",
            "updated_at",
        ]

        # Indented into Meta -- see the note in customers.py; the same block
        # was misplaced here and had the same effect.
        #
        # `kind` is deliberately NOT restored to this list. The model declares
        # it nullable with no default, so making it read-only would write NULL
        # on every supplier created through the API -- a silent regression, and
        # unlike `status` there is no guard being bypassed by its being
        # writable. Honouring the original intent there would cost more than it
        # buys.
        read_only_fields = [
            "uid",
            "date",
            "status",
            "address",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        company = self.context["request"].user.get_active_company()

        # Subscripted rather than `.get()`, so a create that simply omitted the
        # field raised KeyError -- an unhandled 500 on a payload the serializer
        # itself accepts, since `email` is not required.
        #
        # And blank is not a duplicate. `filter(email="")` matches every other
        # supplier that also has none -- production holds 7 -- so the second one
        # entered was refused as a duplicate of the first.
        email = (attrs.get("email") or "").strip()
        if email and (
            Supplier.objects.filter(email__iexact=email, company=company)
            .exclude(status=SupplierStatusChoices.REMOVED)
            .exists()
        ):
            raise ValidationError(
                "Supplier with this email already exists in your company"
            )
        attrs["company"] = company
        return super().validate(attrs)

    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        opening_balance = validated_data.get("opening_balance", 0)
        chart_of_account = validated_data.pop("chart_of_account", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        term = validated_data.pop("term", None)
        address_data = {
            "country": validated_data.pop("country", "us"),
            "street": validated_data.pop("street", None),
            "city": validated_data.pop("city", None),
            "province": validated_data.pop("province", None),
            "postal_code": validated_data.pop("postal_code", None),
            "company": validated_data["company"],
            "status": AddressStatusChoices.ACTIVE,
        }
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
                "Opening Balance Equity",
            ],
            company,
        )
        accounts_payable = chart_of_accounts.get("Accounts Payable (A/P)")
        chart_of_account = chart_of_accounts.get("Opening Balance Equity")
        connector_data = []
        address = Address.objects.create(**address_data)

        supplier = Supplier.objects.create(**validated_data)

        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.SUPPLIER,
                supplier=supplier,
                term=term,
            )

        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.SUPPLIER,
            supplier=supplier,
            address=address,
        )

        if files:
            file_items = [
                FileItem.objects.create(
                    company=validated_data["company"],
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
                        model_kind=FileItemConnectorModelKindChoices.CUSTOMER,
                        supplier=supplier,
                        file_item=file_item,
                    )
                    for file_item in file_items
                ]
            )
        # `!= 0`, not `> 0`. A NEGATIVE opening balance -- a prepayment or an
        # unused vendor credit carried in, which Standard §3 calls legitimate
        # and §12.12 routine -- was written to the row by `objects.create()`
        # above and then posted nowhere at all: no document, no journal entry,
        # no A/P movement. The subledger moved and the ledger did not.
        if opening_balance and float(opening_balance) != 0:
            amount = abs(Decimal(str(opening_balance)))
            purchase, is_credit = opening_balance_document(
                supplier, validated_data["company"], opening_balance,
                date=supplier.date,
            )

            # A vendor who owes US money is a debit to payables, so both legs
            # invert. Resolved from the side rather than from a literal, for the
            # reason the OBE comment below gives: `"addition"` maps to a
            # different side per account kind, and A/P's kind comes from an
            # editable account type -- the reason `repair_control_account_types`
            # exists at all.
            payable_side = (
                JournalEntryConnectorKindChoices.DEBIT
                if is_credit
                else JournalEntryConnectorKindChoices.CREDIT
            )
            payable_action = action_for_side(accounts_payable.kind, payable_side)
            update_opening_balance(
                accounts_payable,
                balance_operation_for_action(payable_action),
                amount,
                0,
            )
            # DEBIT, resolved from the side rather than assumed. Both legs
            # used the literal "addition", and `get_debit_or_credit` maps that
            # to a different side per kind -- it landed on DEBIT only because
            # the old account was an EXPENSE. Opening Balance Equity is
            # EQUITIES, where "addition" is a CREDIT, so keeping the literal
            # puts both legs on the credit side: measured, the entry came out
            # out by -1800.00 on a 900.00 balance. Same fault `e7f2f8de` fixed
            # in the bank-rule engine.
            obe_action = action_for_side(
                chart_of_account.kind,
                JournalEntryConnectorKindChoices.CREDIT
                if is_credit
                else JournalEntryConnectorKindChoices.DEBIT,
            )
            update_opening_balance(
                chart_of_account,
                balance_operation_for_action(obe_action),
                amount,
                0,
            )
            # make journal entry for that

            connector_data.extend(
                [
                    (
                        accounts_payable,
                        payable_action,
                        amount,
                        accounts_payable.opening_balance,
                        None,
                    ),
                    (
                        chart_of_account,
                        obe_action,
                        amount,
                        chart_of_account.opening_balance,
                        None,
                    ),
                ]
            )

            journal_entry = JournalEntryService.create_journal_entry(
                amount=amount,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PURCHASE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=purchase,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=amount,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=supplier,
                created_by=user.get_employee(),
            )

        return supplier


class PrivateWeSupplierDetailsSerializer(ModelSerializer):
    country = ChoiceField(write_only=True, required=False, choices=COUNTRIES)
    street = CharField(write_only=True, required=False)
    city = CharField(write_only=True, required=False)
    province = CharField(write_only=True, required=False)
    postal_code = CharField(write_only=True, required=False)
    address = PrivateAddressSerializer(
        source="addressconnector_set.first.address", read_only=True
    )
    term_items = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
    )
    term = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Supplier
        fields = [
            "uid",
            "currency",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "display_name",
            "suffix",
            "company_name",
            "email",
            "telephone_number",
            "mobile_number",
            "fax",
            "website",
            "business_id",
            "billing_rate",
            "account_number",
            "date",
            "opening_balance",
            "status",
            "kind",
            "description",
            "country",
            "street",
            "city",
            "province",
            "postal_code",
            "address",
            "term_items",
            "term",
            "image",
        ]

        # Indented into Meta -- see the note in customers.py; the same block
        # was misplaced here and had the same effect.
        #
        # `kind` is deliberately NOT restored to this list. The model declares
        # it nullable with no default, so making it read-only would write NULL
        # on every supplier created through the API -- a silent regression, and
        # unlike `status` there is no guard being bypassed by its being
        # writable. Honouring the original intent there would cost more than it
        # buys.
        # `opening_balance` is the A/P subledger. Editing a vendor was writing
        # it straight to the row with no `Purchase`, no journal entry and no
        # control-account movement -- a subledger that moves while the ledger
        # does not. It stays writable on CREATE, which is how a migrated balance
        # is set and is the only path that also posts the entry. DRF drops a
        # read-only field silently, so a form that round-trips the whole object
        # keeps working; the value is simply ignored.
        read_only_fields = [
            "uid",
            "date",
            "status",
            "address",
            "terms",
            "files",
            "opening_balance",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        country = validated_data.pop("country", None)
        street = validated_data.pop("street", None)
        city = validated_data.pop("city", None)
        province = validated_data.pop("province", None)
        postal_code = validated_data.pop("postal_code", None)
        term = validated_data.pop("term", None)

        instance = super().update(instance, validated_data)

        if country or street or city or province or postal_code:
            address_connector = instance.addressconnector_set.first()
            if address_connector:
                address = address_connector.address
            else:
                address = Address.objects.create(
                    country=country or "us",
                    street=street or "",
                    city=city or "",
                    province=province or "",
                    postal_code=postal_code or "",
                    company=instance.company,
                    status=AddressStatusChoices.ACTIVE,
                )
                AddressConnector.objects.create(
                    kind=AddressConnectorKindCoices.SUPPLIER,
                    supplier=instance,
                    address=address,
                )
            if country:
                address.country = country
            if street:
                address.street = street
            if city:
                address.city = city
            if province:
                address.province = province
            if postal_code:
                address.postal_code = postal_code
            address.save()

        if term is not None:
            term_connector = instance.termconnector_set.first()
            if term_connector:
                term_connector.term = term
                term_connector.save()
            else:
                TermConnector.objects.create(
                    kind=TermKindChoices.SUPPLIER,
                    supplier=instance,
                    term=term,
                )

        return super().update(instance, validated_data)


class PrivateWeSupplierBulkCreateSerializer(ModelSerializer):
    supplier_file = FileField(write_only=True)

    class Meta:
        model = Supplier
        fields = ["supplier_file"]

    def validate(self, attrs):
        if not attrs.get("supplier_file"):
            raise ValidationError({"message": "File is required."})

        if not attrs["supplier_file"].name.endswith((".csv", ".xlsx", ".xls")):
            raise ValidationError({"message": "File must be a CSV or Excel file."})

        return super().validate(attrs)
    
    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = self.context["request"].user.get_active_company()
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Payable (A/P)",
                "Opening Balance Equity",
            ],
            company,
        )
        accounts_payable = chart_of_accounts.get("Accounts Payable (A/P)")
        misc_account = chart_of_accounts.get("Opening Balance Equity")

        file = validated_data.pop("supplier_file")
        df = pd.read_excel(file)

        df = df.fillna(
            value={
                "currency": "USD",
                "billing_rate": 0.00,
                "opening_balance": 0.00,
            }
        ).replace({np.nan: None})

        suppliers = []
        addresses = []
        invalid_rows = []
        invalid_mail = []
        supplier_balances = []  # Store opening balances with supplier indexes

        for i, row in df.iterrows():
            if not row.get("first_name"):
                invalid_rows.append(i + 1)
                continue
            if Supplier.objects.filter(
                email=row.get("email"), company=company
            ).exists():
                invalid_mail.append(i + 1)
                continue
            supplier_data = {
                "currency": row.get("currency"),
                "title": row.get("title"),
                "first_name": row.get("first_name"),
                "middle_name": row.get("middle_name"),
                "last_name": row.get("last_name"),
                "display_name": row.get("display_name"),
                "suffix": row.get("suffix"),
                "company_name": row.get("company_name"),
                "email": row.get("email"),
                "telephone_number": row.get("telephone_number"),
                "mobile_number": row.get("mobile_number"),
                "fax": row.get("fax"),
                "website": row.get("website"),
                "business_id": row.get("business_id"),
                "billing_rate": row.get("billing_rate"),
                "account_number": row.get("account_number"),
                "date": pd.to_datetime(row.get("date", pd.Timestamp.now())).date(),
                "opening_balance": row.get("opening_balance"),
                "status": SupplierStatusChoices.ACTIVE,
                "kind": SupplierkindChoices.PURCHASE,
                "description": row.get("description"),
                "company": company,
            }
            suppliers.append(Supplier(**supplier_data))

            address_data = {
                "country": row.get("country" or "us"),
                "street": row.get("street"),
                "city": row.get("city"),
                "province": row.get("province"),
                "postal_code": row.get("postal_code"),
                "company": company,
                "status": AddressStatusChoices.ACTIVE,
            }
            addresses.append(Address(**address_data))

            opening_balance = row.get("opening_balance", 0)
            # `!= 0` -- see the note at the single-create site. An import is the
            # likeliest place for a carried-in vendor credit to arrive.
            if opening_balance and float(opening_balance) != 0:
                # Just track the opening balance and supplier index
                supplier_balances.append(
                    {"index": len(suppliers) - 1, "amount": float(opening_balance)}
                )

        # First create all suppliers
        created_suppliers = Supplier.objects.bulk_create(suppliers)
        created_addresses = Address.objects.bulk_create(addresses)

        # Create address connectors
        address_connectors = [
            AddressConnector(
                kind=AddressConnectorKindCoices.SUPPLIER,
                supplier=supplier,
                address=address,
            )
            for supplier, address in zip(created_suppliers, created_addresses)
        ]
        AddressConnector.objects.bulk_create(address_connectors)

        # For each supplier with opening balance, create purchase and journal entry
        for balance_info in supplier_balances:
            supplier = created_suppliers[balance_info["index"]]
            signed = Decimal(str(balance_info["amount"]))
            amount = abs(signed)

            # Bill or vendor credit, whichever the sign says -- see the note at
            # the single-create site for why a negative is not a negative bill.
            purchase, is_credit = opening_balance_document(
                supplier, company, signed, date=supplier.date,
            )

            # Both legs invert on a credit, and both resolve from the side.
            payable_action = action_for_side(
                accounts_payable.kind,
                JournalEntryConnectorKindChoices.DEBIT
                if is_credit
                else JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                accounts_payable,
                balance_operation_for_action(payable_action),
                amount,
                0,
            )
            obe_action = action_for_side(
                misc_account.kind,
                JournalEntryConnectorKindChoices.CREDIT
                if is_credit
                else JournalEntryConnectorKindChoices.DEBIT,
            )
            update_opening_balance(
                misc_account, balance_operation_for_action(obe_action), amount, 0
            )

            # Prepare connector data for journal entry

            connector_data = [
                (
                    accounts_payable,
                    payable_action,
                    amount,
                    accounts_payable.opening_balance,
                    None,
                ),
                (
                    misc_account,
                    obe_action,
                    amount,
                    misc_account.opening_balance,
                    None,
                ),
            ]

            # Create journal entry using the service
            journal_entry = JournalEntryService.create_journal_entry(
                amount=amount,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PURCHASE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=purchase,
            )

            # Create journal entry connectors using the service
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=amount,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=supplier,
                created_by=user.get_employee(),
            )
        
       
        if invalid_rows:
            raise ValidationError(
                {
                    "message": f"First name is required at row numbers: {', '.join(map(str, invalid_rows))}"
                }
            )
        if invalid_mail:
            raise ValidationError(
                {
                    "message": f"Email addresses are already in use at row numbers: {', '.join(map(str, invalid_mail))}"
                }
            )

        return created_suppliers


class PrivateWeSupplierFileListSerializer(ModelSerializer):
    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "status",
            "file",
            "description",
            "created_at",
            "updated_at",
        ]


class PrivateWeSupplierFileDetailsSerializer(ModelSerializer):
    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "status",
            "file",
            "description",
            "created_at",
            "updated_at",
        ]

        # Indented into Meta -- see the note in customers.py; the same block
        # was misplaced here and had the same effect.
        #
        # `kind` is deliberately NOT restored to this list. The model declares
        # it nullable with no default, so making it read-only would write NULL
        # on every supplier created through the API -- a silent regression, and
        # unlike `status` there is no guard being bypassed by its being
        # writable. Honouring the original intent there would cost more than it
        # buys.
        read_only_fields = [
            "uid",
            "created_at",
            "updated_at",
        ]


class PrivateWeSupplierTransactionListSerializer(ModelSerializer):
    class Meta:
        model = Purchase
        fields = [
            "uid",
            "date",
            # "invoice_id",
            "status",
            "total",
            "is_bill",
            "created_at",
            "updated_at",
        ]


class PrivateWeSupplierPurchaseListSerializer(ModelSerializer):
    currency = PrivateCurrencySlimSerializer(source="get_currency")

    class Meta:
        model = Purchase
        fields = [
            "uid",
            "is_bill",
            "tax_kind",
            "total_tax",
            "total_vat",
            "total",
            "currency",
            "created_at",
            "updated_at",
        ]
