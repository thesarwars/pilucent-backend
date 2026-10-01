import os
import logging
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

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
from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector
from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices
from termio.models import TermConnector
from termio.choicess import TermKindChoices

from customerio.models import Customer
from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from termio.models import Term
from django.db.models import Q
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from datetime import date as date_type
from datamigrationio.django_rest.services.estimate_validator import parse_date

logger = logging.getLogger(__name__)


class MigrationEstimateCreateService:
    """
    Standalone estimate creation service for data migration.
    Creates Sale records with is_estimated=True.
    No journal entries, no FIFO inventory, no opening_balance updates —
    estimates have no GL impact.
    """

    @staticmethod
    def create_estimate(estimate_group, user, company, options=None):
        """
        estimate_group dict keys:
            customer, estimate_number, estimate_date, expiry_date,
            currency_kind, currency_rate, full_billing_address,
            full_shipping_address, shipping_by, shipping_date, term,
            memo, total, total_tax, lines

        Each line in lines:
            product, income_account, quantity, sale_price, total,
            description, tax, is_tax

        Returns: Sale instance
        """

        options = options or {}
        customer = estimate_group["customer"]
        estimate_number = estimate_group["estimate_number"]
        estimate_date = estimate_group["estimate_date"]
        expiry_date = estimate_group.get("expiry_date")
        currency_kind = estimate_group.get("currency_kind") or company.currency if hasattr(company, "currency") else "USD"
        currency_rate = estimate_group.get("currency_rate") or Decimal("1")
        full_billing_address = estimate_group.get("full_billing_address", "")
        full_shipping_address = estimate_group.get("full_shipping_address", "")
        shipping_by = estimate_group.get("shipping_by")
        shipping_date = estimate_group.get("shipping_date")
        term = estimate_group.get("term")
        memo = estimate_group.get("memo", "")
        total = estimate_group.get("total", Decimal("0"))
        total_tax = estimate_group.get("total_tax", Decimal("0"))
        lines = estimate_group.get("lines", [])

        # Generate unique estimate tracking number
        tracking_number = get_unique_id(Sale, company.id, "tracking_number", "EST")
        invoice_id = tracking_number
        reference_number = estimate_number  # preserve imported estimate number as reference

        # Determine tax kind (informational only — no tax postings for estimates)
        has_tax = any(line.get("tax") for line in lines)
        tax_kind = estimate_group.get("tax_kind") or (
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

        # Create Sale as an estimate
        sale = Sale.objects.create(
            invoice_id=invoice_id,
            tracking_number=tracking_number,
            reference_number=reference_number,
            date=estimate_date,
            invoice_date=estimate_date,
            due_date=None,           # estimates use expired_date, not due_date
            expired_date=expiry_date,
            is_invoice=False,
            is_estimated=True,
            is_sale_receipt=False,
            kind=SaleReceptKindChoices.SALE,
            customer=customer,
            company=company,
            warehouse=estimate_group.get("warehouse"),
            created_by=employee,
            payment_method=None,
            receivable_charter_account=None,
            payable_charter_account=None,
            total=total,
            total_tax=total_tax,
            total_vat=Decimal("0"),
            deposit=Decimal("0"),
            due_total=total + total_tax,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
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

        # Create sale items (informational — no inventory or GL changes)
        sale_items = []
        for line in lines:
            product = line.get("product")
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

        SaleItem.objects.bulk_create(sale_items)

        # No GL operations for estimates:
        # - No fifo_product_deduction
        # - No update_opening_balance calls
        # - No JournalEntryService calls
        # - No connector_data postings

        if options.get("send_email"):
            try:
                
                customer_email = customer.email or ""
                emails = [e for e in [customer_email] if e]
                if emails:
                    title = "ESTIMATE"
                    label = "estimates"
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
                            "invoice_date": estimate_date,
                            "date": sale.date,
                            "deposit_to": None,
                            "refund_from": None,
                            "kind": sale.kind,
                            "payment_method": None,
                            "location": "",
                            "invoice_due_date": expiry_date,
                            "term": term,
                            "description": memo,
                            "total_tax": float(total_tax),
                            "deposit": 0.00,
                            "total": float(total),
                            "due_total": float(total + total_tax),
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
                logger.exception("Failed to send migration email for estimate sale uid=%s", sale.uid)

        return sale


class EstimateMigrationImporter:
    """
    Orchestrates the full import: groups rows by estimate, calls
    MigrationEstimateCreateService per estimate group, updates row/job statuses.
    """

    @staticmethod
    def run(job, user, company, options=None):

        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(f"[ESTIMATE IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}")

        # Group rows by customer_uid + estimate_number
        estimate_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            customer_uid = nd.get("customer_uid", "")
            estimate_number = md.get("estimate_number", "")
            group_key = f"{customer_uid}::{estimate_number}"
            estimate_groups[group_key].append(row)

        print(f"[ESTIMATE IMPORTER] estimate groups to process: {len(estimate_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(job, user, CrudAction.UPDATED, {"action": "import_started"})

        for group_key, group_rows in estimate_groups.items():
            print(f"[ESTIMATE IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    customer_uid_str = nd.get("customer_uid", "")
                    estimate_number = md.get("estimate_number", "")
                    print(f"[ESTIMATE IMPORTER] customer_uid={customer_uid_str} estimate_number={estimate_number}")

                    # Safety: re-check duplicate
                    customer = Customer.objects.filter(uid=customer_uid_str).first()
                    if not customer:
                        print(f"[ESTIMATE IMPORTER] ERROR: Customer not found for uid={customer_uid_str}")
                        raise ValueError(f"Customer with uid '{customer_uid_str}' not found.")

                    is_duplicate = Sale.objects.filter(
                        company=company,
                        customer=customer,
                        is_estimated=True,
                    ).filter(
                        Q(invoice_id=estimate_number)
                        | Q(tracking_number=estimate_number)
                        | Q(reference_number=estimate_number)
                    ).exists()

                    if is_duplicate:
                        print(f"[ESTIMATE IMPORTER] SKIPPED duplicate: estimate_number={estimate_number}")
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = f"Duplicate: Estimate '{estimate_number}' already exists."
                            row.save(update_fields=["status", "message", "updated_at"])
                        continue

                    # Build estimate lines from all rows in group
                    estimate_lines = []
                    estimate_date = None
                    expiry_date = None
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

                        # Estimate-level fields from first available row
                        if estimate_date is None and rnd.get("estimate_date"):
                            estimate_date = parse_date(rnd["estimate_date"], "YYYY-MM-DD")
                        if expiry_date is None and rnd.get("expiry_date"):
                            expiry_date = parse_date(rnd["expiry_date"], "YYYY-MM-DD")
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

                        estimate_lines.append({
                            "product": product,
                            "income_account": income_account,
                            "quantity": quantity,
                            "sale_price": sale_price,
                            "total": line_amount,
                            "description": rmd.get("description", ""),
                            "tax": tax,
                            "is_tax": bool(tax),
                        })

                    estimate_group_data = {
                        "customer": customer,
                        "estimate_number": estimate_number,
                        "estimate_date": estimate_date,
                        "expiry_date": expiry_date,
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
                        "lines": estimate_lines,
                    }

                    print(f"[ESTIMATE IMPORTER] Calling create_estimate for estimate_number={estimate_number} total={estimate_group_data['total']} lines={len(estimate_group_data['lines'])}")
                    sale = MigrationEstimateCreateService.create_estimate(
                        estimate_group_data,
                        user,
                        company,
                        options={"send_email": send_email, "source": "data_migration"},
                    )
                    print(f"[ESTIMATE IMPORTER] Estimate created: sale_uid={sale.uid} sale_status={sale.status}")

                    for row in group_rows:
                        row.status = MigrationRowStatusChoices.IMPORTED
                        row.linked_record_uid = str(sale.uid)
                        row.linked_record_type = "sale"
                        row.message = "Successfully imported."
                        row.save(update_fields=["status", "linked_record_uid", "linked_record_type", "message", "updated_at"])

                    imported += 1
                    MigrationAuditService.log(
                        job, user, CrudAction.CREATED,
                        {"action": "estimate_imported", "estimate_number": estimate_number, "sale_uid": str(sale.uid)},
                    )

            except Exception as e:
                print(f"[ESTIMATE IMPORTER] FAILED group={group_key} error={e}")
                logger.exception("Estimate migration importer failed for group %s: %s", group_key, e)
                failed += 1
                for row in group_rows:
                    row.status = MigrationRowStatusChoices.FAILED
                    row.message = str(e)
                    row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job, user, CrudAction.UPDATED,
                    {"action": "estimate_failed", "group_key": group_key, "error": str(e)},
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

        print(f"[ESTIMATE IMPORTER] DONE | imported={imported} failed={failed} skipped={job.skipped_rows} job_status={job.status}")
        MigrationAuditService.log(
            job, user, CrudAction.UPDATED,
            {"action": "import_completed", "imported": imported, "failed": failed},
        )
