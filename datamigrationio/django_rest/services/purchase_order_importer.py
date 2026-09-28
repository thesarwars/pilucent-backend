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

from purchaseio.models import Purchase, PurchaseItem
from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchaseTaxKindChoices,
)
from common.choices import DiscountKind
from common.django_rest.helpers.id_generator import get_unique_id
from currencyio.choices import CurrencyConnectorModelKind
from currencyio.models import Currency, CurrencyConnector
from addressio.models import Address, AddressConnector
from addressio.choices import AddressConnectorKindCoices, AddressStatusChoices

from supplierio.models import Supplier
from productio.models import Product
from accounts.models import ChartOfAccount
from agencyio.models import AgencyTax
from wirehouseio.models import Warehouse

from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

from datetime import date as date_type
from datamigrationio.django_rest.services.purchase_order_validator import parse_date

logger = logging.getLogger(__name__)


class MigrationPurchaseOrderCreateService:
    """
    Standalone purchase order creation for data migration.
    Creates Purchase records with is_bill=False, is_cheque=False.
    Supports PRODUCT and EXPENSE PurchaseItem lines — no GL impact.
    """

    @staticmethod
    def create_purchase_order(po_group, user, company, options=None):
        options = options or {}
        supplier = po_group["supplier"]
        purchase_order_number = po_group["purchase_order_number"]
        po_date = po_group["purchase_order_date"]
        expected_date = po_group.get("expected_date")
        currency_kind = po_group.get("currency_kind") or getattr(
            company, "currency", "USD"
        )
        currency_rate = po_group.get("currency_rate") or Decimal("1")
        memo = po_group.get("memo", "")
        total = po_group.get("total", Decimal("0"))
        total_tax = po_group.get("total_tax", Decimal("0"))
        warehouse = po_group.get("warehouse")
        lines = po_group.get("lines", [])

        tracking_number = get_unique_id(
            Purchase, company.id, "tracking_number", "PURCHASE"
        )
        purchase_id = get_unique_id(Purchase, company.id, "purchase_id", "PUR")

        has_tax = any(line.get("tax") for line in lines)
        tax_kind = (
            PurchaseTaxKindChoices.EXCLUSIVE if has_tax else PurchaseTaxKindChoices.NO_TAX
        )

        try:
            employee = user.get_employee() if hasattr(user, "get_employee") else None
        except Exception:
            employee = None

        purchase = Purchase.objects.create(
            purchase_id=purchase_id,
            tracking_number=tracking_number,
            date=po_date or date_type.today(),
            due_date=expected_date,
            bill_date=None,
            is_bill=False,
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
            due_total=total + total_tax,
            discount=Decimal("0"),
            discount_kind=DiscountKind.FLAT,
            shipping_fee=Decimal("0"),
            tax_kind=tax_kind,
            description=memo,
            status=PurchaseStatus.DRAFT,
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
                full_address=po_group.get("full_billing_address", ""),
                company=company,
                status=AddressStatusChoices.ACTIVE,
            ),
            purchase=purchase,
            kind=AddressConnectorKindCoices.PURCHASE,
        )

        purchase_items = []
        for line in lines:
            line_kind = line.get("line_kind", "PRODUCT")
            description = line.get("description", "")
            line_total = Decimal(str(line.get("total") or "0"))
            tax = line.get("tax")

            if line_kind == "EXPENSE":
                purchase_items.append(
                    PurchaseItem(
                        purchase=purchase,
                        status=PurchaseItemStatus.PUBLISHED,
                        kind=PurchaseItemkind.EXPENSE,
                        total=line_total,
                        description=description,
                        tax=tax,
                        charter_account=line.get("expense_account"),
                        section=line.get("section"),
                        note=line.get("note"),
                    )
                )
            else:
                quantity = int(line.get("quantity") or 1)
                purchase_price = Decimal(
                    str(line.get("purchase_price") or line.get("total") or "0")
                )
                purchase_items.append(
                    PurchaseItem(
                        purchase=purchase,
                        status=PurchaseItemStatus.PUBLISHED,
                        kind=PurchaseItemkind.PRODUCT,
                        total=line_total,
                        quantity=quantity,
                        opening_quantity=quantity,
                        purchase_price=purchase_price,
                        description=description,
                        tax=tax,
                        product=line.get("product"),
                        section=line.get("section"),
                        note=line.get("note"),
                    )
                )

        if purchase_items:
            PurchaseItem.objects.bulk_create(purchase_items)

        if options.get("send_email"):
            try:
                
                supplier_email = supplier.email or ""
                emails = [e for e in [supplier_email] if e]
                if emails:
                    title = "PURCHASE ORDER"
                    label = "purchase_orders"
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
                            "full_billing_address": po_group.get("full_billing_address", ""),
                            "supplier_email": supplier_email,
                            "purchase": purchase,
                            "purchase_items": product_purchase_items,
                            "custom_expense_items": custom_expense_items,
                            "has_deposit": False,
                            "deposit_amount": 0,
                            "has_due_total": (total + total_tax) > 0,
                            "due_total": total + total_tax,
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
                logger.exception("Failed to send migration email for purchase order uid=%s", purchase.uid)

        return purchase


