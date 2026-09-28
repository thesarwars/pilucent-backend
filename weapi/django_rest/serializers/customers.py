from decimal import Decimal

from datetime import datetime
import pandas as pd
import numpy as np

from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    CharField,
    FileField,
    ListField,
    ChoiceField,
    IntegerField,
    ValidationError,
)
from rest_framework.generics import get_object_or_404
from django.db import transaction
from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices
from addressio.models import Address, AddressConnector
from addressio.django_rest.serializers.common import PrivateAddressSerializer
from common.django_rest.helpers.id_generator import get_unique_id

from common.django_rest.helpers.decorators import set_auditlog_actor

from customerio.models import Customer
from customerio.choices import CustomerStatusChoices

from termio.models import TermConnector, Term
from termio.choicess import TermKindChoices
from termio.django_rest.serializers.common import PrivateTermSlimSerializer

from fileroomio.choices import (
    FileItemConnectorModelKindChoices,
    FileItemKindChoices,
    FileItemStatusChoices,
)
from fileroomio.models import FileItemConnector, FileItem

from common.django_rest.helpers.countries import COUNTRIES
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from weapi.django_rest.helpers.opening_balance_documents import (
    customer_opening_balance_document,
)

from journalio.choices import (
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from salesio.choices import SalesStatusChoices, SaleReceptKindChoices
from salesio.models import Sale


class PrivateWeCustomerListSerializer(ModelSerializer):
    street = CharField(write_only=True, required=False)
    city = CharField(write_only=True, required=False)
    province = CharField(write_only=True, required=False)
    postal_code = CharField(write_only=True, required=False)
    country = ChoiceField(write_only=True, required=False, choices=COUNTRIES)
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    terms = PrivateTermSlimSerializer(
        source="termconnector_set.first.term", required=False, read_only=True
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
    file_description = CharField(write_only=True, required=False)
    file_count = IntegerField(source="get_file_item_count", read_only=True)

    class Meta:
        model = Customer
        fields = [
            "uid",
            "currency",
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "company_name",
            "company_email",
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
            "description",
            "country",
            "street",
            "city",
            "province",
            "postal_code",
            "term_uid",
            "terms",
            "address",
            "payment_method",
            "delivery_option",
            # Attachment realted fields
            "files",
            "file_description",
            "file_count",
            "image",
            "created_at",
            "updated_at",
        ]

        # Indented into Meta. This block sat at class-body level, where DRF
        # never sees it, so every field below has been client-writable --
        # including `status`, which meant PATCH {"status": "INACTIVE"} retired a
        # customer while bypassing every CUST-151/152 guard the deactivate
        # endpoint enforces.
        #
        # `read_only_fields` only governs AUTO-GENERATED fields, so `address`,
        # `terms` and `files` are unaffected -- they are declared explicitly on
        # the serializer and keep the behaviour they already had. `files` in
        # particular stays write_only, so uploads are untouched. `date` is safe
        # because the model defaults it to today.
        read_only_fields = [
            "uid",
            "date",
            "status",
            "address",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        opening_balance = validated_data.get("opening_balance", 0)
        term = validated_data.pop("term_uid", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Receivable (A/R)",
                "Opening Balance Equity",
            ],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        service_account = chart_of_accounts.get("Opening Balance Equity")

        connector_data = []
        address_data = {
            "country": validated_data.pop("country", "us"),
            "street": validated_data.pop("street", None),
            "city": validated_data.pop("city", None),
            "province": validated_data.pop("province", None),
            "postal_code": validated_data.pop("postal_code", None),
            "company": validated_data["company"],
            "status": AddressStatusChoices.ACTIVE,
        }
        address = Address.objects.create(**address_data)
        customer = Customer.objects.create(**validated_data)
        if opening_balance != 0:
            sale = Sale.objects.create(
                invoice_id=get_unique_id(Sale, company.id, "invoice_id", "INV"),
                total=opening_balance,
                due_total=opening_balance,
                is_invoice=True,
                status=SalesStatusChoices.OPEN,
                customer=customer,
                created_by=user.get_employee(),
                company=company,
            )
            # Receivable amount
            update_opening_balance(
                receivable_account,
                "credit",
                opening_balance,
                0,
            )
            update_opening_balance(
                service_account,
                "credit",
                opening_balance,
                0,
            )

            connector_data.extend(
                [
                    (
                        receivable_account,
                        "addition",
                        opening_balance,
                        receivable_account.opening_balance,
                        None,
                    ),
                    (
                        service_account,
                        "addition",
                        opening_balance,
                        service_account.opening_balance,
                        None,
                    ),
                ]
            )

            journal_entry = JournalEntryService.create_journal_entry(
                amount=opening_balance,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.SALE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=sale,
            )
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=opening_balance,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                customer=customer,
                created_by=user.get_employee(),
            )

        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.CUSTOMER,
                customer=customer,
                term=term,
            )

        AddressConnector.objects.create(
            kind=AddressConnectorKindCoices.CUSTOMER,
            customer=customer,
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
                        customer=customer,
                        file_item=file_item,
                    )
                    for file_item in file_items
                ]
            )
        return customer


