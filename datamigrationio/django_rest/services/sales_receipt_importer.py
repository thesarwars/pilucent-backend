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

from common.django_rest.helpers.file_helpers import generate_pdf_direct
from common.django_rest.helpers.emails import send_email_to_user

from salesio.models import Sale, SaleItem
from salesio.choices import (
    SaleItemStatusChoices,
    SaleReceptKindChoices,
    SalesStatusChoices,
)
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
from wirehouseio.models import Warehouse

from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from datetime import date as date_type
from datamigrationio.django_rest.services.sales_receipt_validator import parse_date

logger = logging.getLogger(__name__)


class MigrationSaleReceiptCreateService:
    """
    Standalone sales receipt creation for data migration.
    Mirrors PrivateWeSaleListSerializer / invoice migration behavior:
    FIFO, update_opening_balance, JournalEntryService with SALE_RECEPT.
    """

    @staticmethod
    def create_receipt(receipt_group, user, company, options=None):
        """
        receipt_group keys:
            customer, receipt_number, receipt_date, currency_kind, currency_rate,
            full_billing_address, full_shipping_address, shipping_by, shipping_date,
            term, memo, total, total_tax, deposit_account, warehouse, lines

        Each line: product, income_account, quantity, sale_price, total,
            description, tax, is_tax

        Returns: Sale instance
        """
        options = options or {}
        customer = receipt_group["customer"]
        receipt_number = receipt_group["receipt_number"]
        receipt_date = receipt_group["receipt_date"]
        currency_kind = receipt_group.get("currency_kind") or (
            company.currency if hasattr(company, "currency") else "USD"
        )
        currency_rate = receipt_group.get("currency_rate") or Decimal("1")
        full_billing_address = receipt_group.get("full_billing_address", "")
        full_shipping_address = receipt_group.get("full_shipping_address", "")
        shipping_by = receipt_group.get("shipping_by")
        shipping_date = receipt_group.get("shipping_date")
        term = receipt_group.get("term")
        memo = receipt_group.get("memo", "")
        total = receipt_group.get("total", Decimal("0"))
        total_tax = receipt_group.get("total_tax", Decimal("0"))
        deposit_account = receipt_group.get("deposit_account")
        warehouse = receipt_group.get("warehouse")
        lines = receipt_group.get("lines", [])

        deposit_total = total + total_tax
        due_total = Decimal("0")

        tracking_number = get_unique_id(Sale, company.id, "tracking_number", "SR")
        invoice_id = tracking_number

        has_tax = any(line.get("tax") for line in lines)
        tax_kind = TaxKindChoices.EXCLUSIVE if has_tax else TaxKindChoices.NO_TAX

        email_json = {
            "customer_email": customer.email or "",
            "cc_emails": "",
            "bcc_emails": "",
        }

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        sale = Sale.objects.create(
            invoice_id=invoice_id,
            tracking_number=tracking_number,
            reference_number=receipt_number,
            date=receipt_date,
            invoice_date=receipt_date,
            due_date=receipt_date,
            is_invoice=False,
            is_estimated=False,
            is_sale_receipt=True,
            kind=SaleReceptKindChoices.SALE,
            customer=customer,
            company=company,
            warehouse=warehouse,
            created_by=employee,
            payment_method=None,
            receivable_charter_account=deposit_account,
            payable_charter_account=None,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=deposit_total,
            due_total=due_total,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
            tax_kind=tax_kind,
            description=memo,
            email=email_json,
            status=SalesStatusChoices.PAID,
        )

        if term:
            TermConnector.objects.create(
                kind=TermKindChoices.SALE,
                sale=sale,
                term=term,
            )

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

        AddressConnector.objects.create(
            address=Address.objects.create(
                full_address=full_billing_address,
                company=company,
            ),
            sale=sale,
            kind=AddressConnectorKindCoices.SALE,
        )

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

            if product:
                product_income_account = income_account or (
                    product.income_account if product else None
                )
                product_asset_account = product.asset_account if product else None

                remaining, deduction_details, _ = fifo_product_deduction(product, quantity)

                product_additional_cost = (
                    product.productadditionalcost_set.first() if product else None
                )
                cost_of_good_sold_account = (
                    product_additional_cost.expense_account
                    if product_additional_cost
                    else None
                )

                for layer_source, qty, price in deduction_details:
                    purchase_item = as_purchase_item(layer_source)
                    if qty <= 0:
                        continue

                    individual_cost = price * qty
                    individual_income = sale_price * qty

                    if cost_of_good_sold_account:
                        update_opening_balance(
                            cost_of_good_sold_account, "credit", individual_cost, 0
                        )

                    if product_income_account:
                        income_action = action_for_side(
                            product_income_account.kind,
                            JournalEntryConnectorKindChoices.CREDIT,
                        )
                        update_opening_balance(
                            product_income_account,
                            balance_operation_for_action(income_action),
                            individual_income,
                            0,
                        )

                    if product_asset_account:
                        asset_action = action_for_side(
                            product_asset_account.kind,
                            JournalEntryConnectorKindChoices.CREDIT,
                        )
                        update_opening_balance(
                            product_asset_account,
                            balance_operation_for_action(asset_action),
                            individual_cost,
                            0,
                        )

                    if product_income_account:
                        connector_data.append(
                            (
                                product_income_account,
                                income_action,
                                individual_income,
                                product_income_account.opening_balance,
                                None,
                                sale_item,
                                purchase_item,
                            )
                        )

                    if product_asset_account:
                        connector_data.append(
                            (
                                product_asset_account,
                                asset_action,
                                individual_cost,
                                product_asset_account.opening_balance,
                                None,
                                sale_item,
                                purchase_item,
                            )
                        )

                    if cost_of_good_sold_account:
                        cogs_action = action_for_side(
                            cost_of_good_sold_account.kind,
                            JournalEntryConnectorKindChoices.DEBIT,
                        )
                        connector_data.append(
                            (
                                cost_of_good_sold_account,
                                cogs_action,
                                individual_cost,
                                cost_of_good_sold_account.opening_balance,
                                None,
                                sale_item,
                                purchase_item,
                            )
                        )

            elif income_account:
                service_action = action_for_side(
                    income_account.kind, JournalEntryConnectorKindChoices.CREDIT
                )
                update_opening_balance(
                    income_account,
                    balance_operation_for_action(service_action),
                    line_total,
                    0,
                )
                connector_data.append(
                    (
                        income_account,
                        service_action,
                        line_total,
                        income_account.opening_balance,
                        None,
                        sale_item,
                        None,
                    )
                )

        SaleItem.objects.bulk_create(sale_items)

        if due_total != 0:
            update_opening_balance(customer, "credit", due_total, 0)

        if deposit_account and deposit_total != 0:
            # Money received always DEBITS the account it lands in.
            deposit_action = action_for_side(
                deposit_account.kind, JournalEntryConnectorKindChoices.DEBIT
            )
            update_opening_balance(
                deposit_account,
                balance_operation_for_action(deposit_action),
                deposit_total,
                0,
            )
            connector_data.append(
                (
                    deposit_account,
                    deposit_action,
                    deposit_total,
                    deposit_account.opening_balance,
                    None,
                )
            )

        for line in lines:
            tax = line.get("tax")
            line_total = Decimal(str(line.get("total") or "0"))
            is_tax = line.get("is_tax", False)
            if not is_tax or not tax:
                continue
            for tax_group in tax.tax_groups.all():
                payable_account = tax_group.sales_tax_account
                tax_amount = line_total * (
                    Decimal(str(tax_group.rate)) / Decimal("100")
                )
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
                    connector_data.append(
                        (
                            payable_account,
                            tax_action,
                            tax_amount,
                            payable_account.opening_balance,
                            None,
                        )
                    )

        undeposited_funds_map = get_chart_of_account(["Undeposited Funds"], company)
        undeposited_funds_account = undeposited_funds_map.get("Undeposited Funds")
        is_deposit = (
            deposit_account is not None
            and undeposited_funds_account is not None
            and deposit_account.uid == undeposited_funds_account.uid
        )

        journal_entry = JournalEntryService.create_journal_entry(
            amount=total,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.SALE_RECEPT,
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
                    title = "SALE RECEIPT"
                    label = "sales_receipts"
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
                            "invoice_date": receipt_date,
                            "date": sale.date,
                            "deposit_to": deposit_account,
                            "refund_from": None,
                            "kind": sale.kind,
                            "payment_method": None,
                            "location": warehouse.title if warehouse else "",
                            "invoice_due_date": receipt_date,
                            "term": term,
                            "description": memo,
                            "total_tax": float(total_tax),
                            "deposit": float(deposit_total),
                            "total": float(total),
                            "due_total": 0.00,
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
                        f"Balanzify {title}",
                    )
            except Exception:
                logger.exception("Failed to send migration email for sales receipt sale uid=%s", sale.uid)

        return sale


