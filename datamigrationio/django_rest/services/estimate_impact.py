import logging
from collections import defaultdict
from decimal import Decimal

from datamigrationio.models import DataMigrationImpactLine
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)

from customerio.models import Customer

logger = logging.getLogger(__name__)

# Estimates have no GL impact — these reports are not affected
AFFECTED_REPORTS = []

INFORMATIONAL_REPORTS = [
    "Sales Estimates Report",
]


class EstimateImpactService:
    """
    Generates an informational impact preview for estimates.
    Estimates have NO GL impact — no journal entries, no balance updates,
    no FIFO inventory changes. This service creates summary lines only
    so the frontend has something to display during the review step.
    """

    @staticmethod
    def generate(job, company):

        # Delete old impact lines for this job before regenerating
        DataMigrationImpactLine.objects.filter(job=job).delete()

        importable_statuses = [
            MigrationRowStatusChoices.READY,
            MigrationRowStatusChoices.WARNING,
        ]
        rows = job.rows.filter(status__in=importable_statuses)

        # Group rows by (customer_uid + estimate_number)
        estimate_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            customer_uid = nd.get("customer_uid", "")
            estimate_number = md.get("estimate_number", "")
            group_key = f"{customer_uid}::{estimate_number}"
            estimate_groups[group_key].append(row)

        impact_lines_to_create = []
        total_value = Decimal("0")
        total_transactions = len(estimate_groups)

        for group_key, group_rows in estimate_groups.items():
            customer_uid_str = group_key.split("::")[0]
            customer = None
            customer_name = ""
            if customer_uid_str:
                try:
                    customer = Customer.objects.filter(uid=customer_uid_str).first()
                    if customer:
                        customer_name = (
                            customer.display_name or customer.company_name or ""
                        )
                except Exception:
                    pass

            estimate_total = Decimal("0")
            for row in group_rows:
                nd = row.normalized_data
                line_amount = Decimal(nd.get("line_amount", "0") or "0")
                estimate_total += line_amount

            total_value += estimate_total

            # One informational summary line per estimate group (no debit/credit)
            impact_lines_to_create.append(
                DataMigrationImpactLine(
                    job=job,
                    row=None,
                    transaction_type="estimate_summary",
                    account=None,
                    account_title="No Accounting Impact",
                    debit=Decimal("0"),
                    credit=Decimal("0"),
                    customer=customer,
                    customer_name=customer_name,
                    report_impact="Sales Estimates Report",
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
                "Estimates have no accounting impact. No journal entries, "
                "no balance updates, and no tax postings will be created."
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
