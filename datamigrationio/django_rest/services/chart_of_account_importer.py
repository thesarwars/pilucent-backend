import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from common.django_rest.helpers.chart_of_account_helpers import (
    resolve_import_account_kind,
)
from accounts.models import ChartOfAccount

from categoryio.models import Category

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account
from common.django_rest.helpers.crud_logger import CrudAction

from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService

logger = logging.getLogger(__name__)

GL_KINDS = {
    ChartOfAccountKindChoices.ASSETS,
    ChartOfAccountKindChoices.LIABILITIES,
    ChartOfAccountKindChoices.EQUITIES,
}


class ChartOfAccountMigrationImporter:
    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        logger.info(
            "[COA IMPORTER] run() started | job_uid=%s | importable rows=%d",
            job.uid,
            len(rows),
        )

        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "coa_import_started"}
        )

        employee = user.get_employee()

        for row in rows:
            nd = row.normalized_data or {}
            title = nd.get("title", "")

            logger.debug(
                "[COA IMPORTER] Processing row uid=%s title='%s'", row.uid, title
            )
            try:
                with transaction.atomic():
                    account_type = Category.objects.get(id=nd["account_type_id"])
                    detail_type = Category.objects.get(id=nd["detail_type_id"])

                    # The kind must be one of the five, or the account matches
                    # no bucket on any statement and the first posting against
                    # it raises. This used to take account_type.parent.title
                    # verbatim, so a QuickBooks detail type in the Account Type
                    # column produced kind="CREDIT CARDS" and an account that
                    # silently did not exist as far as the reports were
                    # concerned. Failing the row is the point: the importer
                    # catches per row and marks it FAILED, which is visible,
                    # whereas the account it used to create was not.
                    kind = resolve_import_account_kind(account_type)
                    if kind is None:
                        raise ValueError(
                            f"{account_type.title!r} is not a usable account "
                            "type -- it resolves to no account kind. Use a value "
                            "from the 'Type and Details Type' sheet."
                        )

                    opening_balance = Decimal(str(nd.get("opening_balance", "0") or "0"))
                    currency = nd.get("currency", "USD") or "USD"
                    description = nd.get("description") or ""
                    code = nd.get("code") or ""

                    coa = ChartOfAccount.objects.create(
                        title=title,
                        code=code,
                        kind=kind,
                        account_type=account_type,
                        detail_type=detail_type,
                        opening_balance=opening_balance,
                        currency=currency,
                        description=description,
                        status=ChartOfAccountStatusChoices.ACTIVE,
                        company=company,
                    )

                    journal_entry_uid = None

                    # Create opening balance journal entry (mirrors serializer logic)
                    if opening_balance != 0 and kind in GL_KINDS:
                        chart_of_accounts = get_chart_of_account(
                            ["Opening Balance Equity"], company
                        )
                        obe = chart_of_accounts.get("Opening Balance Equity")

                        if obe is None:
                            logger.warning(
                                "[COA IMPORTER] 'Opening Balance Equity' account not found "
                                "for company=%s — skipping journal entry for row=%s",
                                company.id,
                                row.uid,
                            )
                        else:
                            connector_data = []

                            if kind == ChartOfAccountKindChoices.ASSETS:
                                obe.opening_balance += opening_balance
                                connector_data = [
                                    (coa, "addition", opening_balance, opening_balance, None),
                                    (obe, "addition", opening_balance, obe.opening_balance, None),
                                ]
                            elif kind in (
                                ChartOfAccountKindChoices.LIABILITIES,
                                ChartOfAccountKindChoices.EQUITIES,
                            ):
                                obe.opening_balance -= opening_balance
                                connector_data = [
                                    (coa, "addition", opening_balance, opening_balance, None),
                                    (obe, "substraction", opening_balance, obe.opening_balance, None),
                                ]

                            obe.save_dirty_fields()

                            journal_entry = JournalEntry.objects.create(
                                amount=opening_balance,
                                status=JournalEntryStatusChoices.PUBLISHED,
                                kind=JournalEntryKindChoices.CHART_OF_ACCOUNT,
                                is_journal_entry=False,
                                is_transaction=True,
                                company=company,
                            )

                            JournalEntryService.create_journal_entry_connector(
                                connector_data=connector_data,
                                total=opening_balance,
                                request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                                journal_entry=journal_entry,
                                created_by=employee,
                            )

                            journal_entry_uid = str(journal_entry.uid)

                    # Persist uid for rollback
                    nd["journal_entry_uid"] = journal_entry_uid
                    row.normalized_data = nd
                    row.status = MigrationRowStatusChoices.IMPORTED
                    row.linked_record_uid = str(coa.uid)
                    row.linked_record_type = "chart_of_account"
                    row.message = "Successfully imported."
                    row.save(
                        update_fields=[
                            "normalized_data",
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
                            "action": "coa_imported",
                            "title": title,
                            "coa_uid": str(coa.uid),
                            "journal_entry_uid": journal_entry_uid,
                        },
                    )

            except Exception as exc:
                logger.exception(
                    "[COA IMPORTER] FAILED row=%s title='%s': %s", row.uid, title, exc
                )
                failed += 1
                row.status = MigrationRowStatusChoices.FAILED
                row.message = str(exc)
                row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "coa_import_failed",
                        "row_uid": str(row.uid),
                        "title": title,
                        "error": str(exc),
                    },
                )

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

        logger.info(
            "[COA IMPORTER] DONE | imported=%d failed=%d skipped=%d job_status=%s",
            imported,
            failed,
            job.skipped_rows,
            job.status,
        )

        MigrationAuditService.log(
            job,
            user,
            CrudAction.UPDATED,
            {
                "action": "coa_import_completed",
                "imported": imported,
                "failed": failed,
            },
        )
