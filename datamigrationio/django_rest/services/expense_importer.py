import os
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.conf import settings

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)

from common.django_rest.helpers.file_helpers import generate_pdf_direct
from common.django_rest.helpers.emails import send_email_to_user


from purchaseio.models import Purchase, PurchaseItem, Expense, ExpenseConnector
from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchaseTaxKindChoices,
    ExpenseStatusChoices,
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
from paymentio.models import PaymentMethod

from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from datetime import date as date_type
from datamigrationio.django_rest.services.expense_validator import parse_date
from weapi.django_rest.helpers.sale_posting import resolve_cogs_account

logger = logging.getLogger(__name__)


class MigrationExpenseCreateService:
    """
    Standalone expense creation for data migration.
    Mirrors PrivateWeExpenseListSerializer.create() accounting logic:

    For each Purchase linked via ExpenseConnector:
      - PRODUCT lines: ONE bulk update_opening_balance(Inventory Asset, CREDIT, total-tax)
                       then per product item: update_quantity + 7-tuple connector
      - EXPENSE lines: per item update_opening_balance(charter_account, CREDIT, item.total)
                       + 5-tuple connector
      - Payment account: update_opening_balance(payment_account, DEBIT, purchase.total)
                         + 5-tuple connector ("substraction")
      - Tax: update_opening_balance(Sales Tax Payable, CREDIT, purchase.total_tax)
             + 5-tuple connector ("substraction")
    - JournalEntry kind=EXPENSE linked to the Expense record (not Purchase)
    """

    @staticmethod
    def create_expense(expense_group, user, company, options=None):
        """
        expense_group keys:
            supplier, payment_account, payment_method, expense_date,
            reference_number, currency_kind, currency_rate, description, memo,
            total, total_tax, lines

        Each line: product, expense_account, line_kind, quantity, purchase_price,
            total, tax, description

        Returns: Expense instance
        """
        options = options or {}
        supplier = expense_group["supplier"]
        payment_account = expense_group["payment_account"]
        payment_method = expense_group.get("payment_method")
        expense_date = expense_group["expense_date"]
        reference_number = expense_group.get("reference_number", "")
        currency_kind = expense_group.get("currency_kind") or getattr(
            company, "currency", "USD"
        )
        currency_rate = expense_group.get("currency_rate") or Decimal("1")
        description = expense_group.get("description", "")
        total = expense_group.get("total", Decimal("0"))
        total_tax = expense_group.get("total_tax", Decimal("0"))
        # An expense is settled when it is recorded, but only a caller that
        # knows that says so -- CSV import keeps the historical zeroes.
        deposit = expense_group.get("deposit", Decimal("0"))
        due_total = expense_group.get("due_total", Decimal("0"))
        lines = expense_group.get("lines", [])

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        # Create the Expense record
        expense = Expense.objects.create(
            date=expense_date or date_type.today(),
            reference_number=reference_number or None,
            status=ExpenseStatusChoices.PUBLISHED,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=deposit,
            due_total=due_total,
            discount=Decimal("0"),
            shipping_fee=Decimal("0"),
            description=description,
            supplier=supplier,
            payment_account=payment_account,
            payment_method=payment_method,
            created_by=employee,
        )

        # Create the Purchase record that backs this expense
        has_tax = bool(total_tax)
        # A caller with a document-level tax setting (e.g. a recurring template
        # marked INCLUSIVE) passes it explicitly; CSV import has none and keeps
        # the has-tax derivation.
        tax_kind = expense_group.get("tax_kind") or (
            PurchaseTaxKindChoices.EXCLUSIVE if has_tax else PurchaseTaxKindChoices.NO_TAX
        )

        tracking_number = get_unique_id(Purchase, company.id, "tracking_number", "PURCHASE")
        purchase_id = get_unique_id(Purchase, company.id, "purchase_id", "PUR")

        purchase = Purchase.objects.create(
            purchase_id=purchase_id,
            tracking_number=tracking_number,
            date=expense_date or date_type.today(),
            is_bill=False,
            is_cheque=False,
            is_via_expense=True,
            supplier=supplier,
            company=company,
            created_by=employee,
            payment_method=payment_method,
            charter_account=payment_account,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=deposit,
            due_total=due_total,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
            tax_kind=tax_kind,
            description=description,
            status=PurchaseStatus.COMPLETED,
        )

        # Create currency connector
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

        # Create address connector
        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address="",
                company=company,
                status=AddressStatusChoices.ACTIVE,
            ),
            purchase=purchase,
            kind=AddressConnectorKindCoices.PURCHASE,
        )

        # Link purchase to expense
        ExpenseConnector.objects.create(expense=expense, purchase=purchase)

        # Get chart of accounts for GL entries
        chart_of_accounts = get_chart_of_account(
            ["Sales Tax Payable", "Inventory Asset"],
            company,
        )
        tax_charter_account = chart_of_accounts.get("Sales Tax Payable")
        inventory_charter_account = chart_of_accounts.get("Inventory Asset")

        connector_data = []

        # Create purchase items and collect GL data
        purchase_items_to_create = []
        for line in lines:
            line_kind = line.get("line_kind", "EXPENSE")
            line_total = Decimal(str(line.get("total") or "0"))
            tax = line.get("tax")
            line_description = line.get("description", "")

            if line_kind == "PRODUCT":
                product = line.get("product")
                quantity = int(line.get("quantity") or 1)
                purchase_price = Decimal(
                    str(line.get("purchase_price") or line.get("total") or "0")
                )
                purchase_items_to_create.append(
                    (
                        PurchaseItem(
                            purchase=purchase,
                            status=PurchaseItemStatus.PUBLISHED,
                            kind=PurchaseItemkind.PRODUCT,
                            total=line_total,
                            quantity=quantity,
                            opening_quantity=quantity,
                            purchase_price=purchase_price,
                            description=line_description,
                            tax=tax,
                            product=product,
                        ),
                        "PRODUCT",
                        line_total,
                        product,
                        quantity,
                    )
                )
            else:
                expense_account = line.get("expense_account")
                purchase_items_to_create.append(
                    (
                        PurchaseItem(
                            purchase=purchase,
                            status=PurchaseItemStatus.PUBLISHED,
                            kind=PurchaseItemkind.EXPENSE,
                            total=line_total,
                            description=line_description,
                            tax=tax,
                            charter_account=expense_account,
                        ),
                        "EXPENSE",
                        line_total,
                        expense_account,
                        None,
                    )
                )

        if purchase_items_to_create:
            created_items = PurchaseItem.objects.bulk_create(
                [item[0] for item in purchase_items_to_create]
            )

            # Determine if there are any product items to do the bulk inventory update
            product_lines = [
                (created_items[i], line_total, product, qty)
                for i, (_, line_kind, line_total, product, qty) in enumerate(purchase_items_to_create)
                if line_kind == "PRODUCT"
            ]

            if product_lines and inventory_charter_account:
                # Stock arriving on an expense is always a DEBIT to inventory, so
                # resolve the action from the side. "Inventory Asset" is resolved by
                # title fallback when system_key is not backfilled, so its kind is
                # not guaranteed and a hard-coded "addition" can invert the leg.
                inventory_action = action_for_side(
                    inventory_charter_account.kind,
                    JournalEntryConnectorKindChoices.DEBIT,
                )
                # ONE bulk opening balance update for all product lines combined,
                # moved the way the connector action demands so the stored balance
                # and the journal cannot disagree.
                # The sum of the PRODUCT lines, not a document-wide figure. This
                # read `total - total_tax`, which is the whole document net of
                # tax -- so on a mixed expense (some product lines, some coded
                # straight to an expense account) the stored inventory balance
                # moved by the expense lines too, while the connectors below
                # move it by `line_total` each. The journal and the running
                # balance then disagree by the non-product portion, which no
                # debits-vs-credits check finds because the journal itself is
                # fine.
                # Split by whether the item actually holds stock. `d67d4b7e`
                # established that a SERVICE / PROJECT / EVENT product, or one
                # flagged `is_non_stock`, must not be treated as inventory --
                # quantity set on something that has none, and its cost
                # capitalised into Inventory Asset where no inventory report
                # can show it, because they filter on `is_inventory`. That fix
                # only reached the bill serializer.
                #
                # The cost is still a cost, so it is REDIRECTED rather than
                # dropped. Dropping it is what `4ab99db3` had to repair after
                # the bare `continue` left A/P credited and nothing debited.
                # Total debits are therefore unchanged by this split.
                stocked, unstocked = [], []
                for row in product_lines:
                    product = row[2]
                    if not product:
                        continue
                    (stocked if product.tracks_stock() else unstocked).append(row)

                inventory_total = sum(
                    (line_total for _, line_total, _, _ in stocked),
                    Decimal("0"),
                )
                if inventory_total != 0:
                    update_opening_balance(
                        inventory_charter_account,
                        balance_operation_for_action(inventory_action),
                        inventory_total,
                        0,
                    )

                # Per stocked item: update_quantity + 7-tuple connector
                for created_item, line_total, product, quantity in stocked:
                    update_quantity(product, "addition", quantity, 0)

                    # Stock bought through an imported expense is stock, for the
                    # same reason as the bill route. `STOCK_LEDGER_DECISIONS.md`
                    # answer B1.
                    record_purchase_line_movement(
                        purchase, created_item, product, quantity,
                        unit_cost=created_item.purchase_price,
                    )
                    connector_data.append(
                        (
                            inventory_charter_account,
                            inventory_action,
                            line_total,
                            inventory_charter_account.opening_balance,
                            None,
                            None,
                            created_item,
                        )
                    )

                # Per non-stocked item: the same debit, to where its cost
                # belongs. No quantity, no inventory.
                for created_item, line_total, product, quantity in unstocked:
                    cost_account = resolve_cogs_account(product, company)
                    if cost_account is None:
                        logger.error(
                            "expense import: %s of cost for %r has no cost "
                            "account, so its debit cannot be posted and the "
                            "entry will be short by it",
                            line_total, getattr(product, "title", product),
                        )
                        continue
                    if not line_total:
                        continue
                    cost_action = action_for_side(
                        cost_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        cost_account,
                        balance_operation_for_action(cost_action),
                        line_total,
                        0,
                    )
                    connector_data.append(
                        (
                            cost_account,
                            cost_action,
                            line_total,
                            cost_account.opening_balance,
                            None,
                            None,
                            created_item,
                        )
                    )

            # Per expense item: individual update + 5-tuple connector
            for i, (_, line_kind, line_total, expense_account, _qty) in enumerate(purchase_items_to_create):
                if line_kind == "EXPENSE" and expense_account and line_total != 0:
                    # A cost line is ALWAYS a debit, and the account it lands on is
                    # user-chosen -- coding a line to a LIABILITY/EQUITY/INCOME made
                    # "addition" resolve to CREDIT and inverted the leg (prod company
                    # 114, journal 1460: "MN Income Tax" credited, entry out by -2x).
                    line_action = action_for_side(
                        expense_account.kind,
                        JournalEntryConnectorKindChoices.DEBIT,
                    )
                    update_opening_balance(
                        expense_account,
                        balance_operation_for_action(line_action),
                        line_total,
                        0,
                    )
                    connector_data.append(
                        (
                            expense_account,
                            line_action,
                            line_total,
                            expense_account.opening_balance,
                            None,
                        )
                    )

        # The funding leg is fixed by the transaction: money leaving is ALWAYS a
        # credit. The payment account is user-chosen, and on a credit card (a
        # LIABILITY) or an owner-paid EQUITY account "substraction" resolves to
        # DEBIT and inverts the leg, so resolve the action from the side.
        # GROSS, not `total`. `total` is the lines ex-tax -- the recurring
        # builder says so itself by passing `deposit = total + total_tax`
        # (generation.py:_build_expense_group), and the CSV grouper accumulates
        # `total += line_amount` off the line amounts alone.
        #
        # The debits are the line totals plus `total_tax`, so crediting `total`
        # left every taxed expense short by exactly the tax. Money actually
        # leaving the payment account is the gross amount: that is what the
        # supplier was paid.
        payment_total = total + total_tax
        if payment_total != 0:
            payment_action = action_for_side(
                payment_account.kind,
                JournalEntryConnectorKindChoices.CREDIT,
            )
            update_opening_balance(
                payment_account,
                balance_operation_for_action(payment_action),
                payment_total,
                0,
            )
            connector_data.append(
                (
                    payment_account,
                    payment_action,
                    payment_total,
                    payment_account.opening_balance,
                    None,
                )
            )

        # Input tax paid on an expense is a DEBIT against the tax account (see the
        # import preview, expense_impact.py: debit=tax_amount). The stored balance
        # was being incremented as if this were a credit, so the journal and the
        # running balance disagreed and rollback re-added instead of unwinding.
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

        # Journal entry linked to the Expense record (not Purchase)
        journal_entry = JournalEntryService.create_journal_entry(
            amount=total,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.EXPENSE,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=expense,
        )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
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
                    title = "EXPENSE"
                    label = "expenses"
                    backend_url = getattr(settings, "BASE_BACKEND_URL", None) or os.environ.get("BASE_BACKEND_URL", "http://localhost:8000")
                    full_billing_address = expense_group.get("full_billing_address", "")
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
                            "purchase": expense,
                            "purchase_items": [],
                            "custom_expense_items": [],
                            "has_deposit": False,
                            "deposit_amount": 0,
                            "has_due_total": False,
                            "due_total": 0,
                            "description": description,
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
                        f"Pilucent {title}",
                    )
            except Exception:
                logger.exception("Failed to send migration email for expense uid=%s", expense.uid)

        return expense


