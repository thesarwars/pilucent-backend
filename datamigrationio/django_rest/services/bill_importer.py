import os
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)

from common.django_rest.helpers.file_helpers import generate_pdf_direct
from common.django_rest.helpers.emails import send_email_to_user

from purchaseio.models import Purchase, PurchaseItem
from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchaseTaxKindChoices,
)
from common.choices import DiscountKind
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.balance_helpers import (
    update_opening_balance,
    action_for_side,
    balance_operation_for_action,
)
from common.django_rest.helpers.quantity_helpers import update_quantity

from weapi.django_rest.helpers.purchase_item_helpers import (
    record_purchase_line_movement,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector
from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices
from journalio.django_rest.services.journals import JournalEntryService
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)

from supplierio.models import Supplier
from productio.models import Product
from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from wirehouseio.models import Warehouse

from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from datetime import date as date_type
from datamigrationio.django_rest.services.bill_validator import parse_date
from weapi.django_rest.helpers.sale_posting import resolve_cogs_account
"""Where a non-stocked line's cost belongs -- shared with the sale side, so
the two never disagree about the same product."""


logger = logging.getLogger(__name__)


class MigrationBillCreateService:
    """
    Standalone bill creation for data migration.
    Creates Purchase records with is_bill=True.
    Mirrors PrivateWePurchaseListSerializer.create() bill accounting logic:
    - Product lines: update_quantity + update_opening_balance(Inventory Asset, CREDIT)
    - Expense lines: update_opening_balance(expense_account, CREDIT)
    - update_opening_balance(supplier, CREDIT, due_total)
    - update_opening_balance(Accounts Payable, CREDIT, due_total)
    - update_opening_balance(Sales Tax Payable, CREDIT, total_tax)
    - JournalEntry kind=PURCHASE + connectors
    """

    @staticmethod
    def create_bill(bill_group, user, company, options=None):
        """
        bill_group keys:
            supplier, bill_number, bill_date, due_date, currency_kind, currency_rate,
            full_billing_address, memo, total, total_tax, warehouse, lines

        Each line: product, expense_account, line_kind, quantity, purchase_price, total,
            description, tax

        Returns: Purchase instance
        """
        options = options or {}
        supplier = bill_group["supplier"]
        bill_number = bill_group["bill_number"]
        bill_date = bill_group["bill_date"]
        due_date = bill_group.get("due_date")
        currency_kind = bill_group.get("currency_kind") or getattr(
            company, "currency", "USD"
        )
        currency_rate = bill_group.get("currency_rate") or Decimal("1")
        full_billing_address = bill_group.get("full_billing_address", "")
        memo = bill_group.get("memo", "")
        total = bill_group.get("total", Decimal("0"))
        total_tax = bill_group.get("total_tax", Decimal("0"))
        warehouse = bill_group.get("warehouse")
        lines = bill_group.get("lines", [])

        due_total = total + total_tax
        tracking_number = get_unique_id(Purchase, company.id, "tracking_number", "PURCHASE")
        purchase_id = get_unique_id(Purchase, company.id, "purchase_id", "PUR")

        has_tax = any(line.get("tax") for line in lines)
        # A caller with a document-level tax setting (e.g. a recurring template
        # marked INCLUSIVE) passes it explicitly; CSV import has none and keeps
        # the has-tax derivation.
        tax_kind = bill_group.get("tax_kind") or (
            PurchaseTaxKindChoices.EXCLUSIVE if has_tax else PurchaseTaxKindChoices.NO_TAX
        )

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        # Get chart of accounts needed for GL entries
        chart_of_accounts = get_chart_of_account(
            ["Accounts Payable (A/P)", "Inventory Asset", "Sales Tax Payable"],
            company,
        )
        # A purchase order is the same record as a bill with is_bill=False, but
        # it is a COMMITMENT, not a liability: the live endpoint gates every
        # ledger effect on is_bill, so a non-posting caller must skip A/P,
        # inventory, account balances and the journal. Defaults keep bills and
        # CSV import posting exactly as before.
        posting = options.get("posting", True)
        is_bill = bill_group.get("is_bill", True)
        purchase_status = bill_group.get("status") or PurchaseStatus.COMPLETED

        payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")
        expense_asset_charter_account = chart_of_accounts.get("Inventory Asset")
        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")

        purchase = Purchase.objects.create(
            purchase_id=purchase_id,
            tracking_number=tracking_number,
            date=bill_date or date_type.today(),
            bill_date=bill_date,
            due_date=due_date,
            is_bill=is_bill,
            is_cheque=False,
            is_via_expense=False,
            supplier=supplier,
            company=company,
            warehouse=warehouse,
            created_by=employee,
            payment_method=None,
            charter_account=None,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=Decimal("0"),
            due_total=due_total,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
            tax_kind=tax_kind,
            description=memo,
            status=purchase_status,
        )

        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=company,
        )
        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.PURCHASE,
            purchase=purchase,
        )

        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=full_billing_address,
                company=company,
                status=AddressStatusChoices.ACTIVE,
            ),
            purchase=purchase,
            kind=AddressConnectorKindCoices.PURCHASE,
        )

        connector_data = []
        purchase_items = []

        for line in lines:
            line_kind = line.get("line_kind", "EXPENSE")
            description = line.get("description", "")
            line_total = Decimal(str(line.get("total") or "0"))
            tax = line.get("tax")

            if line_kind == "PRODUCT":
                product = line.get("product")
                quantity = int(line.get("quantity") or 1)
                purchase_price = Decimal(
                    str(line.get("purchase_price") or line.get("total") or "0")
                )
                purchase_item = PurchaseItem(
                    purchase=purchase,
                    status=PurchaseItemStatus.PUBLISHED,
                    kind=PurchaseItemkind.PRODUCT,
                    total=line_total,
                    quantity=quantity,
                    opening_quantity=quantity,
                    purchase_price=purchase_price,
                    description=description,
                    tax=tax,
                    product=product,
                    section=line.get("section"),
                    note=line.get("note"),
                )
                purchase_items.append((purchase_item, "PRODUCT", line_total, product, quantity))
            else:
                expense_account = line.get("expense_account")
                purchase_item = PurchaseItem(
                    purchase=purchase,
                    status=PurchaseItemStatus.PUBLISHED,
                    kind=PurchaseItemkind.EXPENSE,
                    total=line_total,
                    description=description,
                    tax=tax,
                    charter_account=expense_account,
                    section=line.get("section"),
                    note=line.get("note"),
                )
                purchase_items.append((purchase_item, "EXPENSE", line_total, expense_account, None))

        if purchase_items:
            created_items = PurchaseItem.objects.bulk_create(
                [item[0] for item in purchase_items]
            )

            for i, (_, line_kind, line_total, account_or_product, quantity) in enumerate(purchase_items):
                if not posting:
                    break  # non-posting document: no inventory, no balances
                created_item = created_items[i]

                if line_kind == "PRODUCT" and account_or_product:
                    # Only stocked items move stock. `d67d4b7e` established
                    # that for the bill serializer and stopped there: a
                    # SERVICE / PROJECT / EVENT product, or one flagged
                    # `is_non_stock`, ran the whole inventory block here --
                    # quantity set on something that has none, and its cost
                    # capitalised into Inventory Asset, where no inventory
                    # report can show it because they filter on `is_inventory`.
                    #
                    # The cost is still a cost, so it is redirected rather than
                    # dropped. Skipping the leg is what `4ab99db3` had to
                    # repair after the bare `continue` in the serializer.
                    tracks_stock = account_or_product.tracks_stock()
                    if tracks_stock:
                        update_quantity(account_or_product, "addition", quantity, 0)

                        # An imported bill is a bill: its goods become a cost
                        # layer like any other. `backfill_stock_ledger_layers`
                        # is a one-shot for stock predating this ledger and does
                        # not run per import, so without this the imported units
                        # carried no layer -- and `fifo_product_deduction` falls
                        # back to the lot walk only when the ledger is ENTIRELY
                        # empty. A product with any other layer therefore sold
                        # the imported units at the wrong cost, silently.
                        # `STOCK_LEDGER_DECISIONS.md` answer B1.
                        record_purchase_line_movement(
                            purchase, created_item, account_or_product, quantity,
                            unit_cost=created_item.purchase_price,
                        )
                    cost_account = (
                        expense_asset_charter_account
                        if tracks_stock
                        else resolve_cogs_account(account_or_product, company)
                    )

                    # Update inventory asset opening balance
                    if cost_account and line_total != 0:
                        inventory_action = action_for_side(
                            cost_account.kind,
                            JournalEntryConnectorKindChoices.DEBIT,
                        )
                        update_opening_balance(
                            cost_account,
                            balance_operation_for_action(inventory_action),
                            line_total,
                            0,
                        )
                        connector_data.append(
                            (
                                cost_account,
                                inventory_action,
                                line_total,
                                cost_account.opening_balance,
                                None,
                                None,
                                created_item,
                            )
                        )

                elif line_kind == "EXPENSE" and account_or_product and line_total != 0:
                    # A bill's cost line is ALWAYS a debit. The account is
                    # whatever the CSV row or recurring template named and can
                    # be any kind, so resolve the action from the side rather
                    # than assuming "addition" lands on a debit.
                    cost_action = action_for_side(
                        account_or_product.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        account_or_product,
                        balance_operation_for_action(cost_action),
                        line_total,
                        0,
                    )
                    connector_data.append(
                        (
                            account_or_product,
                            cost_action,
                            line_total,
                            account_or_product.opening_balance,
                            None,
                        )
                    )

        # Bill-specific: update supplier, A/P, and tax balances
        if posting and due_total != 0:
            # Update supplier opening balance
            update_opening_balance(
                supplier,
                JournalEntryConnectorKindChoices.CREDIT,
                due_total,
                0,
            )

            # Update accounts payable opening balance
            if payable_charter_account:
                payable_action = action_for_side(
                    payable_charter_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    payable_charter_account,
                    balance_operation_for_action(payable_action),
                    due_total,
                    0,
                )
                connector_data.append(
                    (
                        payable_charter_account,
                        payable_action,
                        due_total,
                        payable_charter_account.opening_balance,
                        None,
                    )
                )

        if posting and total_tax != 0 and tax_charter_account:
            # Input tax on a bill DEBITS the tax account (it pays down what is
            # owed); the entry only balances that way. Resolve from the side so
            # a differently-kinded tax account cannot flip it, and pair the
            # balance move to the action so a rollback unwinds to zero.
            tax_action = action_for_side(
                tax_charter_account.kind,
                JournalEntryConnectorKindChoices.DEBIT,
            )
            update_opening_balance(
                tax_charter_account,
                balance_operation_for_action(tax_action),
                total_tax,
                0,
            )
            connector_data.append(
                (
                    tax_charter_account,
                    tax_action,
                    total_tax,
                    tax_charter_account.opening_balance,
                    None,
                )
            )

        # Create journal entry (kind=PURCHASE for bills). A purchase order is a
        # commitment, not a transaction, so it produces no journal at all.
        if posting:
            journal_entry = JournalEntryService.create_journal_entry(
                amount=total + total_tax,
                status=JournalEntryStatusChoices.PUBLISHED,
                kind=JournalEntryKindChoices.PURCHASE,
                is_transaction=True,
                is_journal_entry=True,
                company=company,
                object=purchase,
            )

            JournalEntryService.create_journal_entry_connector(
                connector_data=connector_data,
                total=total + total_tax,
                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                journal_entry=journal_entry,
                supplier=supplier,
                created_by=employee,
            )

        if options.get("send_email"):
            try:
                
                supplier_email = supplier.email or ""
                emails = [e for e in [supplier_email] if e]
                if emails:
                    title = "BILL"
                    label = "bills"
                    backend_url = getattr(settings, "BASE_BACKEND_URL", None) or os.environ.get("BASE_BACKEND_URL", "http://localhost:8000")
                    product_purchase_items = purchase.purchaseitem_set.filter(kind=PurchaseItemkind.PRODUCT)
                    custom_expense_items = purchase.purchaseitem_set.filter(kind=PurchaseItemkind.EXPENSE)
                    pdf_file = generate_pdf_direct(company, {
                        "label": label,
                        "template": "emails/purchases/purchase_pdf_template.html",
                        "title": title,
                        "is_report": False,
                        "data": {
                            "company": company,
                            "supplier": supplier,
                            "full_billing_address": full_billing_address,
                            "supplier_email": supplier_email,
                            "purchase": purchase,
                            "purchase_items": product_purchase_items,
                            "custom_expense_items": custom_expense_items,
                            "has_deposit": False,
                            "deposit_amount": 0,
                            "has_due_total": due_total > 0,
                            "due_total": due_total,
                            "description": memo,
                        },
                    })
                    send_email_to_user(
                        {
                            "title": title,
                            "company": company,
                            "supplier": supplier,
                            "url": f"{backend_url}/{pdf_file.file.url}",
                            "document_type": title,
                        },
                        "emails/purchases/purchase_email_template.html",
                        emails,
                        f"Balanzify {title}",
                    )
            except Exception:
                logger.exception("Failed to send migration email for bill purchase uid=%s", purchase.uid)

        return purchase