class PurchaseOrderMigrationImporter:
    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        print(
            f"[PO IMPORTER] run() started | job_uid={job.uid} | importable rows={len(rows)}"
        )

        po_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            purchase_order_number = md.get("purchase_order_number", "")
            group_key = f"{supplier_uid}::{purchase_order_number}"
            po_groups[group_key].append(row)

        print(f"[PO IMPORTER] purchase order groups to process: {len(po_groups)}")
        imported = 0
        failed = 0

        MigrationAuditService.log(job, user, CrudAction.UPDATED, {"action": "import_started"})

        for group_key, group_rows in po_groups.items():
            print(f"[PO IMPORTER] Processing group: {group_key} ({len(group_rows)} rows)")
            try:
                with transaction.atomic():
                    first_row = group_rows[0]
                    nd = first_row.normalized_data
                    md = first_row.mapped_data

                    supplier_uid_str = nd.get("supplier_uid", "")
                    purchase_order_number = md.get("purchase_order_number", "")

                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if not supplier:
                        raise ValueError(
                            f"Supplier with uid '{supplier_uid_str}' not found."
                        )

                    is_duplicate = (
                        Purchase.objects.filter(
                            company=company,
                            supplier=supplier,
                            is_bill=False,
                            is_cheque=False,
                        )
                        .filter(
                            Q(purchase_id=purchase_order_number)
                            | Q(tracking_number=purchase_order_number)
                        )
                        .exists()
                    )

                    if is_duplicate:
                        for row in group_rows:
                            row.status = MigrationRowStatusChoices.SKIPPED
                            row.message = (
                                f"Duplicate: Purchase order '{purchase_order_number}' "
                                "already exists."
                            )
                            row.save(update_fields=["status", "message", "updated_at"])
                        continue

                    po_lines = []
                    po_date = None
                    expected_date = None
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

                        if po_date is None and rnd.get("purchase_order_date"):
                            po_date = parse_date(
                                rnd["purchase_order_date"], "YYYY-MM-DD"
                            )
                        if expected_date is None and rnd.get("expected_date"):
                            expected_date = parse_date(
                                rnd["expected_date"], "YYYY-MM-DD"
                            )
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

                        line_kind = rnd.get("line_kind", "PRODUCT")
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
                        purchase_price = (
                            Decimal(str(unit_price)) if unit_price else line_amount
                        )

                        line_data = {
                            "line_kind": line_kind,
                            "total": line_amount,
                            "description": rmd.get("description", ""),
                            "tax": tax,
                        }

                        if line_kind == "EXPENSE":
                            expense_account = None
                            expense_account_id = rnd.get("expense_account_id")
                            if expense_account_id:
                                expense_account = ChartOfAccount.objects.filter(
                                    id=expense_account_id
                                ).first()
                            line_data["expense_account"] = expense_account
                        else:
                            product = None
                            product_id = rnd.get("product_id")
                            if product_id:
                                product = Product.objects.filter(id=product_id).first()
                            line_data["product"] = product
                            line_data["quantity"] = quantity
                            line_data["purchase_price"] = purchase_price

                        po_lines.append(line_data)

                    po_group_data = {
                        "supplier": supplier,
                        "purchase_order_number": purchase_order_number,
                        "purchase_order_date": po_date,
                        "expected_date": expected_date,
                        "currency_kind": currency_kind or job.currency,
                        "currency_rate": currency_rate,
                        "full_billing_address": full_billing_address,
                        "memo": memo,
                        "total": total,
                        "total_tax": total_tax,
                        "warehouse": warehouse,
                        "lines": po_lines,
                    }

                    purchase = MigrationPurchaseOrderCreateService.create_purchase_order(
                        po_group_data,
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
                            "action": "purchase_order_imported",
                            "purchase_order_number": purchase_order_number,
                            "purchase_uid": str(purchase.uid),
                        },
                    )

            except Exception as e:
                print(f"[PO IMPORTER] FAILED group={group_key} error={e}")
                logger.exception(
                    "Purchase order migration importer failed for group %s: %s",
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
                        "action": "purchase_order_failed",
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
            f"[PO IMPORTER] DONE | imported={imported} failed={failed} "
            f"skipped={job.skipped_rows} job_status={job.status}"
        )
        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {"action": "import_completed", "imported": imported, "failed": failed},
        )
