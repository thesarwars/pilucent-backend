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
from supplierio.models import Supplier
from agencyio.models import AgencyTax
from accounts.models import ChartOfAccount

logger = logging.getLogger(__name__)

AFFECTED_REPORTS = [
    "Balance Sheet",
    "General Ledger",
    "Trial Balance",
    "Sales Tax Report",
]


class ExpenseImpactService:
    """
    Preview accounting impact for expenses migration (no DB writes except impact lines).

    Per expense group:
      - Per expense line: debit expense account (cost incurred)
      - Per product line: debit inventory asset account
      - Per tax on line: debit sales tax payable
      - Per expense total: credit payment account (money out)
    """

    @staticmethod
    def generate(job, company):
        DataMigrationImpactLine.objects.filter(job=job).delete()

        importable_statuses = [
            MigrationRowStatusChoices.READY,
            MigrationRowStatusChoices.WARNING,
        ]
        rows = job.rows.filter(status__in=importable_statuses)

        account_map = get_chart_of_account(["Inventory Asset", "Sales Tax Payable"], company)
        inventory_account = account_map.get("Inventory Asset")
        tax_account_default = account_map.get("Sales Tax Payable")

        expense_groups = defaultdict(list)
        for row in rows:
            nd = row.normalized_data
            md = row.mapped_data
            supplier_uid = nd.get("supplier_uid", "")
            reference_number = md.get("reference_number", "") or nd.get("expense_date", "")
            group_key = f"{supplier_uid}::{reference_number}"
            expense_groups[group_key].append(row)

        impact_lines_to_create = []
        total_value = Decimal("0")
        total_transactions = len(expense_groups)

        for group_key, group_rows in expense_groups.items():
            supplier_uid_str = group_key.split("::")[0]
            supplier_name = ""
            if supplier_uid_str:
                try:
                    supplier = Supplier.objects.filter(
                        uid=supplier_uid_str, company=company
                    ).first()
                    if supplier:
                        supplier_name = supplier.display_name or supplier.company_name or ""
                except Exception:
                    pass

            expense_subtotal = Decimal("0")
            expense_tax_total = Decimal("0")

            payment_account = None
            payment_account_title = "Payment Account"

            for row in group_rows:
                nd = row.normalized_data
                md = row.mapped_data

                if payment_account is None and nd.get("payment_account_id"):
                    try:
                        payment_account = ChartOfAccount.objects.filter(
                            id=nd["payment_account_id"]
                        ).first()
                        if payment_account:
                            payment_account_title = payment_account.title or ""
                    except Exception:
                        pass

                line_amount = Decimal(nd.get("line_amount", "0") or "0")
                expense_subtotal += line_amount

                line_kind = nd.get("line_kind", "EXPENSE")

                if line_kind == "PRODUCT":
                    impact_lines_to_create.append(
                        DataMigrationImpactLine(
                            job=job,
                            row=row,
                            transaction_type="inventory_asset",
                            account=inventory_account,
                            account_title=(
                                inventory_account.title
                                if inventory_account
                                else "Inventory Asset"
                            ),
                            debit=line_amount,
                            credit=Decimal("0"),
                            customer=None,
                            customer_name=supplier_name,
                            report_impact="Balance Sheet",
                        )
                    )
                else:
                    expense_account = None
                    expense_account_title = ""
                    expense_account_id = nd.get("expense_account_id")
                    if expense_account_id:
                        try:
                            expense_account = ChartOfAccount.objects.filter(
                                id=expense_account_id
                            ).first()
                            if expense_account:
                                expense_account_title = expense_account.title or ""
                        except Exception:
                            pass

                    impact_lines_to_create.append(
                        DataMigrationImpactLine(
                            job=job,
                            row=row,
                            transaction_type="expense",
                            account=expense_account,
                            account_title=expense_account_title or "Expense Account",
                            debit=line_amount,
                            credit=Decimal("0"),
                            customer=None,
                            customer_name=supplier_name,
                            report_impact="General Ledger",
                        )
                    )

                # Process tax lines
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
                                expense_tax_total += tax_amount
                                payable_tax_account = tax_group.sales_tax_account or tax_account_default
                                impact_lines_to_create.append(
                                    DataMigrationImpactLine(
                                        job=job,
                                        row=row,
                                        transaction_type="tax_payable",
                                        account=payable_tax_account,
                                        account_title=(
                                            payable_tax_account.title
                                            if payable_tax_account
                                            else "Sales Tax Payable"
                                        ),
                                        debit=tax_amount,
                                        credit=Decimal("0"),
                                        customer=None,
                                        customer_name=supplier_name,
                                        tax=tax.title,
                                        report_impact="Sales Tax Report",
                                    )
                                )
                    except Exception as e:
                        logger.warning(
                            "Could not process tax for row %s: %s", row.row_number, e
                        )

            expense_total = expense_subtotal + expense_tax_total
            total_value += expense_total

            # Credit payment account for the full expense total (money out)
            impact_lines_to_create.append(
                DataMigrationImpactLine(
                    job=job,
                    row=None,
                    transaction_type="bank_payment",
                    account=payment_account,
                    account_title=payment_account_title,
                    debit=Decimal("0"),
                    credit=expense_total,
                    customer=None,
                    customer_name=supplier_name,
                    report_impact="Balance Sheet",
                )
            )

        DataMigrationImpactLine.objects.bulk_create(impact_lines_to_create)

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
