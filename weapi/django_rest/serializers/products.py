import pandas as pd
import numpy as np

from rest_framework.generics import get_object_or_404
from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    DecimalField,
    CharField,
    FileField,
    ValidationError,
    ListField,
    JSONField,
    IntegerField,
)
from django.db import transaction

from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from agencyio.models import AgencyTax
from accounts.models import ChartOfAccount

from brandio.models import Brand, BrandConnector
from brandio.django_rest.serializers.common import PrivateBrandSlimSerializer

from common.django_rest.helpers.serializer_scoping import company_scoped
from common.django_rest.helpers.balance_helpers import update_opening_balance
from common.django_rest.helpers.serializer_scoping import (
    CompanyScopedRelatedFieldsMixin,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from categoryio.models import Category, CategoryConnector
from categoryio.django_rest.serializers.common import (
    PrivateCategorySlimSerializer,
)

from common.django_rest.helpers.decorators import set_auditlog_actor

from fileroomio.choices import (
    FileItemConnectorModelKindChoices,
    FileItemKindChoices,
    FileItemStatusChoices,
)
from fileroomio.models import FileItemConnector, FileItem
from fileroomio.django_rest.serializers.common import PrivateFileItemConnectorSerializer
from fileroomio.django_rest.services.files import FileService

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from productio.models import (
    Product,
    ProductBundle,
    ProductBundleConnector,
    ProductAdditionalCost,
)

from stockio.django_rest.services.stock_movement import (
    record_opening_stock,
)
from productio.django_rest.serializers.common import (
    PrivateProductAdditionalCostSlimSerializer,
)
from supplierio.models import Supplier


UNSET = object()
"""Distinguishes "the client did not send this field" from "the client sent null".

`validated_data.pop(key, None)` collapses the two, which is how a PATCH that
mentioned only `sale_price` came to write None over an additional-cost row's
expense account -- a NOT NULL column, so an IntegrityError and a 500 on 72% of
production's products.
"""


class PrivateWeProductListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    brand_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Brand.objects.get_status_all().filter(),
        required=False,
    )
    brand = PrivateBrandSlimSerializer(
        source="brandconnector_set.first.brand", read_only=True
    )

    category_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Category.objects.get_status_all().filter(),
        required=False,
    )

    category = PrivateCategorySlimSerializer(
        source="categoryconnector_set.first.category", read_only=True
    )
    asset_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    income_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    cogs_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    cogs_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    expense_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    prefferred_supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )
    # In expense/purchase Tax will not work.
    # tax_uid = SlugRelatedField(
    #     slug_field="uid",
    #     queryset=AgencyTax.objects.all(),
    #     write_only=True,
    #     required=False,
    # )
    file_data = PrivateFileItemConnectorSerializer(
        source="fileitemconnector_set", many=True, read_only=True
    )
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(write_only=True, required=False)
    amount = DecimalField(max_digits=19, decimal_places=3, required=False)
    purchase_information = CharField(max_length=255, required=False)
    purchase_price = DecimalField(
        max_digits=19, decimal_places=3, source="get_purchase_price", read_only=True
    )
    

    class Meta:
        model = Product
        fields = [
            "uid",
            "title",
            "sku",
            "code",
            "quantity",
            "date",
            "expired_date",
            "reorder_point",
            "description",
            "sale_price",
            "kind",
            "status",
            "vat",
            "is_non_stock",
            "is_inventory",
            "is_stock",
            "is_purchased",
            "is_addtional_cost",
            "brand",
            "brand_uid",
            "category",
            "category_uid",
            "asset_account_uid",
            "income_account_uid",
            "cogs_account",
            "cogs_account_uid",
            "expense_account_uid",
            "prefferred_supplier_uid",
            # "tax_uid",
            "file_data",
            "files",
            "file_description",
            "amount",
            "purchase_price",
            "purchase_information",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        company = user.get_active_company()
        validated_data["company"] = company
        validated_data["asset_account"] = validated_data.pop("asset_account_uid", None)
        validated_data["income_account"] = validated_data.pop(
            "income_account_uid", None
        )
        if "cogs_account_uid" in validated_data:
            validated_data["cogs_account"] = validated_data.pop("cogs_account_uid")
        inventory_asset_charter_account = validated_data.get("asset_account")
        brand = validated_data.pop("brand_uid", None)
        category = validated_data.pop("category_uid", None)
        expense_account_uid = validated_data.pop("expense_account_uid", None)
        prefferred_supplier = validated_data.pop("prefferred_supplier_uid", None)
        # tax = validated_data.pop("tax_uid", None)
        amount = validated_data.pop("amount", 0)
        # validated_data["is_addtional_cost"] = True if amount else False
        is_addtional_cost = validated_data.get("is_addtional_cost", False)
        quantity = validated_data.get("quantity", 0)
        validated_data["quantity"] = quantity
        purchase_information = validated_data.pop("purchase_information", None)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)
        chart_of_accounts = get_chart_of_account(
            ["Opening Balance Equity"],
            company,
        )
        opening_balance_equity_charter_account = chart_of_accounts.get(
            "Opening Balance Equity"
        )
        connector_data = []
        product = Product.objects.create(**validated_data)
        if brand:
            BrandConnector.objects.create(
                brand=brand,
                product=product,
            )
        if category:
            CategoryConnector.objects.create(
                category=category,
                product=product,
                brand=brand,
            )
        if is_addtional_cost:
            # The mirror of the update() guard. `expense_account` and `amount`
            # are NOT NULL, so a create that flags is_addtional_cost without
            # them is an IntegrityError -- a 500 the client cannot read --
            # rather than a 400 naming the field to send.
            if expense_account_uid is None or amount is None:
                raise ValidationError(
                    {
                        "is_addtional_cost": (
                            "An additional-cost product needs an expense "
                            "account and an amount. Send those fields, or set "
                            "is_addtional_cost to false."
                        )
                    }
                )
            ProductAdditionalCost.objects.create(
                product=product,
                expense_account=expense_account_uid,
                prefferred_supplier=prefferred_supplier,
                # tax=tax,
                amount=amount,
                description=purchase_information,
            )
        if amount != 0:
            total_additional_cost = quantity * amount
            
            update_opening_balance(
                inventory_asset_charter_account,
                JournalEntryConnectorKindChoices.CREDIT,
                total_additional_cost,
                0,
            )

            # update coa open balance
            update_opening_balance(
                opening_balance_equity_charter_account,
                JournalEntryConnectorKindChoices.CREDIT,
                total_additional_cost,
                0,
            )

            connector_data.extend(
                [
                    (
                        inventory_asset_charter_account,
                        "addition",
                        total_additional_cost,
                        inventory_asset_charter_account.opening_balance,
                        None,
                    ),
                    (
                        opening_balance_equity_charter_account,
                        "addition",
                        total_additional_cost,
                        opening_balance_equity_charter_account.opening_balance,
                        None,
                    ),
                ]
            )
            journal_entry = JournalEntryService.create_journal_entry(
                amount=total_additional_cost,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PRODUCT_PRURCHASE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=product,
            )
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total_additional_cost,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=prefferred_supplier,
                created_by=user.get_employee(),
            )
        if files:
            FileService.create_file_item_connector(
                files=files,
                file_uids=[],
                description=file_description,
                company=user.get_active_company(),
                model_kind=FileItemConnectorModelKindChoices.PRODUCT,
                object=product,
            )

        # Creating a product with a quantity states a fact about inventory, and
        # nothing wrote it down. OPENING rows were produced only by a one-shot
        # backfill command, so every product created since it ran has none --
        # and the valuation reports cumulate the ledger, so an item opened at
        # 100 and then sold 10 read as quantity -10 and value -100 while
        # Product.quantity said 90 and the general ledger said 900.
        record_opening_stock(product, rate=amount, created_by=user.get_employee())

        # The row, not the payload dict: returning the dict made DRF render the
        # 201 body from it, so the response carried no `uid` -- the same defect
        # COA #14 described on the chart-of-accounts endpoint.
        return product


class PrivateWeProductDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    brand_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Brand.objects.get_status_all().filter(),
        required=False,
    )
    brand = PrivateBrandSlimSerializer(
        source="brandconnector_set.first.brand", read_only=True
    )

    category_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Category.objects.get_status_all().filter(),
        required=False,
    )

    category = PrivateCategorySlimSerializer(
        source="categoryconnector_set.first.category", read_only=True
    )

    asset_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    income_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    asset_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    income_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    cogs_account = PrivateChartOfAccountSlimSerializer(read_only=True)
    cogs_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    expense_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().get_status_all().filter(),
        write_only=True,
        required=False,
    )
    prefferred_supplier_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Supplier.objects.selectable(),
        write_only=True,
        required=False,
    )
    tax_uid = SlugRelatedField(
        slug_field="uid",
        queryset=AgencyTax.objects.all(),
        write_only=True,
        required=False,
    )
    file_data = PrivateFileItemConnectorSerializer(
        source="fileitemconnector_set", many=True, read_only=True
    )
    files = ListField(
        child=FileField(allow_empty_file=True, required=False),
        write_only=True,
        required=False,
        allow_null=True,
    )
    file_description = CharField(write_only=True, required=False)
    amount = DecimalField(
        max_digits=10, decimal_places=3, write_only=True, required=False
    )
    purchase_information = CharField(max_length=255, write_only=True, required=False)
    purchase_information_data = PrivateProductAdditionalCostSlimSerializer(
        source="productadditionalcost_set.first", read_only=True
    )
    
    class Meta:
        model = Product
        fields = [
            "uid",
            "title",
            "sku",
            "code",
            "quantity",
            "date",
            "expired_date",
            "reorder_point",
            "description",
            "sale_price",
            "kind",
            "status",
            "vat",
            "is_non_stock",
            "is_inventory",
            "is_stock",
            "is_purchased",
            "is_addtional_cost",
            "asset_account",
            "income_account",
            "brand",
            "category",
            "brand_uid",
            "category_uid",
            "asset_account_uid",
            "income_account_uid",
            "cogs_account",
            "cogs_account_uid",
            "expense_account_uid",
            "prefferred_supplier_uid",
            "tax_uid",
            "file_data",
            "files",
            "file_description",
            "amount",
            "purchase_information",
            "purchase_information_data",
        ]

        # `quantity` is the nineteenth write path to stock, and the only one
        # left that moves it with no document, no movement and no journal entry
        # behind it. Everything else now records what it moves
        # (`STOCK_LEDGER_DECISIONS.md` steps 1-5), so a `PATCH` here was the one
        # remaining way to make `Product.quantity` disagree with the ledger that
        # decides FIFO cost -- and it does so silently, since nothing reads this
        # field to check it.
        #
        # Correcting stock is what a stock adjustment is for, and step 3 wired
        # it, which is why this could only be closed now and not before. It stays
        # writable on CREATE: that is the opening figure, and `record_opening_
        # stock` posts the movement for it.
        #
        # DRF drops a read-only field silently, so an edit form that round-trips
        # the whole object keeps working; the value is simply ignored.
        read_only_fields = [
            "uid",
            "quantity",
            "created_at",
            "updated_at",
            "brand_details",
            "category_details",
        ]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # Absent means UNCHANGED. These two were assigned unconditionally, so a
        # PATCH that touched only the title wrote None over both -- and a
        # product with no income account posts a receivable with no revenue
        # credit, while one with no asset account relieves no inventory. The
        # `cogs_account` line directly below has always been guarded this way;
        # the two above it were written before that pattern existed.
        #
        # Same shape as 557b565f, which was the money fields on a bill, and as
        # the warehouse and charter-account fields on the sale serializer. The
        # identical block in `create` is correct as it stands: on a create there
        # is no prior value for absent to preserve.
        if "asset_account_uid" in validated_data:
            validated_data["asset_account"] = validated_data.pop("asset_account_uid")
        if "income_account_uid" in validated_data:
            validated_data["income_account"] = validated_data.pop("income_account_uid")
        if "cogs_account_uid" in validated_data:
            validated_data["cogs_account"] = validated_data.pop("cogs_account_uid")
        brand = validated_data.pop("brand_uid", None)
        category = validated_data.pop("category_uid", None)
        # UNSET, not None. `pop(key, None)` cannot tell "the client did not
        # mention this field" from "the client sent null", and the block below
        # assigned all five unconditionally -- so `PATCH {"sale_price": "25.000"}`
        # on a product with `is_addtional_cost=True` wrote None over every one of
        # them. `expense_account` and `amount` are NOT NULL, so that was an
        # IntegrityError escaping as a 500; `prefferred_supplier`, `tax` and
        # `description` are nullable, so those were silently wiped instead,
        # which is the quieter half of the same bug.
        expense_account_uid = validated_data.pop("expense_account_uid", UNSET)
        prefferred_supplier = validated_data.pop("prefferred_supplier_uid", UNSET)
        tax = validated_data.pop("tax_uid", UNSET)
        amount = validated_data.pop("amount", UNSET)
        purchase_information = validated_data.pop("purchase_information", UNSET)
        files = validated_data.pop("files", None)
        file_description = validated_data.pop("file_description", None)

        instance = super().update(instance, validated_data)

        if brand is not None:
            brand_connector = instance.brandconnector_set.first()
            if brand_connector:
                brand_connector.brand = brand
                brand_connector.save()
            else:
                BrandConnector.objects.create(
                    brand=brand,
                    product=instance,
                )
        if category is not None:
            category_connector = instance.categoryconnector_set.first()
            if category_connector:
                category_connector.category = category
                category_connector.save()
            else:
                CategoryConnector.objects.create(
                    category=category,
                    product=instance,
                    brand=brand,
                )

        if instance.is_addtional_cost:
            product_additional_cost = instance.productadditionalcost_set.first()
            sent = {
                "expense_account": expense_account_uid,
                "prefferred_supplier": prefferred_supplier,
                "tax": tax,
                "amount": amount,
                "description": purchase_information,
            }
            sent = {k: v for k, v in sent.items() if v is not UNSET}

            if product_additional_cost:
                # PATCH semantics: touch only what the payload named. A field
                # the client did not mention keeps the value it had.
                for field, value in sent.items():
                    setattr(product_additional_cost, field, value)
                if sent:
                    product_additional_cost.save(
                        update_fields=[*sent, "updated_at"]
                    )
            else:
                # Creating the row rather than amending one, so the NOT NULL
                # columns have to be present. Refusing with a 400 that names the
                # field beats an IntegrityError the client cannot read.
                missing = [
                    name for name in ("expense_account", "amount")
                    if sent.get(name) is None
                ]
                if missing:
                    raise ValidationError(
                        {
                            "is_addtional_cost": (
                                "An additional-cost product needs "
                                + " and ".join(
                                    {
                                        "expense_account": "an expense account",
                                        "amount": "an amount",
                                    }[name]
                                    for name in missing
                                )
                                + ". Send those fields, or set is_addtional_cost "
                                "to false."
                            )
                        }
                    )
                ProductAdditionalCost.objects.create(
                    product=instance, **sent
                )

        if files:
            instance.fileitemconnector_set.all().delete()
            file_items = [
                FileItem.objects.create(
                    company=instance.company,
                    status=FileItemStatusChoices.PUBLISHED,
                    file=file,
                    description=file_description,
                    kind=FileItemKindChoices.IMAGE,
                )
                for file in files
            ]

            FileItemConnector.objects.bulk_create(
                [
                    FileItemConnector(
                        model_kind=FileItemConnectorModelKindChoices.PRODUCT,
                        product=instance,
                        file_item=file_item,
                    )
                    for file_item in file_items
                ]
            )

        return instance


class PrivateWeProductBundleListSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    products_items = JSONField(required=False, write_only=True)

    class Meta:
        model = ProductBundle
        fields = ["uid", "title", "sku", "status", "products_items", "description"]
        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        products_items = validated_data.pop("products_items", None)

        product_bundle = ProductBundle.objects.create(**validated_data)

        if products_items:
            for item in products_items:
                product = (
                    get_object_or_404(company_scoped(Product.objects.filter(uid=item["product_uid"]), self))
                    if item.get("product_uid")
                    else None
                )
                if product:
                    ProductBundleConnector.objects.create(
                        product_bundle=product_bundle,
                        products=product,
                        quantity=item.get("quantity", 1),
                    )
        return product_bundle


class PrivateWeProductBundleDetailsSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    products_items = JSONField(required=False, write_only=True)

    class Meta:
        model = ProductBundle
        fields = ["uid", "title", "sku", "status", "products_items", "description"]
        read_only_fields = ["uid", "created_at", "updated_at"]

    def validate(self, attrs):
        attrs["company"] = self.context["request"].user.get_active_company()
        return super().validate(attrs)

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        products_items = validated_data.pop("products_items", None)
        instance = super().update(instance, validated_data)

        if products_items is not None:
            instance.productbundleconnector_set.all().delete()

            for item in products_items:
                product = (
                    get_object_or_404(company_scoped(Product.objects.filter(uid=item["product_uid"]), self))
                    if item.get("product_uid")
                    else None
                )

                if product:
                    ProductBundleConnector.objects.create(
                        product_bundle=instance,
                        products=product,
                        quantity=item.get("quantity", 1),
                    )
        return instance


class PrivateWeProductBulkCreateSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    product_file = FileField(write_only=True)

    class Meta:
        model = Product
        fields = ["product_file"]

    def validate(self, attrs):
        if not attrs.get("product_file"):
            raise ValidationError({"message": "File is required."})

        if not attrs["product_file"].name.endswith((".csv", ".xlsx", ".xls")):
            raise ValidationError({"message": "File must be a CSV or Excel file."})

        return super().validate(attrs)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        file = validated_data.pop("product_file")
        user = self.context["request"].user
        company = user.get_active_company()

        if file.name.endswith(".xlsx"):
            df = pd.read_excel(file, engine="openpyxl")
        elif file.name.endswith(".xls"):
            df = pd.read_excel(file, engine="xlrd")
        elif file.name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            raise ValidationError({"message": "Unsupported file format."})

        df = df.replace({np.nan: None})

        chart_of_accounts = get_chart_of_account(
            [
                "Opening Balance Equity",
                "Inventory Asset",
                "Sales of Product Income",
                "Cost of Goods Sold (COGS)",
            ],
            company,
        )

        inventory_asset_account = chart_of_accounts.get("Inventory Asset")
        opening_balance_equity_account = chart_of_accounts.get("Opening Balance Equity")
        sales_income_account = chart_of_accounts.get("Sales of Product Income")
        expense_account = chart_of_accounts.get("Cost of Goods Sold (COGS)")

        products = []
        products_with_additional_costs = []
        invalid_rows = []

        for index, row in df.iterrows():
            if not row.get("sku"):
                invalid_rows.append(index + 1)
                continue

            amount = row.get("purchase_price", 0)
            quantity = row.get("quantity", 0)
            is_additional_cost = bool(
                amount and quantity and amount > 0 and quantity > 0
            )

            product = Product(
                title=row.get("title"),
                sku=row.get("sku"),
                code=row.get("code"),
                quantity=quantity,
                date=pd.to_datetime(row.get("date", pd.Timestamp.now())).date(),
                expired_date=row.get("expired_date"),
                reorder_point=row.get("reorder_point", 0),
                description=row.get("description"),
                sale_price=row.get("sale_price", 0),
                kind=row.get("kind", "PRODUCT"),
                status=row.get("status", "ACTIVE"),
                vat=row.get("vat", 0),
                is_inventory=row.get("is_inventory", True),
                is_addtional_cost=is_additional_cost,
                asset_account=inventory_asset_account,
                income_account=sales_income_account,
                company=company,
            )

            products.append(product)

            # Store products that need additional cost processing
            if is_additional_cost:
                products_with_additional_costs.append(
                    (index, product, amount, quantity)
                )

        # bulk_create bypasses save(), so the derivation has to happen here too
        # or the CSV path would be the one way to store a contradictory flag.
        for product in products:
            product.is_inventory = product.tracks_stock()

        created_products = Product.objects.bulk_create(products)

        # Same opening fact for the CSV path. bulk_create returns rows with PKs
        # on Postgres, so each product can be opened as it is created.
        for created in created_products:
            opening_rate = next(
                (a for _i, p, a, _q in products_with_additional_costs if p is created),
                0,
            )
            record_opening_stock(created, rate=opening_rate)

        for index, product, amount, quantity in products_with_additional_costs:
            total_additional_cost = quantity * amount

            ProductAdditionalCost.objects.create(
                product=product,
                expense_account=expense_account,
                amount=amount,
                description=f"Initial purchase of {product.title}",
            )

            update_opening_balance(
                inventory_asset_account,
                JournalEntryConnectorKindChoices.CREDIT,
                total_additional_cost,
                0,
            )

            update_opening_balance(
                opening_balance_equity_account,
                JournalEntryConnectorKindChoices.CREDIT,
                total_additional_cost,
                0,
            )

            connector_data = [
                (
                    inventory_asset_account,
                    "addition",
                    total_additional_cost,
                    inventory_asset_account.opening_balance,
                    None,
                ),
                (
                    opening_balance_equity_account,
                    "addition",
                    total_additional_cost,
                    opening_balance_equity_account.opening_balance,
                    None,
                ),
            ]

            # Create journal entry
            journal_entry = JournalEntryService.create_journal_entry(
                amount=total_additional_cost,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PRODUCT_PRURCHASE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=product,
            )

            # Create journal entry connector
            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total_additional_cost,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                created_by=user.get_employee(),
            )

        if invalid_rows:
            raise ValidationError(
                {
                    "message": f"SKU is required for rows {', '.join(map(str, invalid_rows))}"
                }
            )

        return created_products
