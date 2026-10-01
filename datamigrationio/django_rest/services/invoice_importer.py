import os
import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datamigrationio.models import DataMigrationRow
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationDuplicateHandlingChoices,
)
from common.django_rest.helpers.file_helpers import generate_pdf_direct
from common.django_rest.helpers.emails import send_email_to_user

from salesio.models import Sale, SaleItem
from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices, SalesStatusChoices
from common.choices import TaxKindChoices, DiscountKind
from common.django_rest.helpers.id_generator import get_unique_id
from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.fifo_product_quantity_helpers import (
    as_purchase_item,
    fifo_product_deduction,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector
from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices
from termio.models import TermConnector
from termio.choicess import TermKindChoices
from journalio.django_rest.services.journals import JournalEntryService
from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)


from customerio.models import Customer
from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from termio.models import Term
from salesio.models import Sale
from django.db.models import Q
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction


from datetime import date as date_type
from datamigrationio.django_rest.services.invoice_validator import parse_date

logger = logging.getLogger(__name__)


class MigrationInvoiceCreateService:
    """
    Standalone invoice creation service for data migration.
    Calls the same low-level helpers as PrivateWeSaleListSerializer but is
    completely independent — does NOT import or call the existing serializer.
    Email and PDF generation are skipped by default.
    """

    @staticmethod
    def create_invoice(invoice_group, user, company, options=None):
        """
        invoice_group dict keys:
            customer, invoice_number, invoice_date, due_date,
            currency_kind, currency_rate, full_billing_address,
            full_shipping_address, shipping_by, shipping_date, term,
            memo, total, total_tax, due_total, receivable_account, lines

        Each line in lines:
            product, income_account, quantity, sale_price, total,
            description, tax, is_tax

        Returns: Sale instance
        """
        
        options = options or {}
        customer = invoice_group["customer"]
        invoice_number = invoice_group["invoice_number"]
        invoice_date = invoice_group["invoice_date"]
        due_date = invoice_group["due_date"]
        currency_kind = invoice_group.get("currency_kind") or company.currency if hasattr(company, "currency") else "USD"
        currency_rate = invoice_group.get("currency_rate") or Decimal("1")
        full_billing_address = invoice_group.get("full_billing_address", "")
        full_shipping_address = invoice_group.get("full_shipping_address", "")
        shipping_by = invoice_group.get("shipping_by")
        shipping_date = invoice_group.get("shipping_date")
        term = invoice_group.get("term")
        memo = invoice_group.get("memo", "")
        total = invoice_group.get("total", Decimal("0"))
        total_tax = invoice_group.get("total_tax", Decimal("0"))
        due_total = invoice_group.get("due_total", total)
        receivable_account = invoice_group.get("receivable_account")
        # Document-level inputs a caller with a template carries; defaults keep
        # CSV import posting exactly as before.
        warehouse = invoice_group.get("warehouse")
        deposit = invoice_group.get("deposit", Decimal("0"))
        discount = invoice_group.get("discount", Decimal("0"))
        discount_kind = invoice_group.get("discount_kind") or DiscountKind.FLAT
        shipping_fee = invoice_group.get("shipping_fee", Decimal("0"))
        lines = invoice_group.get("lines", [])

        # Generate unique invoice tracking number
        tracking_number = get_unique_id(Sale, company.id, "tracking_number", "INV")
        invoice_id = tracking_number
        reference_number = invoice_number  # preserve imported invoice number as reference

        # Determine tax kind
        has_tax = any(line.get("tax") for line in lines)
        tax_kind = invoice_group.get("tax_kind") or (
            TaxKindChoices.EXCLUSIVE if has_tax else TaxKindChoices.NO_TAX
        )

        # Build email JSON
        email_json = {
            "customer_email": customer.email or "",
            "cc_emails": "",
            "bcc_emails": "",
        }

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        # Create Sale
        sale = Sale.objects.create(
            invoice_id=invoice_id,
            tracking_number=tracking_number,
            reference_number=reference_number,
            date=invoice_date,
            invoice_date=invoice_date,
            due_date=due_date,
            is_invoice=True,
            is_estimated=False,
            is_sale_receipt=False,
            kind=SaleReceptKindChoices.SALE,
            customer=customer,
            company=company,
            warehouse=warehouse,
            created_by=employee,
            payment_method=None,
            receivable_charter_account=receivable_account,
            payable_charter_account=None,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=deposit,
            due_total=due_total,
            discount=discount,
            discount_kind=discount_kind,
            shipping_fee=shipping_fee,
            tax_kind=tax_kind,
            description=memo,
            email=email_json,
            status=SalesStatusChoices.OPEN,
        )

        # Term connector
        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.SALE,
                sale=sale,
                term=term,
            )

        # Currency connector
        currency, _ = Currency.objects.get_or_create(
            kind=currency_kind,
            exchange_rate=currency_rate,
            company=company,
        )
        CurrencyConnector.objects.create(
            currency=currency,
            model_kind=CurrencyConnectorModelKind.SALE,
            sale=sale,
        )

        # Billing address connector
        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=full_billing_address,
                company=company,
            ),
            sale=sale,
            kind=AddressConnectorKindCoices.SALE,
        )

        # Shipping address connector
        if shipping_by or shipping_date or full_shipping_address:
            AddressConnector.objects.create(
                address=Address.objects.create(
                    full_address=full_shipping_address,
                    shipping_by=shipping_by,
                    shipping_date=shipping_date or date_type.today(),
                    is_shipping=True,
                    company=company,
                ),
                sale=sale,
                kind=AddressConnectorKindCoices.SALE,
            )

        # Create sale items and handle FIFO inventory
        connector_data = []
        sale_items = []

        for line in lines:
            product = line.get("product")
            income_account = line.get("income_account")
            quantity = int(line.get("quantity") or 1)
            sale_price = Decimal(str(line.get("sale_price") or line.get("total") or "0"))
            line_total = Decimal(str(line.get("total") or "0"))
            description = line.get("description", "")
            tax = line.get("tax")
            is_tax = bool(tax)

            sale_item = SaleItem(
                sale=sale,
                product=product,
                quantity=quantity,
                sale_price=sale_price,
                total=line_total,
                description=description,
                is_tax=is_tax,
                tax=tax,
                status=SaleItemStatusChoices.PUBLISHED,
                section=None,
                note=None,
            )
            sale_items.append(sale_item)

            # FIFO inventory deduction
            if product:
                product_income_account = income_account or (product.income_account if product else None)
                product_asset_account = product.asset_account if product else None

                remaining, deduction_details, _ = fifo_product_deduction(product, quantity)

                product_additional_cost = product.productadditionalcost_set.first() if product else None
                cost_of_good_sold_account = (
                    product_additional_cost.expense_account
                    if product_additional_cost
                    else None
                )

                # --- Revenue -------------------------------------------------
                # Recognised from the INVOICE, once per line -- not from what
                # FIFO managed to deduct.
                #
                # This sat inside the loop below, so revenue was a function of
                # consumed inventory. A service product or an out-of-stock item
                # consumes no layers, the loop never ran, and the entry got a
                # full debit to Accounts Receivable with no credit anywhere.
                # Partial stock was quieter and worse: 4 of 10 units on hand
                # recognised 40% of the revenue and dropped the rest.
                #
                # `4567a927` fixed exactly this in the OTHER sale engine on
                # 2026-08-06. This importer is a second engine that was never
                # folded in, and it runs unattended on the recurring beat, so it
                # kept writing the same defect nightly after the interactive
                # path stopped.
                #
                # Basis is `line_total`, not `sale_price * quantity`. The
                # receivable follows the header (`due_total = total + tax`), and
                # `sale_price` falls back to the line total at :223 -- so a row
                # carrying quantity 3 and total 300 with no unit price would
                # otherwise credit 900 against a 300 receivable. Six production
                # lines have exactly that shape. It also matches the service
                # branch below, which has always used `line_total`.
                income_action = (
                    action_for_side(
                        product_income_account.kind,
                        JournalEntryConnectorKindChoices.CREDIT,
                    )
                    if product_income_account
                    else None
                )
                if product_income_account and line_total:
                    update_opening_balance(
                        product_income_account,
                        balance_operation_for_action(income_action),
                        line_total,
                        0,
                    )
                    connector_data.append((
                        product_income_account,
                        income_action,
                        line_total,
                        product_income_account.opening_balance,
                        None,
                        sale_item,
                        # No single purchase layer backs the revenue -- it
                        # belongs to the line, not to a lot.
                        None,
                    ))
                elif line_total:
                    # The receivable is still debited for this line, so saying
                    # nothing here means a silently short entry.
                    logger.error(
                        "invoice import: %s of revenue on a line for %r has no "
                        "income account, so the entry will not balance",
                        line_total, getattr(product, "title", product),
                    )

                # --- Inventory relief and cost of sales ----------------------
                # These DO belong per layer: each consumed lot has its own cost,
                # which is the point of FIFO.
                for layer_source, qty, price in deduction_details:
                    purchase_item = as_purchase_item(layer_source)
                    if qty <= 0:
                        continue

                    individual_cost = price * qty

                    if cost_of_good_sold_account:
                        update_opening_balance(cost_of_good_sold_account, "credit", individual_cost, 0)

                    # Inventory relief always CREDITS and cost of sales always
                    # DEBITS -- the transaction fixes each side, not the account
                    # it happens to be coded to.
                    asset_action = (
                        action_for_side(
                            product_asset_account.kind,
                            JournalEntryConnectorKindChoices.CREDIT,
                        )
                        if product_asset_account
                        else None
                    )
                    cogs_action = (
                        action_for_side(
                            cost_of_good_sold_account.kind,
                            JournalEntryConnectorKindChoices.DEBIT,
                        )
                        if cost_of_good_sold_account
                        else None
                    )

                    # Revenue is NOT here any more -- it is posted once per line
                    # above. Leaving it in the loop is what made income a
                    # function of consumed stock, and it also meant the
                    # document's revenue was credited once PER LAYER, so a line
                    # drawing on three lots recognised it three times.
                    if product_asset_account:
                        update_opening_balance(
                            product_asset_account,
                            balance_operation_for_action(asset_action),
                            individual_cost,
                            0,
                        )

                    if product_asset_account:
                        connector_data.append((
                            product_asset_account,
                            asset_action,
                            individual_cost,
                            product_asset_account.opening_balance,
                            None,
                            sale_item,
                            purchase_item,
                        ))

                    if cost_of_good_sold_account:
                        connector_data.append((
                            cost_of_good_sold_account,
                            cogs_action,
                            individual_cost,
                            cost_of_good_sold_account.opening_balance,
                            None,
                            sale_item,
                            purchase_item,
                        ))

            elif income_account:
                # Service line: no product, post directly to income account
                service_action = action_for_side(
                    income_account.kind, JournalEntryConnectorKindChoices.CREDIT
                )
                update_opening_balance(
                    income_account,
                    balance_operation_for_action(service_action),
                    line_total,
                    0,
                )
                connector_data.append((
                    income_account,
                    service_action,
                    line_total,
                    income_account.opening_balance,
                    None,
                    sale_item,
                    None,
                ))

        SaleItem.objects.bulk_create(sale_items)

        # Accounting postings
        # Update customer opening balance
        update_opening_balance(customer, "credit", due_total, 0)

        # Update receivable account
        if receivable_account:
            # An invoice always DEBITS what it is receivable against.
            receivable_action = action_for_side(
                receivable_account.kind, JournalEntryConnectorKindChoices.DEBIT
            )
            update_opening_balance(
                receivable_account,
                balance_operation_for_action(receivable_action),
                due_total,
                0,
            )
            if due_total != 0:
                connector_data.append((
                    receivable_account,
                    receivable_action,
                    due_total,
                    receivable_account.opening_balance,
                    None,
                ))

        # Per-item tax postings
        for line in lines:
            tax = line.get("tax")
            line_total = Decimal(str(line.get("total") or "0"))
            is_tax = line.get("is_tax", False)
            if not is_tax or not tax:
                continue
            for tax_group in tax.tax_groups.all():
                payable_account = tax_group.sales_tax_account
                tax_amount = line_total * (Decimal(str(tax_group.rate)) / Decimal("100"))
                tax_action = action_for_side(
                    payable_account.kind,
                    JournalEntryConnectorKindChoices.CREDIT,
                )
                update_opening_balance(
                    payable_account,
                    balance_operation_for_action(tax_action),
                    tax_amount,
                    0,
                )
                if total_tax != 0:
                    connector_data.append((
                        payable_account,
                        tax_action,
                        tax_amount,
                        payable_account.opening_balance,
                        None,
                    ))

        # Journal entry
        undeposited_funds_map = get_chart_of_account(["Undeposited Funds"], company)
        undeposited_funds_account = undeposited_funds_map.get("Undeposited Funds")
        is_deposit = (
            receivable_account is not None
            and undeposited_funds_account is not None
            and receivable_account.uid == undeposited_funds_account.uid
        )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=total,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE,
            is_transaction=True,
            is_journal_entry=True,
            is_deposit=is_deposit,
            company=company,
            object=sale,
        )

        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=total,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            customer=customer,
            created_by=employee,
        )

        if options.get("send_email"):
            try:
                
                customer_email = customer.email or ""
                emails = [e for e in [customer_email] if e]
                if emails:
                    title = "INVOICE"
                    label = "invoices"
                    backend_url = getattr(settings, "BASE_BACKEND_URL", None) or os.environ.get("BASE_BACKEND_URL", "http://localhost:8000")
                    customer_address = customer.addressconnector_set.first()
                    pdf_file = generate_pdf_direct(company, {
                        "label": label,
                        "template": "emails/invoices/invoice_pdf_template.html",
                        "title": title,
                        "is_report": False,
                        "data": {
                            "company": company,
                            "customer": customer,
                            "customer_address": customer_address.address if customer_address else "",
                            "customer_email": customer_email,
                            "billing_address": full_billing_address,
                            "shipping_address": full_shipping_address,
                            "shipping_date": shipping_date,
                            "shipping_by": shipping_by,
                            "tracking_number": sale.tracking_number,
                            "reference_number": sale.reference_number,
                            "invoice_date": invoice_date,
                            "date": sale.date,
                            "deposit_to": receivable_account,
                            "refund_from": None,
                            "kind": sale.kind,
                            "payment_method": None,
                            "location": "",
                            "invoice_due_date": due_date,
                            "term": term,
                            "description": memo,
                            "total_tax": float(total_tax),
                            "deposit": 0.00,
                            "total": float(total),
                            "due_total": float(due_total),
                            "sale_items": SaleItem.objects.filter(sale=sale),
                        },
                    })
                    send_email_to_user(
                        {
                            "title": title,
                            "company": company,
                            "customer": customer,
                            "url": f"{backend_url}/{pdf_file.file.url}",
                        },
                        "emails/invoices/invoice_email_template.html",
                        emails,
                        f"Pilucent {title}",
                    )
            except Exception:
                logger.exception("Failed to send migration email for invoice sale uid=%s", sale.uid)

        return sale


