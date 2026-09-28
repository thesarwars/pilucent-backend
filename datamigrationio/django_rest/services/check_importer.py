import os
import logging
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)

from purchaseio.models import Purchase, PurchaseItem
from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchaseTaxKindChoices,
)
from common.django_rest.helpers.file_helpers import generate_pdf_direct
from common.django_rest.helpers.emails import send_email_to_user

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
from datamigrationio.django_rest.services.check_validator import parse_date
from weapi.django_rest.helpers.sale_posting import resolve_cogs_account
"""Where a non-stocked line's cost belongs -- shared with the sale side, so
the two never disagree about the same product."""


logger = logging.getLogger(__name__)


class MigrationCheckCreateService:
    """
    Standalone check creation for data migration.
    Creates Purchase records with is_cheque=True.
    Mirrors PrivateWePurchaseListSerializer.create() cheque accounting logic:
    - Product lines: update_quantity + update_opening_balance(Inventory Asset, CREDIT)
    - Expense lines: update_opening_balance(expense_account, CREDIT)
    - update_opening_balance(bank_account, DEBIT, total_balance)  -- money out
    - update_opening_balance(Sales Tax Payable, CREDIT, total_tax)
    - JournalEntry kind=CHEQUE + connectors
    """

    @staticmethod
    def create_check(check_group, user, company, options=None):
        """
        check_group keys:
            supplier, check_number, check_date, bank_account, currency_kind, currency_rate,
            memo, total, total_tax, warehouse, lines

        Each line: product, expense_account, line_kind, quantity, purchase_price, total,
            description, tax

        Returns: Purchase instance
        """
        options = options or {}
        supplier = check_group["supplier"]
        check_number = check_group["check_number"]
        check_date = check_group["check_date"]
        bank_account = check_group["bank_account"]
        currency_kind = check_group.get("currency_kind") or getattr(
            company, "currency", "USD"
        )
        currency_rate = check_group.get("currency_rate") or Decimal("1")
        memo = check_group.get("memo", "")
        total = check_group.get("total", Decimal("0"))
        total_tax = check_group.get("total_tax", Decimal("0"))
        warehouse = check_group.get("warehouse")
        lines = check_group.get("lines", [])

        total_balance = total + total_tax
        tracking_number = get_unique_id(Purchase, company.id, "tracking_number", "PURCHASE")
        purchase_id = get_unique_id(Purchase, company.id, "purchase_id", "PUR")

        has_tax = any(line.get("tax") for line in lines)
        # A caller with a document-level tax setting (e.g. a recurring template
        # marked INCLUSIVE) passes it explicitly; CSV import has none and keeps
        # the has-tax derivation.
        tax_kind = check_group.get("tax_kind") or (
            PurchaseTaxKindChoices.EXCLUSIVE if has_tax else PurchaseTaxKindChoices.NO_TAX
        )

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        # Get chart of accounts needed for GL entries
        chart_of_accounts = get_chart_of_account(
            ["Inventory Asset", "Sales Tax Payable"],
            company,
        )
        expense_asset_charter_account = chart_of_accounts.get("Inventory Asset")
        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")

        purchase = Purchase.objects.create(
            purchase_id=purchase_id,
            tracking_number=tracking_number,
            date=check_date or date_type.today(),
            bill_date=None,
            due_date=None,
            is_bill=False,
            is_cheque=True,
            is_via_expense=False,
            cheque_number=check_number,
            supplier=supplier,
            company=company,
            warehouse=warehouse,
            created_by=employee,
            payment_method=None,
            charter_account=bank_account,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=Decimal("0"),
            due_total=total_balance,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
            tax_kind=tax_kind,
            description=memo,
            status=PurchaseStatus.COMPLETED,
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
                full_address="",
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
                        # Buying stock always DEBITs the inventory account,
                        # whatever kind it resolves to.
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
                    # A cheque's cost line is ALWAYS a debit, whatever account the
                    # user coded it to. "addition" only resolves to DEBIT on asset
                    # and expense accounts; a line coded to a liability, equity or
                    # income account -- which the validator accepts, it filters on
                    # status alone -- posted a CREDIT instead, leaving the entry
                    # out of balance by twice the line.
                    expense_action = action_for_side(
                        account_or_product.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        account_or_product,
                        balance_operation_for_action(expense_action),
                        line_total,
                        0,
                    )
                    connector_data.append(
                        (
                            account_or_product,
                            expense_action,
                            line_total,
                            account_or_product.opening_balance,
                            None,
                        )
                    )

        # Cheque-specific: the funding leg is ALWAYS a credit (money out),
        # whatever kind the account it is drawn on happens to be.
        # "substraction" only resolves to CREDIT on asset and expense accounts,
        # so a cheque drawn on a credit-card or other liability account posted a
        # DEBIT and left the entry with no credit side at all.
        if bank_account and total_balance != 0:
            bank_action = action_for_side(
                bank_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                bank_account,
                balance_operation_for_action(bank_action),
                total_balance,
                0,
            )
            connector_data.append(
                (
                    bank_account,
                    bank_action,
                    total_balance,
                    bank_account.opening_balance,
                    None,
                )
            )

        # Tax payable. The bank is credited total + tax, so the tax leg has to be
        # the matching DEBIT for the entry to balance -- and the stored balance
        # must move the same way the journal line does. The hard-coded CREDIT
        # ADDED to a liability the journal was debiting, so the running balance
        # disagreed with the ledger on every import, and the rollback (which
        # derives its undo from the connector kind) added it a second time.
        if total_tax != 0 and tax_charter_account:
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

        # Create journal entry (kind=CHEQUE for checks)
        journal_entry = JournalEntryService.create_journal_entry(
            amount=total_balance,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.CHEQUE,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=purchase,
        )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total_balance,
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
                    title = "CHEQUE"
                    label = "cheques"
                    backend_url = getattr(settings, "BASE_BACKEND_URL", None) or os.environ.get("BASE_BACKEND_URL", "http://localhost:8000")
                    full_billing_address = check_group.get("full_billing_address", "")
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
                            "has_due_total": False,
                            "due_total": 0,
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
                logger.exception("Failed to send migration email for check purchase uid=%s", purchase.uid)

        return purchase


class CheckMigrationImporter:
    """Orchestrates checks migration import."""

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(
            f"[CHECK IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}"
        )

        check_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            check_number = md.get("check_number", "")
            group_key = f"{supplier_uid}::{check_number}"
            check_groups[group_key].append(row)

        print(f"[CHECK IMPORTER] check groups to process: {len(check_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "check_import_started"}
        )

        for group_key, group_rows in check_groups.items():
            print(f"[CHECK IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    supplier_uid_str = nd.get("supplier_uid", "")
                    check_number = md.get("check_number", "")

                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if not supplier:
                        raise ValueError(
                            f"Supplier with uid '{supplier_uid_str}' not found."
                        )

                    # Resolve bank account from first row
                    bank_account_id = nd.get("bank_account_id")
                    bank_account = None
                    if bank_account_id:
                        bank_account = ChartOfAccount.objects.filter(
                            id=bank_account_id
                        ).first()

                    if not bank_account:
                        raise ValueError(
                            f"Bank account not found for check '{check_number}'."
                        )

                    # Duplicate check
                    is_duplicate = (
                        Purchase.objects.filter(
                            company=company,
                            supplier=supplier,
                            is_cheque=True,
                        )
                        .filter(
                            Q(purchase_id=check_number)
                            | Q(tracking_number=check_number)
                            | Q(cheque_number=check_number)
                        )
                        .exists()
                    )

                    if is_duplicate:
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = (
                                f"Duplicate: Check '{check_number}' already exists for this vendor."
                            )
                            row.save(update_fields=["status", "message", "updated_at"])
                        continue

                    # Aggregate data from all rows in the group
                    check_lines = []
                    check_date = None
                    currency_kind = None
                    currency_rate = Decimal("1")
                    memo = ""
                    total = Decimal("0")
                    total_tax = Decimal("0")
                    warehouse = None

                    for row in group_rows:
                        rnd = row.normalized_data
                        rmd = row.mapped_data

                        if check_date is None and rnd.get("check_date"):
                            check_date = parse_date(rnd["check_date"], "YYYY-MM-DD")
                        if not currency_kind:
                            currency_kind = rmd.get("currency_kind") or job.currency
                        if rmd.get("currency_rate"):
                            try:
                                currency_rate = Decimal(str(rmd["currency_rate"]))
                            except Exception:
                                pass
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

                        check_lines.append(line_data)

                    check_group_data = {
                        "supplier": supplier,
                        "check_number": check_number,
                        "check_date": check_date,
                        "bank_account": bank_account,
                        "currency_kind": currency_kind or job.currency,
                        "currency_rate": currency_rate,
                        "memo": memo,
                        "total": total,
                        "total_tax": total_tax,
                        "warehouse": warehouse,
                        "lines": check_lines,
                    }

                    purchase = MigrationCheckCreateService.create_check(
                        check_group_data,
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
                            "action": "check_imported",
                            "check_number": check_number,
                            "purchase_uid": str(purchase.uid),
                        },
                    )

            except Exception as e:
                print(f"[CHECK IMPORTER] FAILED group={group_key} error={e}")
                logger.exception(
                    "Check migration importer failed for group %s: %s",
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
                        "action": "check_import_failed",
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
            f"[CHECK IMPORTER] DONE | imported={imported} failed={failed} "
            f"skipped={job.skipped_rows} job_status={job.status}"
        )
        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "check_import_completed", "imported": imported, "failed": failed},
        )