class SaleReceiptMigrationImporter:
    """Orchestrates sales receipt migration import."""

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))

        undeposited_map = get_chart_of_account(["Undeposited Funds"], company)
        default_deposit = undeposited_map.get("Undeposited Funds")

        receipt_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            customer_uid = nd.get("customer_uid", "")
            receipt_number = md.get("receipt_number", "")
            group_key = f"{customer_uid}::{receipt_number}"
            receipt_groups[group_key].append(row)

        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "sales_receipt_import_started"}
        )

        for group_key, group_rows in receipt_groups.items():
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    customer_uid_str = nd.get("customer_uid", "")
                    receipt_number = md.get("receipt_number", "")

                    customer = Customer.objects.filter(uid=customer_uid_str).first()
                    if not customer:
                        raise ValueError(f"Customer with uid '{customer_uid_str}' not found.")

                    is_duplicate = Sale.objects.filter(
                        company=company,
                        customer=customer,
                        is_sale_receipt=True,
                        kind=SaleReceptKindChoices.SALE,
                    ).filter(
                        Q(invoice_id=receipt_number)
                        | Q(tracking_number=receipt_number)
                        | Q(reference_number=receipt_number)
                    ).exists()

                    if is_duplicate:
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = (
                                f"Duplicate: Receipt '{receipt_number}' already exists."
                            )
                            row.save(
                                update_fields=["status", "message", "updated_at"]
                            )
                        continue

                    receipt_lines = []
                    receipt_date = None
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
                    warehouse = None
                    deposit_account = None

                    for row in group_rows:
                        rnd = row.normalized_data
                        rmd = row.mapped_data

                        if receipt_date is None and rnd.get("receipt_date"):
                            receipt_date = parse_date(rnd["receipt_date"], "YYYY-MM-DD")
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
                            shipping_date = parse_date(
                                rmd["shipping_date"], job.date_format
                            )
                        if not term and rnd.get("term_id"):
                            term = Term.objects.filter(id=rnd["term_id"]).first()
                        if not memo:
                            memo = rmd.get("memo", "")

                        if deposit_account is None and rnd.get("deposit_account_id"):
                            deposit_account = ChartOfAccount.objects.filter(
                                id=rnd["deposit_account_id"]
                            ).first()

                        if warehouse is None and rnd.get("warehouse_id"):
                            warehouse = Warehouse.objects.filter(
                                id=rnd["warehouse_id"]
                            ).first()

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
                            income_account = ChartOfAccount.objects.filter(
                                id=income_account_id
                            ).first()
                        elif product and product.income_account:
                            income_account = product.income_account

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

                        qty = rnd.get("quantity")
                        unit_price = rnd.get("unit_price")
                        quantity = int(Decimal(str(qty))) if qty else 1
                        sale_price = (
                            Decimal(str(unit_price)) if unit_price else line_amount
                        )

                        receipt_lines.append(
                            {
                                "product": product,
                                "income_account": income_account,
                                "quantity": quantity,
                                "sale_price": sale_price,
                                "total": line_amount,
                                "description": rmd.get("description", ""),
                                "tax": tax,
                                "is_tax": bool(tax),
                            }
                        )

                    if deposit_account is None:
                        deposit_account = default_deposit
                    if deposit_account is None:
                        raise ValueError(
                            "No deposit account mapped and Undeposited Funds account "
                            "not found for this company."
                        )

                    receipt_group_data = {
                        "customer": customer,
                        "receipt_number": receipt_number,
                        "receipt_date": receipt_date,
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
                        "deposit_account": deposit_account,
                        "warehouse": warehouse,
                        "lines": receipt_lines,
                    }

                    sale = MigrationSaleReceiptCreateService.create_receipt(
                        receipt_group_data,
                        user,
                        company,
                        options={"send_email": send_email, "source": "data_migration"},
                    )

                    for row in group_rows:
                        row.status = MigrationRowStatusChoices.IMPORTED
                        row.linked_record_uid = str(sale.uid)
                        row.linked_record_type = "sale"
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
                            "action": "sales_receipt_imported",
                            "receipt_number": receipt_number,
                            "sale_uid": str(sale.uid),
                        },
                    )

            except Exception as e:
                logger.exception(
                    "Sales receipt migration failed for group %s: %s", group_key, e
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
                        "action": "sales_receipt_import_failed",
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

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "import_completed", "imported": imported, "failed": failed},
        )
