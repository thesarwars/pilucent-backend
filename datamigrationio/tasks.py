import logging
from accounts.models import User
from datamigrationio.models import DataMigrationJob
from datamigrationio.choices import MigrationStatusChoices
from datamigrationio.django_rest.services.invoice_importer import (
    InvoiceMigrationImporter,
)
from datamigrationio.django_rest.services.estimate_importer import (
    EstimateMigrationImporter,
)
from datamigrationio.django_rest.services.sales_receipt_importer import (
    SaleReceiptMigrationImporter,
)
from datamigrationio.django_rest.services.purchase_order_importer import (
    PurchaseOrderMigrationImporter,
)
from datamigrationio.django_rest.services.bill_importer import BillMigrationImporter
from datamigrationio.django_rest.services.check_importer import CheckMigrationImporter
from datamigrationio.django_rest.services.expense_importer import (
    ExpenseMigrationImporter,
)
from datamigrationio.django_rest.services.location_importer import (
    LocationMigrationImporter,
)
from datamigrationio.django_rest.services.chart_of_account_importer import (
    ChartOfAccountMigrationImporter,
)
from datamigrationio.django_rest.services.employee_importer import (
    EmployeeMigrationImporter,
)

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_invoice_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process invoice data migration import.
    Runs InvoiceMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_invoice_migration STARTED | job_uid={job_uid} user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_invoice_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        print(
            f"[TASK] Job found: {job} | company={company} | current status={job.status}"
        )

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])
        print(f"[TASK] Job status set to IN_PROGRESS")

        InvoiceMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        print(
            f"[TASK] process_invoice_migration COMPLETED | job_uid={job_uid} | final status={job.status}"
        )
        logger.info(
            "[TASK] process_invoice_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        print(
            f"[TASK] process_invoice_migration FAILED | job_uid={job_uid} | error={e}"
        )
        logger.exception(
            "process_invoice_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_sales_receipt_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process sales receipt data migration import.
    """
    print(
        f"[TASK] process_sales_receipt_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_sales_receipt_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        SaleReceiptMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_sales_receipt_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_sales_receipt_migration task failed for job_uid=%s: %s",
            job_uid,
            e,
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_estimate_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process estimate data migration import.
    Runs EstimateMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_estimate_migration STARTED | job_uid={job_uid} user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_estimate_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        print(
            f"[TASK] Job found: {job} | company={company} | current status={job.status}"
        )

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])
        print(f"[TASK] Job status set to IN_PROGRESS")

        EstimateMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        print(
            f"[TASK] process_estimate_migration COMPLETED | job_uid={job_uid} | final status={job.status}"
        )
        logger.info(
            "[TASK] process_estimate_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        print(
            f"[TASK] process_estimate_migration FAILED | job_uid={job_uid} | error={e}"
        )
        logger.exception(
            "process_estimate_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_purchase_order_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process purchase order data migration import.
    Runs PurchaseOrderMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_purchase_order_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_purchase_order_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        PurchaseOrderMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_purchase_order_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_purchase_order_migration task failed for job_uid=%s: %s",
            job_uid,
            e,
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_bill_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process bill data migration import.
    Runs BillMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_bill_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_bill_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        BillMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_bill_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_bill_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_check_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process check data migration import.
    Runs CheckMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_check_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_check_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        CheckMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_check_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_check_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_expense_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process expense data migration import.
    Runs ExpenseMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_expense_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_expense_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        ExpenseMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_expense_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_expense_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_location_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process location (warehouse) data migration import.
    Runs LocationMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_location_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_location_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        LocationMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_location_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_location_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_chart_of_account_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process chart of accounts data migration import.
    Runs ChartOfAccountMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_chart_of_account_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_chart_of_account_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        ChartOfAccountMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_chart_of_account_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_chart_of_account_migration task failed for job_uid=%s: %s",
            job_uid,
            e,
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise


@shared_task(bind=True)
def process_employee_migration(self, job_uid, user_id, send_email=False):
    """
    Celery task to process employee data migration import.
    Runs EmployeeMigrationImporter.run() for the given job.
    """
    print(
        f"[TASK] process_employee_migration STARTED | job_uid={job_uid} "
        f"user_id={user_id} send_email={send_email}"
    )
    logger.info(
        "[TASK] process_employee_migration STARTED | job_uid=%s user_id=%s",
        job_uid,
        user_id,
    )

    try:
        job = DataMigrationJob.objects.get(uid=job_uid)
        user = User.objects.get(id=user_id)
        company = job.company

        job.status = MigrationStatusChoices.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        EmployeeMigrationImporter.run(
            job,
            user,
            company,
            options={"send_email": send_email, "skip_error_rows": True},
        )

        logger.info(
            "[TASK] process_employee_migration COMPLETED | job_uid=%s | final status=%s",
            job_uid,
            job.status,
        )

    except Exception as e:
        logger.exception(
            "process_employee_migration task failed for job_uid=%s: %s", job_uid, e
        )
        try:
            job = DataMigrationJob.objects.get(uid=job_uid)
            job.status = MigrationStatusChoices.FAILED
            job.save(update_fields=["status", "updated_at"])
        except Exception:
            pass
        raise
