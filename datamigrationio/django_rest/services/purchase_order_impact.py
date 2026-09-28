import logging
from collections import defaultdict
from decimal import Decimal

from datamigrationio.models import DataMigrationImpactLine
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)

from supplierio.models import Supplier

logger = logging.getLogger(__name__)

AFFECTED_REPORTS = []

INFORMATIONAL_REPORTS = [
    "Purchase Orders Report",
]


class PurchaseOrderImpactService:
    """
    Generates an informational impact preview for purchase orders.
    Purchase orders have NO GL impact — no journal entries, no balance updates.
    """

    @staticmethod
    def generate(job, company):
        DataMigrationImpactLine.objects.filter(job=job).delete()

        importable_statuses = [
            MigrationRowStatusChoices.READY,
            MigrationRowStatusChoices.WARNING,
        ]
        rows = job.rows.filter(status__in=importable_statuses)

        po_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            purchase_order_number = md.get("purchase_order_number", "")
            group_key = f"{supplier_uid}::{purchase_order_number}"
            po_groups[group_key].append(row)

        impact_lines_to_create = []
        total_value = Decimal("0")
        total_transactions = len(po_groups)

        for group_key, group_rows in po_groups.items():
            supplier_uid_str = group_key.split("::")[0]
            supplier = None
            supplier_name = ""
            if supplier_uid_str:
                try:
                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if supplier:
                        supplier_name = (
                            supplier.display_name or supplier.company_name or ""
                        )
                except Exception:
                    pass

            po_total = Decimal("0")
            for row in group_rows:
                nd = row.normalized_data
                line_amount = Decimal(nd.get("line_amount", "0") or "0")
                po_total += line_amount

            total_value += po_total

            impact_lines_to_create.append(
                DataMigrationImpactLine(
                    job=job,
                    row=None,
                    transaction_type="purchase_order_summary",
                    account=None,
                    account_title="No Accounting Impact",
                    debit=Decimal("0"),
                    credit=Decimal("0"),
                    customer=None,
                    customer_name=supplier_name,
                    report_impact="Purchase Orders Report",
                )
            )

        DataMigrationImpactLine.objects.bulk_create(impact_lines_to_create)

        job.status = MigrationStatusChoices.IMPACT_REVIEWED
        job.current_step = MigrationStepChoices.CONFIRM_IMPORT
        job.save(update_fields=["status", "current_step", "updated_at"])

        return {
            "job_uid": str(job.uid),
            "impact_level": "No Impact",
            "total_transactions": total_transactions,
            "total_value": str(total_value),
            "affected_reports": AFFECTED_REPORTS,
            "informational_note": (
                "Purchase orders have no accounting impact. No journal entries, "
                "no balance updates, and no inventory postings will be created."
            ),
            "lines": list(
                DataMigrationImpactLine.objects.filter(job=job).values(
                    "uid",
                    "transaction_type",
                    "account_title",
                    "debit",
                    "credit",
                    "customer_name",
                    "tax",
                    "location",
                    "report_impact",
                )
            ),
        }
