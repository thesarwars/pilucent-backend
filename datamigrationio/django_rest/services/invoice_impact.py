import logging
from collections import defaultdict
from decimal import Decimal

from datamigrationio.models import DataMigrationImpactLine
from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from customerio.models import Customer
from agencyio.models import AgencyTax

logger = logging.getLogger(__name__)

AFFECTED_REPORTS = [
    "Balance Sheet",
    "Profit & Loss",
    "Accounts Receivable Aging",
    "General Ledger",
    "Trial Balance",
    "Sales Tax Report",
]


class InvoiceImpactService:
    """
    Generates accounting impact preview ONLY.
    Does NOT create Sale, SaleItem, JournalEntry, or update any opening balances.
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

        # Get receivable account
        chart_map = get_chart_of_account(["Accounts Receivable (A/R)"], company)
        receivable_account = chart_map.get("Accounts Receivable (A/R)")

        # Group rows by (customer_uid + invoice_number)
        invoice_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            customer_uid = nd.get("customer_uid", "")
            invoice_number = md.get("invoice_number", "")
            group_key = f"{customer_uid}::{invoice_number}"
            invoice_groups[group_key].append(row)

        impact_lines_to_create = []
        total_value = Decimal("0")
        total_transactions = len(invoice_groups)

        for group_key, group_rows in invoice_groups.items():
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

            subtotal = Decimal("0")
            tax_total = Decimal("0")

            for row in group_rows:
                nd = row.normalized_data
                md = row.mapped_data

                line_amount = Decimal(nd.get("line_amount", "0") or "0")
                subtotal += line_amount

                # Per-line income account credit
                income_account = None
                income_account_title = ""
                income_account_id = nd.get("income_account_id")
                if income_account_id:
                    from accounts.models import ChartOfAccount

                    try:
                        income_account = ChartOfAccount.objects.filter(
                            id=income_account_id
                        ).first()
                        if income_account:
                            income_account_title = income_account.title or ""
                    except Exception:
                        pass

                impact_lines_to_create.append(
                    DataMigrationImpactLine(
                        job=job,
                        row=row,
                        transaction_type="income",
                        account=income_account,
                        account_title=income_account_title or "Income Account",
                        debit=Decimal("0"),
                        credit=line_amount,
                        customer=customer,
                        customer_name=customer_name,
                        report_impact="Profit & Loss",
                    )
                )

                # Per-line tax credit
                tax_uid_str = nd.get("tax_uid")
                if tax_uid_str:
                    try:
                        tax = AgencyTax.objects.filter(uid=tax_uid_str).first()
                        if tax:
                            for tax_group in tax.tax_groups.all():
                                tax_amount = (
                                    line_amount
                                    * Decimal(str(tax_group.rate))
                                    / Decimal("100")
                                )
                                tax_total += tax_amount
                                payable_account = tax_group.sales_tax_account
                                impact_lines_to_create.append(
                                    DataMigrationImpactLine(
                                        job=job,
                                        row=row,
                                        transaction_type="tax_payable",
                                        account=payable_account,
                                        account_title=(
                                            payable_account.title
                                            if payable_account
                                            else "Sales Tax Payable"
                                        ),
                                        debit=Decimal("0"),
                                        credit=tax_amount,
                                        customer=customer,
                                        customer_name=customer_name,
                                        tax=tax.title,
                                        report_impact="Sales Tax Report",
                                    )
                                )
                    except Exception as e:
                        logger.warning(
                            "Could not process tax for row %s: %s", row.row_number, e
                        )

            invoice_total = subtotal + tax_total
            total_value += invoice_total

            # Accounts receivable debit (one per invoice group)
            impact_lines_to_create.append(
                DataMigrationImpactLine(
                    job=job,
                    row=None,
                    transaction_type="accounts_receivable",
                    account=receivable_account,
                    account_title=(
                        receivable_account.title
                        if receivable_account
                        else "Accounts Receivable (A/R)"
                    ),
                    debit=invoice_total,
                    credit=Decimal("0"),
                    customer=customer,
                    customer_name=customer_name,
                    report_impact="Balance Sheet",
                )
            )

        DataMigrationImpactLine.objects.bulk_create(impact_lines_to_create)

        # Determine impact level
        if total_value >= Decimal("10000"):
            impact_level = "High Impact"
        elif total_value >= Decimal("1000"):
            impact_level = "Medium Impact"
        else:
            impact_level = "Low Impact"

        job.status = MigrationStatusChoices.IMPACT_REVIEWED
        job.current_step = MigrationStepChoices.CONFIRM_IMPORT
        job.save(update_fields=["status", "current_step", "updated_at"])

        return {
            "job_uid": str(job.uid),
            "impact_level": impact_level,
            "total_transactions": total_transactions,
            "total_value": str(total_value),
            "affected_reports": AFFECTED_REPORTS,
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