class InvoiceMigrationImporter:
    """
    Orchestrates the full import: groups rows by invoice, calls
    MigrationInvoiceCreateService per invoice group, updates row/job statuses.
    """

    @staticmethod
    def run(job, user, company, options=None):
        
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(f"[IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}")

        # Get receivable account once
        chart_map = get_chart_of_account(["Accounts Receivable (A/R)"], company)
        receivable_account = chart_map.get("Accounts Receivable (A/R)")
        print(f"[IMPORTER] receivable_account={receivable_account}")

        # Group rows by customer_uid + invoice_number
        invoice_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            customer_uid = nd.get("customer_uid", "")
            invoice_number = md.get("invoice_number", "")
            group_key = f"{customer_uid}::{invoice_number}"
            invoice_groups[group_key].append(row)

        print(f"[IMPORTER] invoice groups to process: {len(invoice_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(job, user, CrudAction.UPDATED, {"action": "import_started"})

        for group_key, group_rows in invoice_groups.items():
            print(f"[IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    customer_uid_str = nd.get("customer_uid", "")
                    invoice_number = md.get("invoice_number", "")
                    print(f"[IMPORTER] customer_uid={customer_uid_str} invoice_number={invoice_number}")

                    # Safety: re-check duplicate
                    customer = Customer.objects.filter(uid=customer_uid_str).first()
                    if not customer:
                        print(f"[IMPORTER] ERROR: Customer not found for uid={customer_uid_str}")
                        raise ValueError(f"Customer with uid '{customer_uid_str}' not found.")

                    is_duplicate = Sale.objects.filter(
                        company=company,
                        customer=customer,
                        is_invoice=True,
                    ).filter(
                        Q(invoice_id=invoice_number)
                        | Q(tracking_number=invoice_number)
                        | Q(reference_number=invoice_number)
                    ).exists()

                    if is_duplicate:
                        print(f"[IMPORTER] SKIPPED duplicate: invoice_number={invoice_number}")
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = f"Duplicate: Invoice '{invoice_number}' already exists."
                            row.save(update_fields=["status", "message", "updated_at"])
                        continue

                    # Build invoice lines from all rows in group
                    invoice_lines = []
                    invoice_date = None
                    due_date = None
                    currency_kind = None
                    currency_rate = Decimal("1")
                    full_billing_address = ""
                    full_shipping_address = ""
                    shipping_by = None
                    shipping_date = None
                    term = None
                    memo = ""
                    total = Decimal("0")
                    total_tax = Decimal("0")

                    for row in group_rows:
                        rnd = row.normalized_data
                        rmd = row.mapped_data

                        # Invoice-level fields from first row
                        if invoice_date is None and rnd.get("invoice_date"):
                            invoice_date = parse_date(rnd["invoice_date"], "YYYY-MM-DD")
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
                        if not full_shipping_address:
                            full_shipping_address = rmd.get("full_shipping_address", "")
                        if not shipping_by:
                            shipping_by = rmd.get("shipping_by")
                        if not shipping_date and rmd.get("shipping_date"):
                            shipping_date = parse_date(rmd["shipping_date"], job.date_format)
                        if not term and rnd.get("term_id"):
                            term = Term.objects.filter(id=rnd["term_id"]).first()
                        if not memo:
                            memo = rmd.get("memo", "")

                        # Line item
                        line_amount = Decimal(rnd.get("line_amount", "0") or "0")
                        total += line_amount

                        product = None
                        product_id = rnd.get("product_id")
                        if product_id:
                            from productio.models import Product
                            product = Product.objects.filter(id=product_id).first()

                        income_account = None
                        income_account_id = rnd.get("income_account_id")
                        if income_account_id:
                            income_account = ChartOfAccount.objects.filter(id=income_account_id).first()
                        elif product and product.income_account:
                            income_account = product.income_account

                        tax = None
                        tax_id = rnd.get("tax_id")
                        if tax_id:
                            tax = AgencyTax.objects.filter(id=tax_id).first()
                            if tax:
                                for tax_group in tax.tax_groups.all():
                                    tax_amount = line_amount * Decimal(str(tax_group.rate)) / Decimal("100")
                                    total_tax += tax_amount

                        qty = rnd.get("quantity")
                        unit_price = rnd.get("unit_price")
                        quantity = int(Decimal(str(qty))) if qty else 1
                        sale_price = Decimal(str(unit_price)) if unit_price else line_amount

                        invoice_lines.append({
                            "product": product,
                            "income_account": income_account,
                            "quantity": quantity,
                            "sale_price": sale_price,
                            "total": line_amount,
                            "description": rmd.get("description", ""),
                            "tax": tax,
                            "is_tax": bool(tax),
                        })

                    due_total = total + total_tax

                    invoice_group_data = {
                        "customer": customer,
                        "invoice_number": invoice_number,
                        "invoice_date": invoice_date,
                        "due_date": due_date,
                        "currency_kind": currency_kind or job.currency,
                        "currency_rate": currency_rate,
                        "full_billing_address": full_billing_address,
                        "full_shipping_address": full_shipping_address,
                        "shipping_by": shipping_by,
                        "shipping_date": shipping_date,
                        "term": term,
                        "memo": memo,
                        "total": total,
                        "total_tax": total_tax,
                        "due_total": due_total,
                        "receivable_account": receivable_account,
                        "lines": invoice_lines,
                    }

                    print(f"[IMPORTER] Calling create_invoice for invoice_number={invoice_number} total={invoice_group_data['total']} due_total={invoice_group_data['due_total']} lines={len(invoice_group_data['lines'])}")
                    sale = MigrationInvoiceCreateService.create_invoice(
                        invoice_group_data,
                        user,
                        company,
                        options={"send_email": send_email, "source": "data_migration"},
                    )
                    print(f"[IMPORTER] Invoice created: sale_uid={sale.uid} sale_status={sale.status}")

                    for row in group_rows:
                        row.status = MigrationRowStatusChoices.IMPORTED
                        row.linked_record_uid = str(sale.uid)
                        row.linked_record_type = "sale"
                        row.message = "Successfully imported."
                        row.save(update_fields=["status", "linked_record_uid", "linked_record_type", "message", "updated_at"])

                    imported += 1
                    MigrationAuditService.log(
                        job, user, CrudAction.CREATED,
                        {"action": "invoice_imported", "invoice_number": invoice_number, "sale_uid": str(sale.uid)},
                    )

            except Exception as e:
                print(f"[IMPORTER] FAILED group={group_key} error={e}")
                logger.exception("Migration importer failed for group %s: %s", group_key, e)
                failed += 1
                for row in group_rows:
                    row.status = MigrationRowStatusChoices.FAILED
                    row.message = str(e)
                    row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job, user, CrudAction.UPDATED,
                    {"action": "invoice_failed", "group_key": group_key, "error": str(e)},
                )

        # Update job counters
        job.imported_rows = job.rows.filter(status=MigrationRowStatusChoices.IMPORTED).count()
        job.failed_rows = job.rows.filter(status=MigrationRowStatusChoices.FAILED).count()
        job.skipped_rows = job.rows.filter(status=MigrationRowStatusChoices.SKIPPED).count()
        job.completed_at = timezone.now()

        if imported > 0 and failed == 0:
            job.status = MigrationStatusChoices.COMPLETED
        elif imported > 0 and failed > 0:
            job.status = MigrationStatusChoices.PARTIALLY_COMPLETED
        else:
            job.status = MigrationStatusChoices.FAILED

        job.save(update_fields=[
            "imported_rows", "failed_rows", "skipped_rows",
            "status", "completed_at", "updated_at",
        ])

        print(f"[IMPORTER] DONE | imported={imported} failed={failed} skipped={job.skipped_rows} job_status={job.status}")
        MigrationAuditService.log(
            job, user, CrudAction.UPDATED,
            {"action": "import_completed", "imported": imported, "failed": failed},
        )