class ExpenseMigrationImporter:
    """Orchestrates expenses migration import."""

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(
            f"[EXPENSE IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}"
        )

        # Group rows by supplier_uid::reference_number
        expense_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            reference_number = md.get("reference_number", "") or nd.get("expense_date", "")
            group_key = f"{supplier_uid}::{reference_number}"
            expense_groups[group_key].append(row)

        print(f"[EXPENSE IMPORTER] expense groups to process: {len(expense_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "expense_import_started"}
        )

        for group_key, group_rows in expense_groups.items():
            print(f"[EXPENSE IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    supplier_uid_str = nd.get("supplier_uid", "")
                    reference_number = md.get("reference_number", "")

                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if not supplier:
                        raise ValueError(
                            f"Supplier with uid '{supplier_uid_str}' not found."
                        )

                    # Resolve payment account from first row
                    payment_account_id = nd.get("payment_account_id")
                    payment_account = None
                    if payment_account_id:
                        payment_account = ChartOfAccount.objects.filter(
                            id=payment_account_id
                        ).first()

                    if not payment_account:
                        raise ValueError(
                            f"Payment account not found for expense '{reference_number}'."
                        )

                    # Duplicate check
                    if reference_number:
                        is_duplicate = Expense.objects.filter(
                            supplier=supplier,
                            reference_number=reference_number,
                            supplier__company=company,
                        ).exists()

                        if is_duplicate:
                            for row in group_rows:
                                row.status = MigrationRowStatusChoices.SKIPPED
                                row.message = (
                                    f"Duplicate: Expense '{reference_number}' already exists for this payee."
                                )
                                row.save(update_fields=["status", "message", "updated_at"])
                            continue

                    # Aggregate data from all rows in the group
                    expense_lines = []
                    expense_date = None
                    currency_kind = None
                    currency_rate = Decimal("1")
                    description = ""
                    total = Decimal("0")
                    total_tax = Decimal("0")
                    payment_method = None

                    for row in group_rows:
                        rnd = row.normalized_data
                        rmd = row.mapped_data

                        if expense_date is None and rnd.get("expense_date"):
                            expense_date = parse_date(rnd["expense_date"], "YYYY-MM-DD")
                        if not currency_kind:
                            currency_kind = rmd.get("currency_kind") or job.currency
                        if rmd.get("currency_rate"):
                            try:
                                currency_rate = Decimal(str(rmd["currency_rate"]))
                            except Exception:
                                pass
                        if not description:
                            description = rmd.get("memo", "") or rmd.get("description", "")
                        if payment_method is None and rnd.get("payment_method_id"):
                            payment_method = PaymentMethod.objects.filter(
                                id=rnd["payment_method_id"]
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

                        expense_lines.append(line_data)

                    expense_group_data = {
                        "supplier": supplier,
                        "payment_account": payment_account,
                        "payment_method": payment_method,
                        "expense_date": expense_date,
                        "reference_number": reference_number,
                        "currency_kind": currency_kind or job.currency,
                        "currency_rate": currency_rate,
                        "description": description,
                        "total": total,
                        "total_tax": total_tax,
                        "lines": expense_lines,
                    }

                    expense = MigrationExpenseCreateService.create_expense(
                        expense_group_data,
                        user,
                        company,
                        options={"send_email": send_email, "source": "data_migration"},
                    )

                    for row in group_rows:
                        row.status = MigrationRowStatusChoices.IMPORTED
                        row.linked_record_uid = str(expense.uid)
                        row.linked_record_type = "expense"
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
                            "action": "expense_imported",
                            "reference_number": reference_number,
                            "expense_uid": str(expense.uid),
                        },
                    )

            except Exception as e:
                print(f"[EXPENSE IMPORTER] FAILED group={group_key} error={e}")
                logger.exception(
                    "Expense migration importer failed for group %s: %s",
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
                        "action": "expense_import_failed",
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
            f"[EXPENSE IMPORTER] DONE | imported={imported} failed={failed} "
            f"skipped={job.skipped_rows} job_status={job.status}"
        )
        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "expense_import_completed", "imported": imported, "failed": failed},
        )
