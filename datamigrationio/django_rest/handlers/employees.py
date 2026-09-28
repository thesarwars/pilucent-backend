from django.conf import settings

from datamigrationio.django_rest.handlers.base import BaseMigrationHandler
from datamigrationio.django_rest.handlers.registry import MigrationHandlerRegistry


COLUMN_ALIAS_MAP = {
    # First name
    "first name": "first_name",
    "firstname": "first_name",
    "given name": "first_name",
    # Middle name
    "middle name": "middle_name",
    "middlename": "middle_name",
    # Last name
    "last name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "family name": "last_name",
    # Email
    "email": "email",
    "email address": "email",
    "work email": "email",
    "preferred email": "email",
    # Phone
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "contact number": "phone",
    # Employee ID
    "employee id": "employee_id",
    "employee no": "employee_id",
    "emp id": "employee_id",
    "staff id": "employee_id",
    "id": "employee_id",
    # Department
    "department": "department",
    "dept": "department",
    "team": "department",
    # Designation
    "designation": "designation",
    "job title": "designation",
    "position": "designation",
    "title": "designation",
    "role": "designation",
    # Joining / hire date
    "joining date": "joining_date",
    "join date": "joining_date",
    "hire date": "joining_date",
    "start date": "joining_date",
    "date of joining": "joining_date",
    "employment date": "joining_date",
    # Employment type
    "employment type": "employment_type",
    "emp type": "employment_type",
    "type": "employment_type",
    "contract type": "employment_type",
    # Status
    "status": "status",
    "employee status": "status",
    # Gender
    "gender": "gender",
    "sex": "gender",
    # Date of birth
    "date of birth": "date_of_birth",
    "dob": "date_of_birth",
    "birth date": "date_of_birth",
    "birthday": "date_of_birth",
    # SSN
    "ssn": "ssn",
    "social security number": "ssn",
    "social security": "ssn",
    # Country
    "country": "country",
    "country code": "country",
    # Employee code
    "code": "code",
    "employee code": "code",
}

REQUIRED_TARGET_FIELDS = {"first_name", "last_name", "email"}


@MigrationHandlerRegistry.register
class EmployeesMigrationHandler(BaseMigrationHandler):
    data_type = "employees"
    label = "Employees"
    category = "Payroll"
    description = "Import employee records."
    has_gl_impact = False
    is_posting_transaction = False
    import_available = True
    template_available = True

    TEMPLATE_HEADERS = [
        "First Name",
        "Last Name",
        "Email",
        "Phone",
        "Employee ID",
        "Department",
        "Designation",
        "Joining Date",
        "Employment Type",
        "Status",
        "Gender",
        "Date of Birth",
        "SSN",
        "Country",
        "Code",
    ]

    TEMPLATE_SAMPLE_ROW = [
        "Jane",
        "Doe",
        "jane.doe@example.com",
        "+1-555-000-0001",
        "EMP-001",
        "Engineering",
        "Software Engineer",
        "01/15/2024",
        "FULL_TIME",
        "ACTIVE",
        "FEMALE",
        "01/01/1990",
        "",
        "US",
        "",
    ]

    @classmethod
    def get_template_headers(cls) -> list:
        return cls.TEMPLATE_HEADERS

    @classmethod
    def get_template_sample_row(cls) -> list:
        return cls.TEMPLATE_SAMPLE_ROW

    @classmethod
    def get_field_aliases(cls) -> dict:
        return COLUMN_ALIAS_MAP

    @classmethod
    def get_target_fields(cls) -> list:
        return sorted(set(COLUMN_ALIAS_MAP.values()))

    @classmethod
    def get_required_target_fields(cls) -> set:
        return REQUIRED_TARGET_FIELDS

    @classmethod
    def get_accounting_target_fields(cls) -> set:
        return set()

    @classmethod
    def validate(cls, job, company) -> dict:
        from datamigrationio.django_rest.services.employee_validator import (
            EmployeeValidatorService,
        )
        return EmployeeValidatorService.validate_job(job, company)

    @classmethod
    def review_impact(cls, job, company) -> dict:
        from datamigrationio.django_rest.services.employee_impact import (
            EmployeeImpactService,
        )
        return EmployeeImpactService.generate(job, company)

    @classmethod
    def confirm_import(cls, job, user, options=None) -> dict:
        from datamigrationio.tasks import process_employee_migration

        send_email = (options or {}).get("send_email", False)
        use_celery = bool(getattr(settings, "CELERY_BROKER_URL", None)) and not settings.DEBUG

        if use_celery:
            process_employee_migration.delay(str(job.uid), user.id, send_email=send_email)
            message = "Import started. Check results endpoint for progress."
        else:
            process_employee_migration.apply(
                args=[str(job.uid), user.id],
                kwargs={"send_email": send_email},
            )
            message = "Import completed synchronously."

        return {
            "implemented": True,
            "job_uid": str(job.uid),
            "status": job.status,
            "message": message,
        }

    @classmethod
    def rollback(cls, job, user, reason="") -> dict:
        from datamigrationio.django_rest.services.employee_rollback import (
            EmployeeMigrationRollbackService,
        )
        return EmployeeMigrationRollbackService.run(job, user, reason=reason)