class PrivateWeCustomerDetailsSerializer(ModelSerializer):
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
    term_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Term.objects.filter(is_active=True),
        write_only=True,
        required=False,
    )
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(write_only=True, required=False)

    class Meta:
        model = Customer
        fields = [
            "uid",
            "currency",
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "company_name",
            "company_email",
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
            "description",
            "country",
            "street",
            "city",
            "province",
            "postal_code",
            "address",
            "term_items",
            "term_uid",
            "payment_method",
            "delivery_option",
            "description",
            "files",
            "file_description",
            "image",
            "created_at",
            "updated_at",
        ]

        # Indented into Meta. This block sat at class-body level, where DRF
        # never sees it, so every field below has been client-writable --
        # including `status`, which meant PATCH {"status": "INACTIVE"} retired a
        # customer while bypassing every CUST-151/152 guard the deactivate
        # endpoint enforces.
        #
        # `read_only_fields` only governs AUTO-GENERATED fields, so `address`,
        # `terms` and `files` are unaffected -- they are declared explicitly on
        # the serializer and keep the behaviour they already had. `files` in
        # particular stays write_only, so uploads are untouched. `date` is safe
        # because the model defaults it to today.
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
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        # Addrress related field
        country = validated_data.pop("country", None)
        street = validated_data.pop("street", None)
        city = validated_data.pop("city", None)
        province = validated_data.pop("province", None)
        postal_code = validated_data.pop("postal_code", None)
        term = validated_data.pop("term_uid", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)

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
                kind=AddressConnectorKindCoices.CUSTOMER,
                customer=instance,
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
                    kind=TermKindChoices.CUSTOMER,
                    customer=instance,
                    term=term,
                )

        if files:
            for file_data in files:
                if isinstance(file_data, dict):
                    # Update existing file
                    file_item = get_object_or_404(
                        FileItem.objects.filter(
                            uid=file_data["uid"], company=instance.company
                        )
                    )
                    if file_data.get("file"):
                        file_item.file = file_data["file"]
                    if file_description:
                        file_item.description = file_description
                    file_item.save()
                else:
                    # Create new file
                    file_item = FileItem.objects.create(
                        status=FileItemStatusChoices.PUBLISHED,
                        file=file_data,
                        description=file_description,
                        kind=FileItemKindChoices.PDF,
                    )
                    FileItemConnector.objects.create(
                        model_kind=FileItemConnectorModelKindChoices.CUSTOMER,
                        customer=instance,
                        file_item=file_item,
                    )

        return super().update(instance, validated_data)


class PrivateWeCustomerFileListSerializer(ModelSerializer):
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


class PrivateWeCustomerFileDetailsSerializer(ModelSerializer):
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


