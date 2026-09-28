import logging
from decimal import Decimal

from categoryio.models import Category

from accounts.choices import ChartOfAccountKindChoices

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
    MigrationStepChoices,
)
from datamigrationio.models import DataMigrationImpactLine

logger = logging.getLogger(__name__)

GL_KINDS = {
    ChartOfAccountKindChoices.ASSETS,
    ChartOfAccountKindChoices.LIABILITIES,
    ChartOfAccountKindChoices.EQUITIES,
}

AFFECTED_REPORTS = [
    "Balance Sheet",
    "Trial Balance",
    "General Ledger",
    "Equity Statement",
]

OBE_TITLE = "Opening Balance Equity"


def _get_kind_from_account_type(account_type_id) -> str:
    """Resolve the ChartOfAccountKind from a Category's parent title."""
    try:
        cat = Category.objects.select_related("parent").get(id=account_type_id)
        source = cat.parent if cat.parent else cat
        return source.title.upper()
    except Category.DoesNotExist:
        return ""


class ChartOfAccountImpactService:
    @staticmethod
    def generate(job, company) -> dict:
        DataMigrationImpactLine.objects.filter(job=job).delete()

        importable_statuses = [
            MigrationRowStatusChoices.READY,
            MigrationRowStatusChoices.WARNING,
        ]
        rows = list(job.rows.filter(status__in=importable_statuses))

        impact_lines_to_create = []
        total_value = Decimal("0")
        total_transactions = len(rows)

        for row in rows:
            nd = row.normalized_data or {}
            account_type_id = nd.get("account_type_id")
            opening_balance = Decimal(str(nd.get("opening_balance", "0") or "0"))
            title = nd.get("title", "")

            if not account_type_id or opening_balance == 0:
                continue

            kind = _get_kind_from_account_type(account_type_id)
            if kind not in GL_KINDS:
                continue

            total_value += opening_balance

            if kind == ChartOfAccountKindChoices.ASSETS:
                # Assets: Debit new account, Credit OBE
                impact_lines_to_create.append(
                    DataMigrationImpactLine(
                        job=job,
                        row=row,
                        transaction_type="chart_of_account",
                        account_title=title,
                        debit=opening_balance,
                        credit=Decimal("0"),
                        report_impact="Balance Sheet",
                    )
                )
                impact_lines_to_create.append(
                    DataMigrationImpactLine(
                        job=job,
                        row=row,
                        transaction_type="chart_of_account",
                        account_title=OBE_TITLE,
                        debit=Decimal("0"),
                        credit=opening_balance,
                        report_impact="Balance Sheet / Equity",
                    )
                )
            elif kind in (ChartOfAccountKindChoices.LIABILITIES, ChartOfAccountKindChoices.EQUITIES):
                # Liabilities & Equities: Debit OBE, Credit new account
                impact_lines_to_create.append(
                    DataMigrationImpactLine(
                        job=job,
                        row=row,
                        transaction_type="chart_of_account",
                        account_title=OBE_TITLE,
                        debit=opening_balance,
                        credit=Decimal("0"),
                        report_impact="Balance Sheet / Equity",
                    )
                )
                impact_lines_to_create.append(
                    DataMigrationImpactLine(
                        job=job,
                        row=row,
                        transaction_type="chart_of_account",
                        account_title=title,
                        debit=Decimal("0"),
                        credit=opening_balance,
                        report_impact="Balance Sheet",
                    )
                )

        if impact_lines_to_create:
            DataMigrationImpactLine.objects.bulk_create(impact_lines_to_create)

        # Determine impact level
        if total_value >= Decimal("10000"):
            impact_level = "High"
        elif total_value >= Decimal("1000"):
            impact_level = "Medium"
        elif total_value > 0:
            impact_level = "Low"
        else:
            impact_level = "None"

        job.status = MigrationStatusChoices.IMPACT_REVIEWED
        job.current_step = MigrationStepChoices.CONFIRM_IMPORT
        job.save(update_fields=["status", "current_step", "updated_at"])

        logger.info(
            "[COA IMPACT] job_uid=%s | importable=%d | gl_impact_lines=%d | total_value=%s",
            job.uid,
            total_transactions,
            len(impact_lines_to_create),
            total_value,
        )

        return {
            "job_uid": str(job.uid),
            "impact_level": impact_level,
            "total_transactions": total_transactions,
            "total_value": float(total_value),
            "affected_reports": AFFECTED_REPORTS,
            "lines": [
                {
                    "account_title": line.account_title,
                    "debit": float(line.debit),
                    "credit": float(line.credit),
                    "report_impact": line.report_impact,
                    "transaction_type": line.transaction_type,
                }
                for line in impact_lines_to_create
            ],
        }