class BillMigrationImporter:
    """Orchestrates bills migration import."""

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(
            f"[BILL IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}"
        )

        bill_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            bill_number = md.get("bill_number", "")
            group_key = f"{supplier_uid}::{bill_number}"
            bill_groups[group_key].append(row)

        print(f"[BILL IMPORTER] bill groups to process: {len(bill_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "bill_import_started"}
        )

        for group_key, group_rows in bill_groups.items():
            print(f"[BILL IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    supplier_uid_str = nd.get("supplier_uid", "")
                    bill_number = md.get("bill_number", "")

                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if not supplier:
                        raise ValueError(
                            f"Supplier with uid '{supplier_uid_str}' not found."
                        )

                    # Duplicate check
                    is_duplicate = (
                        Purchase.objects.filter(
                            company=company,
                            supplier=supplier,
                            is_bill=True,
                        )
                        .filter(
                            Q(purchase_id=bill_number)
                            | Q(tracking_number=bill_number)
                        )
                        .exists()
                    )

                    if is_duplicate:
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = (
                                f"Duplicate: Bill '{bill_number}' already exists for this vendor."
                            )
                            row.save(update_fields=["status", "message", "updated_at"])
                        continue

                    # Aggregate data from all rows in the group
                    bill_lines = []
                    bill_date = None
                    due_date = None
                    currency_kind = None
                    currency_rate = Decimal("1")
                    full_billing_address = ""
                    memo = ""
                    total = Decimal("0")
                    total_tax = Decimal("0")
                    warehouse = None

                    for row in group_rows:
                        rnd = row.normalized_data
                        rmd = row.mapped_data

                        if bill_date is None and rnd.get("bill_date"):
                            bill_date = parse_date(rnd["bill_date"], "YYYY-MM-DD")
                        if due_date is None and rnd.get("due_date"):
                            due_date = parse_date(rnd["due_date"], "YYYY-MM-DD")
                        if not currency_kind:
                            currency_kind = rmd.get("currency_kind") or job.currency
                        if rmd.get("currency_rate"):
                            try:
                                currency_rate = Decimal(str(rmd["currency_rate"]))
                            except Exception:
                                pass
                        if not full_billing_address:
                            full_billing_address = rmd.get("full_billing_address", "")
                        if not memo:
                            memo = rmd.get("memo", "")
                        if warehouse is None and rnd.get("warehouse_id"):
                            warehouse = Warehouse.objects.filter(
                                id=rnd["warehouse_id"]
                            ).first()

                        line_amount = Decimal(rnd.get("line_amount", "0") or "0")
                        total += line_amount

                        # Resolve tax
                        tax = None
                        tax_id = rnd.get("tax_id")
                        if tax_id:
                            tax = AgencyTax.objects.filter(id=tax_id).first()
                            if tax:
                                for tax_group in tax.tax_groups.all():
                                    tax_amount = (
                                        line_amount
                                        * Decimal(str(tax_group.rate))
                                        / Decimal("100")
                                    )
                                    total_tax += tax_amount

                        line_kind = rnd.get("line_kind", "EXPENSE")

                        qty = rnd.get("quantity")
                        unit_price = rnd.get("unit_price")
                        quantity = int(Decimal(str(qty))) if qty else 1
                        purchase_price = (
                            Decimal(str(unit_price)) if unit_price else line_amount
                        )

                        line_data = {
                            "line_kind": line_kind,
                            "total": line_amount,
                            "description": rmd.get("description", ""),
                            "tax": tax,
                            "quantity": quantity,
                            "purchase_price": purchase_price,
                        }

                        if line_kind == "PRODUCT":
                            product = None
                            product_id = rnd.get("product_id")
                            if product_id:
                                product = Product.objects.filter(id=product_id).first()
                            line_data["product"] = product
                        else:
                            expense_account = None
                            expense_account_id = rnd.get("expense_account_id")
                            if expense_account_id:
                                expense_account = ChartOfAccount.objects.filter(
                                    id=expense_account_id
                                ).first()
                            line_data["expense_account"] = expense_account

                        bill_lines.append(line_data)

                    bill_group_data = {
                        "supplier": supplier,
                        "bill_number": bill_number,
                        "bill_date": bill_date,
                        "due_date": due_date,
                        "currency_kind": currency_kind or job.currency,
                        "currency_rate": currency_rate,
                        "full_billing_address": full_billing_address,
                        "memo": memo,
                        "total": total,
                        "total_tax": total_tax,
                        "warehouse": warehouse,
                        "lines": bill_lines,
                    }

                    purchase = MigrationBillCreateService.create_bill(
                        bill_group_data,
                        user,
                        company,
                        options={"send_email": send_email, "source": "data_migration"},
                    )

                    for row in group_rows:
                        row.status = MigrationRowStatusChoices.IMPORTED
                        row.linked_record_uid = str(purchase.uid)
                        row.linked_record_type = "purchase"
                        row.message = "Successfully imported."
                        row.save(
                            update_fields=[
                                "status",
                                "linked_record_uid",
                                "linked_record_type",
                                "message",
                                "updated_at",
                            ]
                        )

                    imported += 1
                    MigrationAuditService.log(
                        job,
                        user,
                        CrudAction.CREATED,
                        {
                            "action": "bill_imported",
                            "bill_number": bill_number,
                            "purchase_uid": str(purchase.uid),
                        },
                    )

            except Exception as e:
                print(f"[BILL IMPORTER] FAILED group={group_key} error={e}")
                logger.exception(
                    "Bill migration importer failed for group %s: %s",
                    group_key,
                    e,
                )
                failed += 1
                for row in group_rows:
                    row.status = MigrationRowStatusChoices.FAILED
                    row.message = str(e)
                    row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "bill_import_failed",
                        "group_key": group_key,
                        "error": str(e),
                    },
                )

        job.imported_rows = job.rows.filter(
            status=MigrationRowStatusChoices.IMPORTED
        ).count()
        job.failed_rows = job.rows.filter(
            status=MigrationRowStatusChoices.FAILED
        ).count()
        job.skipped_rows = job.rows.filter(
            status=MigrationRowStatusChoices.SKIPPED
        ).count()
        job.completed_at = timezone.now()

        if imported > 0 and failed == 0:
            job.status = MigrationStatusChoices.COMPLETED
        elif imported > 0 and failed > 0:
            job.status = MigrationStatusChoices.PARTIALLY_COMPLETED
        else:
            job.status = MigrationStatusChoices.FAILED

        job.save(
            update_fields=[
                "imported_rows",
                "failed_rows",
                "skipped_rows",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        print(
            f"[BILL IMPORTER] DONE | imported={imported} failed={failed} "
            f"skipped={job.skipped_rows} job_status={job.status}"
        )
        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "bill_import_completed", "imported": imported, "failed": failed},
        )
