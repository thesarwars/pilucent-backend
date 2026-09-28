import os
import logging

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from common.django_rest.helpers.emails import send_email_to_user


from accounts.django_rest.helpers.group_seeds import EMPLOYEE_GROUP_NAME
from accounts.models import User
from adminio.choices import CompanyRoleKindChoices, CompanyRoleStatusChoices
from adminio.models import CompanyRole
from companyio.models import CompanyDepartment, CompanyDesignation, CompanyUser
from employeeio.choices import EmployeeKindChoices, EmployeeStatusChoices
from employeeio.models import Employee

from datamigrationio.choices import (
    MigrationRowStatusChoices,
    MigrationStatusChoices,
)
from datamigrationio.django_rest.services.audit_service import MigrationAuditService
from common.django_rest.helpers.crud_logger import CrudAction

logger = logging.getLogger(__name__)


class EmployeeMigrationImporter:
    """
    Imports each row as a standalone Employee record.
    Mirrors PrivateWeEmployeeListSerializer.create() logic:
      1. Create User (login identity)
      2. Create/get CompanyUser
      3. Assign system 'employee' CompanyRole + Django group
      4. Create Employee
    """

    @staticmethod
    def run(job, user, company, options=None):
        options = options or {}
        send_email = options.get("send_email", False)

        importable_statuses = [MigrationRowStatusChoices.READY]
        if getattr(job, "allow_warning_import", False):
            importable_statuses.append(MigrationRowStatusChoices.WARNING)

        rows = list(job.rows.filter(status__in=importable_statuses))
        logger.info(
            "[EMPLOYEE IMPORTER] run() started | job_uid=%s | importable rows=%d",
            job.uid,
            len(rows),
        )

        imported = 0
        failed = 0

        MigrationAuditService.log(
            job, user, CrudAction.UPDATED, {"action": "employee_import_started"}
        )

        # Resolve the default system 'employee' CompanyRole once for the whole batch.
        default_employee_role = CompanyRole.objects.filter(
            company=company,
            name=EMPLOYEE_GROUP_NAME,
            is_system=True,
        ).first()

        employee_group, _ = Group.objects.get_or_create(name=EMPLOYEE_GROUP_NAME)

        for row in rows:
            nd = row.normalized_data or {}
            email = nd.get("email", "")
            first_name = nd.get("first_name", "")
            last_name = nd.get("last_name", "")

            logger.info(
                "[EMPLOYEE IMPORTER] Processing row uid=%s email='%s'",
                row.uid,
                email,
            )

            try:
                with transaction.atomic():
                    middle_name = nd.get("middle_name") or ""
                    composed_name = " ".join(
                        part for part in (first_name, middle_name, last_name) if part
                    )
                    gender = nd.get("gender") or None
                    date_of_birth_str = nd.get("date_of_birth") or None
                    ssn = nd.get("ssn") or ""
                    country = nd.get("country") or "us"
                    phone = nd.get("phone") or ""

                    # --- Create User (login identity) ---
                    new_user = User.objects.create(
                        email=email,
                        first_name=first_name,
                        middle_name=middle_name,
                        last_name=last_name,
                        name=composed_name,
                        phone=phone,
                        gender=gender,
                        ssn=ssn,
                        country=country,
                    )
                    if date_of_birth_str:
                        try:
                            from datetime import datetime as dt
                            new_user.date_of_birth = dt.strptime(
                                date_of_birth_str, "%Y-%m-%d"
                            ).date()
                            new_user.save(update_fields=["date_of_birth"])
                        except (ValueError, TypeError):
                            pass
                    new_user.set_password(email)
                    new_user.save(update_fields=["password"])

                    # --- Create/get CompanyUser ---
                    cu, _ = CompanyUser.objects.get_or_create(
                        user=new_user,
                        defaults={"company": company},
                    )

                    # --- Assign default system employee role ---
                    if default_employee_role:
                        cu.roles.add(default_employee_role)

                    # --- Add to Django 'employee' group ---
                    new_user.groups.add(employee_group)

                    # --- Resolve optional FKs from normalized_data ---
                    department = None
                    if nd.get("department_id"):
                        department = CompanyDepartment.objects.filter(
                            id=nd["department_id"]
                        ).first()

                    designation = None
                    if nd.get("designation_id"):
                        designation = CompanyDesignation.objects.filter(
                            id=nd["designation_id"]
                        ).first()

                    kind = nd.get("kind") or EmployeeKindChoices.FULL_TIME
                    status = nd.get("status") or EmployeeStatusChoices.DRAFT
                    employee_id = nd.get("employee_id") or None
                    code = nd.get("code") or None

                    joining_date_str = nd.get("joining_date") or None
                    confirmation_date = None
                    if joining_date_str:
                        try:
                            from datetime import datetime as dt
                            confirmation_date = dt.strptime(
                                joining_date_str, "%Y-%m-%d"
                            ).date()
                        except (ValueError, TypeError):
                            pass

                    today = timezone.now().date()

                    # --- Create Employee ---
                    employee = Employee.objects.create(
                        user=new_user,
                        name=composed_name,
                        first_name=first_name,
                        middle_name=middle_name or None,
                        last_name=last_name,
                        gender=gender,
                        ssn=ssn or None,
                        country=country,
                        phone_number=phone or None,
                        preferred_email=email,
                        employee_id=employee_id,
                        code=code,
                        department=department,
                        designation=designation,
                        kind=kind,
                        status=status,
                        confirmation_date=confirmation_date or today,
                        offer_date=today,
                        terminate_date=today,
                        last_date_of_work=today,
                    )

                    row.status = MigrationRowStatusChoices.IMPORTED
                    row.linked_record_uid = str(employee.uid)
                    row.linked_record_type = "employee"
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
                            "action": "employee_imported",
                            "email": email,
                            "employee_uid": str(employee.uid),
                        },
                    )

                    if send_email and email:
                        try:
                            
                            frontend_url = getattr(settings, "BASE_FRONTEND_URL", None) or os.environ.get("BASE_FRONTEND_URL", "http://localhost:3000")
                            onboarding_url = f"{frontend_url}/onboarding?email={email}"
                            send_email_to_user(
                                {
                                    "company": company,
                                    "employee": employee,
                                    "url": onboarding_url,
                                },
                                "emails/onboard/employee_email.html",
                                [email],
                                f"Welcome to {company.name}",
                            )
                        except Exception:
                            logger.exception(
                                "[EMPLOYEE IMPORTER] Failed to send welcome email for employee uid=%s",
                                employee.uid,
                            )

            except Exception as e:
                logger.exception(
                    "[EMPLOYEE IMPORTER] FAILED row=%s email='%s' error=%s",
                    row.uid,
                    email,
                    e,
                )
                failed += 1
                row.status = MigrationRowStatusChoices.FAILED
                row.message = str(e)
                row.save(update_fields=["status", "message", "updated_at"])
                MigrationAuditService.log(
                    job,
                    user,
                    CrudAction.UPDATED,
                    {
                        "action": "employee_import_failed",
                        "row_uid": str(row.uid),
                        "email": email,
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

        logger.info(
            "[EMPLOYEE IMPORTER] DONE | imported=%d failed=%d skipped=%d job_status=%s",
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
                "action": "employee_import_completed",
                "imported": imported,
                "failed": failed,
            },
        )