class PrivateWeCustomerBulkCreateSerializer(ModelSerializer):
    customer_file = FileField(write_only=True)

    class Meta:
        model = Customer
        fields = ["customer_file"]

    def validate(self, attrs):
        if not attrs.get("customer_file"):
            raise ValidationError({"message": "File is required."})

        if not attrs["customer_file"].name.endswith((".csv", ".xlsx", ".xls")):
            raise ValidationError({"message": "File must be a CSV or Excel file."})

        return attrs

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = self.context["request"].user.get_active_company()
        chart_of_accounts = get_chart_of_account(
            [
                "Accounts Receivable (A/R)",
                "Opening Balance Equity",
            ],
            company,
        )
        receivable_account = chart_of_accounts.get("Accounts Receivable (A/R)")
        chart_of_account = chart_of_accounts.get("Opening Balance Equity")

        file = validated_data.pop("customer_file", None)
        df = pd.read_excel(file)
        df = df.fillna(
            value={
                "currency": "USD",
                "billing_rate": 0.00,
                "opening_balance": 0.00,
            }
        ).replace({np.nan: None})

        customers = []
        addresses = []
        missing_first_name_rows = []
        missing_email_rows = []
        duplicate_emails = []
        customer_balances = []  # Track customers with opening balances
        existing_emails = set(
            Customer.objects.filter(company=company).values_list("email", flat=True)
        )
        file_emails = set()

        for i, row in df.iterrows():
            row_number = i + 2

            # Validate required fields
            if row.get("first_name") is None:
                missing_first_name_rows.append(row_number)
                continue

            if row.get("email") is None:
                missing_email_rows.append(row_number)
                continue

            email = row.get("email")
            if email in file_emails or email in existing_emails:
                duplicate_emails.append(row_number)
                continue

            file_emails.add(email)

            # Prepare customer data
            customer_data = {
                "currency": row.get("currency"),
                "first_name": row.get("first_name"),
                "middle_name": row.get("middle_name"),
                "last_name": row.get("last_name"),
                "suffix": row.get("suffix"),
                "company_name": row.get("company_name"),
                "company_email": row.get("company_email"),
                "email": email,
                "telephone_number": row.get("telephone_number"),
                "mobile_number": row.get("mobile_number"),
                "fax": row.get("fax"),
                "website": row.get("website"),
                "business_id": row.get("business_id"),
                "billing_rate": row.get("billing_rate"),
                "account_number": row.get("account_number"),
                "date": pd.to_datetime(
                    row.get("date") if row.get("date") is not None else datetime.now()
                ).date(),
                "opening_balance": row.get("opening_balance"),
                "status": CustomerStatusChoices.ACTIVE,
                "description": row.get("description"),
                "company": company,
            }
            customers.append(Customer(**customer_data))

            # Prepare address data
            address_data = {
                "country": row.get("country", "us"),
                "street": row.get("street"),
                "city": row.get("city"),
                "province": row.get("province"),
                "postal_code": row.get("postal_code"),
                "company": company,
                "status": AddressStatusChoices.ACTIVE,
            }
            addresses.append(Address(**address_data))

            # Track customers with opening balance
            opening_balance = row.get("opening_balance", 0)
            # `!= 0`. The supplier twin of this guard dropped a carried-in
            # vendor credit on the floor -- written to the row and posted
            # nowhere. Same guard, same shape, so the same fix; the mirror rule
            # says fixing one side alone turns one defect into two.
            if opening_balance and float(opening_balance) != 0:
                customer_balances.append(
                    {
                        "index": len(customers) - 1,
                        "amount": float(opening_balance),
                        "display_name": row.get("first_name"),
                    }
                )

        # Check for validation errors
        errors = {}
        if missing_first_name_rows:
            errors["first_name"] = (
                f"First name is required at row numbers: {', '.join(map(str, missing_first_name_rows))}"
            )

        if missing_email_rows:
            errors["email"] = (
                f"Email is required at row numbers: {', '.join(map(str, missing_email_rows))}"
            )

        if duplicate_emails:
            errors["duplicate_email"] = (
                f"Duplicate or existing email addresses at row numbers: {', '.join(map(str, duplicate_emails))}"
            )

        if errors:
            raise ValidationError(errors)

        # Create customers and addresses
        created_customers = Customer.objects.bulk_create(customers)
        created_addresses = Address.objects.bulk_create(addresses)

        # Create address connectors
        address_connectors = [
            AddressConnector(
                kind=AddressConnectorKindCoices.CUSTOMER,
                customer=customer,
                address=address,
            )
            for customer, address in zip(created_customers, created_addresses)
        ]
        AddressConnector.objects.bulk_create(address_connectors)

        # For each customer with opening balance, create sale receipt and journal entry
        for balance_info in customer_balances:
            customer = created_customers[balance_info["index"]]
            signed = Decimal(str(balance_info["amount"]))
            amount = abs(signed)

            # Invoice or credit memo, whichever the sign says. A negative is not
            # a negative invoice: `open_invoices_qs` filters `due_total__gt=0`,
            # so one would be invisible to the ageing report while its journal
            # legs still moved A/R.
            sale, is_credit = customer_opening_balance_document(
                customer, company, signed, created_by=user.get_employee(),
                date=customer.date,
            )

            # Both legs invert on a credit, and both resolve from the side they
            # must land on rather than from a literal -- `"addition"` maps to a
            # different side per account kind.
            receivable_action = action_for_side(
                receivable_account.kind,
                JournalEntryConnectorKindChoices.CREDIT
                if is_credit
                else JournalEntryConnectorKindChoices.DEBIT,
            )
            equity_action = action_for_side(
                chart_of_account.kind,
                JournalEntryConnectorKindChoices.DEBIT
                if is_credit
                else JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                receivable_account,
                balance_operation_for_action(receivable_action),
                amount,
                0,
            )
            update_opening_balance(
                chart_of_account,
                balance_operation_for_action(equity_action),
                amount,
                0,
            )

            # Prepare connector data for journal entry

            connector_data = [
                (
                    receivable_account,
                    "addition",
                    amount,
                    receivable_account.opening_balance,
                    None,
                ),
                (
                    chart_of_account,
                    "addition",
                    amount,
                    chart_of_account.opening_balance,
                    None,
                ),
            ]

            # Create journal entry
            journal_entry = JournalEntryService.create_journal_entry(
                amount=amount,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.SALE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=sale,
            )

            # Create journal entry connectors
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=amount,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                customer=customer,
                created_by=user.get_employee(),
            )

        return created_customers


class PrivateWeCustomerTransactionListSerializer(ModelSerializer):
    class Meta:
        model = Sale
        fields = [
            "uid",
            "date",
            "invoice_id",
            "status",
            "total",
            "created_at",
            "updated_at",
            "is_invoice",
            "is_estimated",
        ]


class PrivateWeSaleInvoiceListByCustomerSerializer(ModelSerializer):
    class Meta:
        model = Sale
        fields = [
            "uid",
            "invoice_id",
            "status",
            "tracking_number",
            "date",
            "total",
            "discount",
            "shipping_fee",
            "total_vat",
            "total_tax",
            "invoice_date",
            "is_invoice",
            "is_estimated",
        ]
