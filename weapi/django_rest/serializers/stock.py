from rest_framework.generics import get_object_or_404
from rest_framework.serializers import (
    ModelSerializer,
    SlugRelatedField,
    ValidationError,
    DecimalField,
    JSONField,
)
from django.db import transaction

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer
from common.django_rest.helpers.serializer_scoping import CompanyScopedRelatedFieldsMixin
from common.django_rest.helpers.serializer_scoping import company_scoped
from common.django_rest.helpers.retire_guard import assert_not_retiring_by_patch
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.quantity_helpers import update_quantity

from stockio.django_rest.services.stock_movement import (
    record_adjustment_stock,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.decorators import set_auditlog_actor

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.django_rest.serializers.common import PrivateJournalEntryLastBalanceConnectorSlimSerializer

from stockio.models import StockAlert, StockAdjustment, StockAdjustmentItem
from stockio.choices import (
    StockAdjustmentItemStatusChoices,
    StockAdjustmentItemKindChoices,
)

from productio.models import Product
from productio.django_rest.serializers.common import PrivateProductSlimSerializer




class PrivateWeStockLevelSerializer(ModelSerializer):
    class Meta:
        model = StockAlert
        fields = [
            "uid",
            "status",
            "quantity",
            "description",
            "is_expired_date",
            "before_expired_day",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        if (
            StockAlert.objects.get_status_all()
            .filter(company=validated_data["company"])
            .exists()
        ):
            raise ValidationError(
                "Stock alert already exists for this company. Please update the existing alert."
            )
        return super().create(validated_data)


class PrivateWeStockLevelDetailSerializer(ModelSerializer):
    class Meta:
        model = StockAlert
        fields = [
            "uid",
            "status",
            "quantity",
            "description",
            "is_expired_date",
            "before_expired_day",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        return super().update(instance, validated_data)


class PrivateWeStockAdjustmentSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    stock_adjustment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    stock_adjustment_items = JSONField(write_only=True, required=False)
    sub_total = DecimalField(
        source="get_sub_total", max_digits=10, decimal_places=2, read_only=True
    )
    journal_connector = PrivateJournalEntryLastBalanceConnectorSlimSerializer(
        source="get_journal__account_last_balance", read_only=True
    )

    class Meta:
        model = StockAdjustment
        fields = [
            "uid",
            "status",
            "date",
            "reference_number",
            "description",
            "reason",
            "sub_total",
            "journal_connector",
            "stock_adjustment_account_uid",
            "stock_adjustment_items",
        ]

    read_only_fields = ["uid", "created_at", "updated_at"]

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["company"] = self.context["request"].user.get_active_company()
        company = validated_data["company"]
        validated_data["stock_adjustment_account"] = validated_data.pop(
            "stock_adjustment_account_uid", None
        )
        stock_adjustment_account = validated_data.get("stock_adjustment_account")

        # Validate reference number
        reference_number = validated_data.get("reference_number")
        if reference_number == "":
            validated_data["reference_number"] = None

        stock_adjustment_items = validated_data.pop("stock_adjustment_items", [])
        chart_of_accounts = get_chart_of_account(
            [
                "Inventory Asset",
            ],
            company,
        )
        inventory_asset_charter_account = chart_of_accounts.get("Inventory Asset")
        connector_data = []
        total_amount = 0  # Initialize total amount tracker
        stock_adjustment = super().create(validated_data)

        if stock_adjustment_items:
            for item in stock_adjustment_items:
                product = get_object_or_404(
                    company_scoped(Product.objects.filter(uid=item.get("product_uid")), self)
                )

                # Get product additional cost
                product_additional_cost = product.productadditionalcost_set.first()
                product_cost_amount = (
                    product_additional_cost.amount if product_additional_cost else 0
                )
                quantity = item.get("quantity", 0)
                item_balance = quantity * product_cost_amount
                total_amount += item_balance
                # Track the total amount based on the kind of adjust
                kind = item.get("kind", StockAdjustmentItemKindChoices.ADDITION)

                # Create the stock adjustment item
                adjustment_item = StockAdjustmentItem.objects.create(
                    status=item.get("status", StockAdjustmentItemStatusChoices.ACTIVE),
                    kind=kind,
                    description=item.get("description", None),
                    quantity=quantity,
                    product=product,
                    stock_adjustment=stock_adjustment,
                )
                # used after fifo added
                # total_adjustment_balance = stock_adjustment.get_sub_total()

                # Update product quantity and account balances based on kind
                if kind == StockAdjustmentItemKindChoices.ADDITION:
                    update_quantity(product, "addition", quantity, 0)

                    # The one document whose whole purpose is to move inventory
                    # was moving it with no ledger row -- `Product.quantity` and
                    # the journal legs and nothing in between. Written up, these
                    # are costed units with no purchase behind them, so the row
                    # becomes a cost layer of its own.
                    record_adjustment_stock(
                        adjustment_item, unit_cost=product_cost_amount,
                        created_by=user.get_employee(),
                    )

                    # Stock written UP: inventory DEBITS (there is more of
                    # it) and the adjustment account takes the contra CREDIT.
                    # Both sides were right; both stored balances moved the
                    # wrong way. `update_opening_balance` reads CREDIT/DEBIT as
                    # add/subtract, not as a side, so passing the accounting
                    # side there subtracted from inventory while the journal
                    # debited it.
                    inventory_action = action_for_side(
                        inventory_asset_charter_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    adjustment_action = action_for_side(
                        stock_adjustment_account.kind,
                        JournalEntryConnectorKindChoices.CREDIT,
                    )
                    update_opening_balance(
                        stock_adjustment_account,
                        balance_operation_for_action(adjustment_action),
                        item_balance,
                        0,
                    )
                    update_opening_balance(
                        inventory_asset_charter_account,
                        balance_operation_for_action(inventory_action),
                        item_balance,
                        0,
                    )

                    connector_data.append(
                        (
                            stock_adjustment_account,
                            adjustment_action,
                            item_balance,
                            stock_adjustment_account.opening_balance,
                            None,
                        )
                    )
                    connector_data.append(
                        (
                            inventory_asset_charter_account,
                            inventory_action,
                            item_balance,
                            inventory_asset_charter_account.opening_balance,
                            None,
                        )
                    )

                elif kind == StockAdjustmentItemKindChoices.DEDUCTION:
                    update_quantity(product, "deduction", quantity, 0)

                    # Written down, it relieves the oldest layers like any other
                    # outbound. Shrinkage is the case where on-hand and the
                    # layers are most likely to already disagree, so units no
                    # layer explains are admitted as a fallback slice rather
                    # than dropped.
                    record_adjustment_stock(
                        adjustment_item, unit_cost=product_cost_amount,
                        created_by=user.get_employee(),
                    )

                    # Stock written DOWN: the mirror. Inventory CREDITS (less
                    # of it) and the adjustment account takes the DEBIT -- the
                    # shrinkage recognised as a cost.
                    inventory_action = action_for_side(
                        inventory_asset_charter_account.kind,
                        JournalEntryConnectorKindChoices.CREDIT,
                    )
                    adjustment_action = action_for_side(
                        stock_adjustment_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        stock_adjustment_account,
                        balance_operation_for_action(adjustment_action),
                        item_balance,
                        0,
                    )
                    update_opening_balance(
                        inventory_asset_charter_account,
                        balance_operation_for_action(inventory_action),
                        item_balance,
                        0,
                    )

                    connector_data.append(
                        (
                            stock_adjustment_account,
                            adjustment_action,
                            item_balance,
                            stock_adjustment_account.opening_balance,
                            None,
                        )
                    )
                    connector_data.append(
                        (
                            inventory_asset_charter_account,
                            inventory_action,
                            item_balance,
                            inventory_asset_charter_account.opening_balance,
                            None,
                        )
                    )

            journal_entry = JournalEntryService.create_journal_entry(
                amount=total_amount,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.STOCK_ADJUSTMENT,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=stock_adjustment,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total_amount,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                created_by=user.get_employee(),
            )
        return stock_adjustment


class PrivateWeStockAdjustmentDetailSerializer(CompanyScopedRelatedFieldsMixin, ModelSerializer):
    stock_adjustment_account = PrivateChartOfAccountSlimSerializer()
    stock_adjustment_account_uid = SlugRelatedField(
        slug_field="uid",
        queryset=ChartOfAccount.objects.selectable().all().exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    stock_adjustment_items = JSONField(write_only=True, required=False)
    journal_connector = PrivateJournalEntryLastBalanceConnectorSlimSerializer(
        source="get_journal__account_last_balance", read_only=True
    )

    class Meta:
        model = StockAdjustment
        fields = [
            "uid",
            "status",
            "date",
            "reference_number",
            "description",
            "reason",
            "stock_adjustment_account",
            "stock_adjustment_items",
            "stock_adjustment_account_uid",
            "journal_connector",
        ]

    @transaction.atomic
    @set_auditlog_actor
    def update(self, instance, validated_data):
        # `status` is writable here and read-only on none of the six
        # detail serializers, so a PATCH could retire the document by
        # writing the column -- skipping every guard, the reversal and
        # the allocation unwind that live in `perform_destroy`.
        assert_not_retiring_by_patch(
            instance, validated_data, document='stock adjustment',
        )

        validated_data["company"] = self.context["request"].user.get_active_company()
        # Validate reference number
        reference_number = validated_data.get("reference_number")
        if reference_number == "":
            validated_data["reference_number"] = None

        stock_adjustment_account = validated_data.get("stock_adjustment_account_uid")
        if stock_adjustment_account:
            validated_data["stock_adjustment_account"] = validated_data.pop(
                "stock_adjustment_account_uid", None
            )
        stock_adjustment_items = validated_data.pop("stock_adjustment_items", [])
        instance = super().update(instance, validated_data)

        if stock_adjustment_items:
            for stock_adjustment_item in stock_adjustment_items:
                if stock_adjustment_item.get("uid"):
                    # Scoped to THIS adjustment, not to the whole table. The uid
                    # comes straight from the request body, and
                    # `stockio_stockadjustmentitem` carries no row-level-security
                    # policy -- unlike ChartOfAccount, Product, Sale, Purchase
                    # and Customer, where the database refuses a cross-tenant row
                    # even when the query forgets. So any uid in the table
                    # resolved here, and the loop below then rewrites its
                    # `status`, `kind`, `description`, `quantity` and `product`:
                    # a write straight into another company's stock adjustment.
                    #
                    # Scoping by the parent rather than by `company=` is both
                    # narrower and simpler -- `instance` is already tenant-scoped
                    # by the view's `get_object`, and a line belonging to a
                    # DIFFERENT adjustment of the SAME company has no business
                    # being rewritten here either. Same shape as the journal-line
                    # fix in `serializers/journals.py`.
                    item = get_object_or_404(
                        StockAdjustmentItem.objects.filter(
                            uid=stock_adjustment_item.get("uid"),
                            stock_adjustment=instance,
                        )
                    )
                    item.status = stock_adjustment_item.get(
                        "status", StockAdjustmentItemStatusChoices.DRAFT
                    )
                    item.kind = stock_adjustment_item.get(
                        "kind", StockAdjustmentItemKindChoices.ADDITION
                    )
                    item.description = stock_adjustment_item.get("description", None)
                    item.quantity = stock_adjustment_item.get("quantity", 0)
                    item.product = get_object_or_404(
                        company_scoped(Product.objects.filter(
                            uid=stock_adjustment_item.get("product_uid")
                        ), self)
                    )
                    item.save()
                else:
                    StockAdjustmentItem.objects.create(
                        status=stock_adjustment_item.get(
                            "status", StockAdjustmentItemStatusChoices.DRAFT
                        ),
                        # ADDITION, not INCREASE -- the latter is not a member
                        # of StockAdjustmentItemKindChoices, which defines only
                        # ADDITION and DEDUCTION. Python evaluates a `.get`
                        # default eagerly, so this raised AttributeError before
                        # the create ran: adding a line to an existing stock
                        # adjustment has never worked, it 500s. The equivalent
                        # default fifty lines up already says ADDITION.
                        kind=stock_adjustment_item.get(
                            "kind", StockAdjustmentItemKindChoices.ADDITION
                        ),
                        description=stock_adjustment_item.get("description", None),
                        quantity=stock_adjustment_item.get("quantity", 0),
                        product=get_object_or_404(
                            company_scoped(Product.objects.filter(
                                uid=stock_adjustment_item.get("product_uid")
                            ), self)
                        ),
                        stock_adjustment=instance,
                    )
        return instance


class PrivateWeStockAdjustmentItemSerializer(ModelSerializer):
    product = PrivateProductSlimSerializer(read_only=True)

    class Meta:
        model = StockAdjustmentItem
        fields = [
            "uid",
            "status",
            "kind",
            "description",
            "quantity",
            "product",
        ]
        read_only_fields = ["uid", "created_at", "updated_at"]
