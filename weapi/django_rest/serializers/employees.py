import os
import logging

from django.conf import settings
from django.contrib.auth.models import Group
from django.utils import timezone
from django.db import transaction

from django.db.models import Q

from rest_framework.serializers import (
    CharField,
    ChoiceField,
    DateField,
    DecimalField,
    EmailField,
    ModelSerializer,
    SlugRelatedField,
    ValidationError,
    BooleanField,
    SerializerMethodField,
)
from rest_framework.generics import get_object_or_404

from accounts.choices import UserGenderChoices
from accounts.django_rest.helpers.group_seeds import EMPLOYEE_GROUP_NAME
from accounts.django_rest.helpers.invitation_token import generate_invitation_token
from accounts.django_rest.serializers.common import PriateUserSlimSerializer
from accounts.models import User

from adminio.choices import CompanyRoleKindChoices, CompanyRoleStatusChoices
from adminio.django_rest.serializers.common import PrivateCompanyRoleSlimSerializer
from adminio.models import CompanyRole

from addressio.django_rest.serializers.common import PrivateAddressSerializer

from attendanceio.django_rest.serializers.common import PrivateHolidaySlimSerializer
from attendanceio.models import Holiday

from companyio.choices import (
    CompanyDepartmentStatusChoices,
    CompanyDesignationStatusChoices,
    CompanyShiftStatusChoices,
)
from companyio.models import (
    CompanyDepartment,
    CompanyDesignation,
    CompanyShift,
    CompanyUser,
)
from companyio.django_rest.serializers.common import (
    PrivateCompanyDepartmentSlimSerializer,
    PrivateCompanyDesignationSlimSerializer,
    PrivateCompanyShiftSlimSerializer,
)

from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.emails import send_email_to_user
from common.django_rest.helpers.countries import COUNTRIES
from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from employeeio.choices import (
    EmployeeStatusChoices,
    EmployeeEducationStatusChoices,
    EmployeeBankingInformationStatusChoices,
    EmployeeEarningStatusChoices,
    EmployeeDeductionContributionStatusChoices,
    EmployeeGarnishmentStatusChoices,
    EmployeeWorkExperienceStatusChoices,
    EmployeeOnboardingKindChoices,
)
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
    PrivateEmployeeBankingInformationSlimSerializer,
)
from employeeio.models import (
    Employee,
    EmployeeEducation,
    EmployeeBankingInformation,
    EmployeeTax,
    EmployeeEarning,
    EmployeeDeductionContribution,
    EmployeeGarnishment,
    EmployeeWorkExperience,
)

from fileroomio.models import FileItem, FileItemConnector
from fileroomio.choices import FileItemStatusChoices, FileItemConnectorModelKindChoices
from fileroomio.django_rest.helpers.file_helpers import get_file_kind

from payrollio.models import (
    PaySchedule,
    DeductionAndContributions,
    PayrollFederalTaxInfoSetting,
    PayrollWorkLocation,
)
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    sync_other_liability_component_for_deduction,
)
from payrollio.django_rest.serializer.common import (
    PayrollSalaryProcessSlimSerializerForEmployee,
    PrivateWePayrollWorkLocationSlimSerializer,
)
from payrollio.choicess import PayrollWorkLocationChoices


from ..serializers.payroll.deduction_and_contribution import (
    DeductionAndContributionSlimSerializer,
)

from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)


class PrivateEmployeeUserSerializer(ModelSerializer):

    class Meta:
        model = User
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "name",
            "email",
            "salutation",
            "gender",
            "nid_card_no",
            "ssn",
            "image",
            "country",
            "date_of_birth",
            "is_email_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateWeEmployeeListAllSerializer(ModelSerializer):
    user = PrivateEmployeeUserSerializer(read_only=True)

    class Meta:
        model = Employee
        fields = [
            "uid",
            "employee_id",
            "user",
        ]
        read_only_fields = fields


class PrivateEmployeePayScheduleSerializer(ModelSerializer):
    class Meta:
        model = PaySchedule
        fields = [
            "uid",
            "title",
            "pay_frequency",
            "status",
            "is_default",
            "first_payday",
            "first_end_day",
            "first_month",
            "first_day",
            "second_payday",
            "second_end_day",
            "second_month",
            "second_day",
            "next_pay_date",
            "end_of_next_pay_period",
            "created_at",
        ]


class PrivateWeEmployeeTaxListSerializer(ModelSerializer):

    class Meta:
        model = EmployeeTax
        fields = [
            "uid",
            "is_the_state_other_income_tax",
            "state",
            "martial_status",
            "total_allowance",
            "additional_with_holdings",
            "total",
            "exempt",
            "is_the_employee_exempt_from_any_state_taxes",
            "is_the_employee_work_in_the_state_where_live",
            "is_federal_with_holding",
            "employee_W_4_kind",
            "is_multiple_jobs_or_spouse_works",
            "total_other_income",
            "extra_with_holding",
            "holding_status",
            "deduction",
            "exempt_from_with_holding",
            "exempt_from_with_holding",
            "is_employee_exempt_from_federal_tax",
            "claim_depends",
            "exempt_fields",
            "children_under_17",
            "other_dependents",
            "other_tax_credits",
            "children_amount",
            "dependent_amount",
            "total_credits",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        return super().create(validated_data)


class PrivateWeEmployeeTaxDetailsSerializer(ModelSerializer):

    class Meta:
        model = EmployeeTax
        fields = [
            "uid",
            "is_the_state_other_income_tax",
            "state",
            "martial_status",
            "total_allowance",
            "additional_with_holdings",
            "total",
            "exempt",
            "is_the_employee_exempt_from_any_state_taxes",
            "is_the_employee_work_in_the_state_where_live",
            "is_federal_with_holding",
            "employee_W_4_kind",
            "is_multiple_jobs_or_spouse_works",
            "total_other_income",
            "extra_with_holding",
            "holding_status",
            "deduction",
            "exempt_from_with_holding",
            "exempt_from_with_holding",
            "is_employee_exempt_from_federal_tax",
            "is_employee_exempt_from_family_paid_leave",
            "claim_depends",
            "exempt_fields",
            "children_under_17",
            "other_dependents",
            "other_tax_credits",
            "children_amount",
            "dependent_amount",
            "total_credits",
            "created_at",
            "updated_at",
        ]


class EmployeeBankingInformationSlimSerializer(ModelSerializer):
    class Meta:
        model = EmployeeBankingInformation
        fields = ["uid", "kind", "created_at"]


class PrivateWeEmployeeDeductionContributionListSerializer(ModelSerializer):
    deduction_and_contribution = DeductionAndContributionSlimSerializer(read_only=True)
    deduction_and_contribution_uid = SlugRelatedField(
        slug_field="uid",
        queryset=DeductionAndContributions.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = EmployeeDeductionContribution
        fields = [
            "uid",
            "status",
            "tax_option",
            # Employee deduction
            "employee_deduction_kind",
            "total_employee_deduction_per_pay_check",
            "total_maximum_annual_employee_deduction",
            # Company contribution
            "company_contribution_kind",
            "total_company_contribution_per_pay_check",
            "total_maximum_annual_company_contribution",
            "deduction_and_contribution",
            "deduction_and_contribution_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["status"] = EmployeeDeductionContributionStatusChoices.ACTIVE
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        validated_data["deduction_and_contribution"] = validated_data.pop(
            "deduction_and_contribution_uid", None
        )
        instance = super().create(validated_data)
        if instance.deduction_and_contribution_id:
            sync_other_liability_component_for_deduction(
                company=instance.employee.get_company(),
                deduction=instance.deduction_and_contribution,
                employee=instance.employee,
            )
        return instance


class PrivateWeEmployeeDeductionContributionDetailsSerializer(ModelSerializer):
    deduction_and_contribution = DeductionAndContributionSlimSerializer(read_only=True)
    deduction_and_contribution_uid = SlugRelatedField(
        slug_field="uid",
        queryset=DeductionAndContributions.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = EmployeeDeductionContribution
        fields = [
            "uid",
            "status",
            "tax_option",
            # Employee deduction
            "employee_deduction_kind",
            "total_employee_deduction_per_pay_check",
            "total_maximum_annual_employee_deduction",
            # Company contribution
            "company_contribution_kind",
            "total_company_contribution_per_pay_check",
            "total_maximum_annual_company_contribution",
            "deduction_and_contribution",
            "deduction_and_contribution_uid",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        if "deduction_and_contribution_uid" in validated_data:
            validated_data["deduction_and_contribution"] = validated_data.pop(
                "deduction_and_contribution_uid", None
            )
        instance = super().update(instance, validated_data)
        if instance.deduction_and_contribution_id:
            sync_other_liability_component_for_deduction(
                company=instance.employee.get_company(),
                deduction=instance.deduction_and_contribution,
                employee=instance.employee,
            )
        return instance


class PrivateWeEmployeeListSerializer(ModelSerializer):
    user = PrivateEmployeeUserSerializer(read_only=True)
    confirmation_date = DateField(write_only=True, required=False, allow_null=True)
    company_email = EmailField(required=False, allow_null=True)
    personal_email = EmailField(required=False, allow_null=True)
    # Profile fields. Required at creation; once persisted they live on
    # Employee independently of the linked User (see create() below).
    first_name = CharField(max_length=100)
    middle_name = CharField(max_length=100, required=False, allow_blank=True)
    last_name = CharField(max_length=100)
    gender = ChoiceField(
        choices=UserGenderChoices.choices, required=False, allow_blank=True
    )
    salutation = CharField(required=False, max_length=100, allow_blank=True)
    date_of_birth = DateField(required=False)
    ssn = CharField(required=False, max_length=100, allow_blank=True)
    country = ChoiceField(choices=COUNTRIES, required=False, allow_blank=True)

    # Department
    department = PrivateCompanyDepartmentSlimSerializer(read_only=True)
    department_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyDepartment.objects.filter(
            status=CompanyDepartmentStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    # Desgnation
    designation = PrivateCompanyDesignationSlimSerializer(read_only=True)
    designation_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyDesignation.objects.filter(
            status=CompanyDesignationStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    shift_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyShift.objects.filter(status=CompanyShiftStatusChoices.ACTIVE),
        write_only=True,
        required=False,
    )

    # Company role information
    # Both fields accept EMPLOYEE-kind roles only. `company_role_uid` (singular)
    # is kept for backward compatibility; new clients should send `company_role_uids`.
    # company_role_uid = SlugRelatedField(
    #     slug_field="uid",
    #     queryset=CompanyRole.objects.filter(
    #         kind=CompanyRoleKindChoices.EMPLOYEE,
    #         status=CompanyRoleStatusChoices.ACTIVE,
    #     ),
    #     write_only=True,
    #     required=False,
    #     help_text="(deprecated) Single EMPLOYEE-kind role to assign. Prefer company_role_uids.",
    # )
    company_role_uids = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyRole.objects.filter(
            kind=CompanyRoleKindChoices.EMPLOYEE,
            status=CompanyRoleStatusChoices.ACTIVE,
        ),
        write_only=True,
        required=False,
        many=True,
        help_text=(
            "Zero or more EMPLOYEE-kind roles to assign in addition to the default "
            "system 'employee' role (which is always attached)."
        ),
    )
    report_to = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    report_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all().exclude(status=EmployeeStatusChoices.REMOVED),
        write_only=True,
        required=False,
    )

    # Pay shedule information
    pay_schedule_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaySchedule.objects.all().exclude(
            status=EmployeeStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )

    # Holyday information
    holiday_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Holiday.objects.all(),
        write_only=True,
        required=False,
    )
    # Get total worked hour
    worked_hour_count = SerializerMethodField(read_only=True)

    # Work location information
    work_locations = PrivateWePayrollWorkLocationSlimSerializer(read_only=True)
    work_locations_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PayrollWorkLocation.objects.all().exclude(
            status=PayrollWorkLocationChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )
    # bank information
    banaking_informations = PrivateEmployeeBankingInformationSlimSerializer(
        source="get_banking_informations.first", read_only=True
    )

    addresses = PrivateAddressSerializer(
        many=True, read_only=True, source="get_addresses"
    )
    contribution_and_deductions = PrivateWeEmployeeDeductionContributionListSerializer(
        source="get_deduction_and_contibution", many=True, read_only=True
    )

    class Meta:
        model = Employee
        fields = [
            "uid",
            # User (login identity) — nested, read-only
            "user",
            # Employee profile (independent from User; see create() docstring)
            "first_name",
            "middle_name",
            "last_name",
            "name",
            "gender",
            "image",
            "salutation",
            "date_of_birth",
            "blood_group",
            "nid_card_no",
            "ssn",
            "country",
            "description",
            # Employee information
            "code",
            "employee_id",
            "kind",
            "status",
            "company_phone_number",
            "company_email",
            "is_joined",
            "is_access_enabled",
            "on_boarding_kind",
            # Hiring information
            "confirmation_date",
            "notice_period",
            "offer_date",
            "contract_end_date",
            # Terminate information
            "terminate_date",
            "last_date_of_work",
            "terminate_kind",
            "terminate_description",
            # Company information
            "designation",
            "designation_uid",
            "department",
            "department_uid",
            "shift",
            "shift_uid",
            # Contact information
            "phone_number",
            "home_phone_number",
            "personal_email",
            "preferred_email",
            # Emargency contact information
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_phone_number",
            # Attendance information
            "attendance_device_id",
            # Company role information
            # "company_role_uid",
            "company_role_uids",
            "report_to",
            "report_to_uid",
            # Payroll information
            "pay_kind",
            "is_over_time",
            "is_double_over_time",
            "is_holiday_pay",
            "is_bonus",
            "is_banking_info_verified",
            "salary_frequency",
            "total_salary",
            "total_hour_per_day",
            "total_day_per_week",
            "total_rate_per_hour",
            # Pay shedule information
            "pay_schedule_uid",
            # Eligibility
            "citizenship_kind",
            "uscis_or_alien_registration_number",
            "from_i_94",
            "foreign_passport",
            "w4_signature",
            "authorized_to_work_until",
            "is_not_applicable",
            "is_included_social_security_number_from_i9",
            # Holiday related
            "holiday_uid",
            # Worked hour related
            "worked_hour_count",
            # banking information
            "banaking_informations",
            # work location
            "work_locations",
            "work_locations_uid",
            "is_same_address",
            "addresses",
            "contribution_and_deductions",
            "created_at",
            "updated_at",
        ]

    read_only_fields = [
        "uid",
        "name",
        "department",
        "designation",
        "shift",
        "is_access_enabled",
        "created_at",
        "updated_at",
    ]

    def validate(self, validated_data):
        company = self.context["request"].user.get_active_company()
        company_users = company.companyuser_set.values_list("user_id", flat=True)
        company_email = validated_data.get("preferred_email")
        employee_id = validated_data.get("employee_id")
        filters = Q(user__in=company_users)
        if company_email:
            filters &= Q(company_email=company_email)
        if employee_id:
            filters &= Q(employee_id=employee_id)

        if company_email or employee_id:
            if User.objects.filter(email=company_email).exists():
                raise ValidationError(
                    {
                        "message": "An employee already exists with the given preferred email or employee ID."
                    }
                )
            if Employee.objects.filter(filters).exists():
                raise ValidationError(
                    {
                        "message": "An employee already exists with the given preferred email or employee ID."
                    }
                )

        # Make sure every requested role belongs to the requester's company.
        all_role_inputs = list(validated_data.get("company_role_uids", []) or [])
        # single = validated_data.get("company_role_uid")
        # if single:
        #     all_role_inputs.append(single)
        for role in all_role_inputs:
            if role.company_id != company.id:
                raise ValidationError(
                    {"message": "One or more roles do not belong to your company."}
                )

        validated_data["company"] = company
        return super().validate(validated_data)

    def get_worked_hour_count(self, object):
        request = self.context.get("request")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        return (
            object.get_worked_hours([start_date, end_date])
            if start_date and end_date
            else object.get_worked_hours(None)
        )

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        # Profile fields are copied to BOTH User (for login identity) and
        # Employee (for HR record). After this point the two diverge.
        first_name = validated_data.get("first_name", "") or ""
        middle_name = validated_data.get("middle_name", "") or ""
        last_name = validated_data.get("last_name", "") or ""
        composed_name = " ".join(
            part for part in (first_name, middle_name, last_name) if part
        )
        gender = validated_data.get("gender") or UserGenderChoices.MALE
        date_of_birth = validated_data.get("date_of_birth")
        ssn = validated_data.get("ssn", "") or ""
        salutation = validated_data.get("salutation", "") or ""
        country = validated_data.get("country") or "us"

        email = validated_data["preferred_email"]
        phone_number = validated_data.get("phone_number", "")
        company = validated_data.pop("company")

        from common.django_rest.helpers.subscription_limits import (
            enforce_subscription_create_limit,
        )
        from subscriptionio.choices import LimitMetricChoices

        enforce_subscription_create_limit(company, LimitMetricChoices.EMPLOYEE)
        enforce_subscription_create_limit(company, LimitMetricChoices.USER)

        validated_data["report_to"] = validated_data.pop("report_to_uid", None)
        validated_data["designation"] = validated_data.pop("designation_uid", None)
        validated_data["department"] = validated_data.pop("department_uid", None)
        validated_data["shift"] = validated_data.pop("shift_uid", None)
        validated_data["pay_schedule"] = validated_data.pop("pay_schedule_uid", None)
        validated_data["holiday"] = validated_data.pop("holiday_uid", None)
        validated_data["work_locations"] = validated_data.pop(
            "work_locations_uid", None
        )

        # Creating user (login identity). Password is left unusable on purpose;
        # the welcome email contains a token-based setup link, never the password.
        user = User.objects.create(
            email=email,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            name=composed_name,
            phone=phone_number,
            gender=gender,
            date_of_birth=date_of_birth,
            ssn=ssn,
            salutation=salutation,
            country=country,
        )
        user.set_password(email)
        user.save()
        validated_data["user"] = user

        # Compose `name` for the Employee row from the supplied parts; this
        # is the independent HR profile name (User.name may diverge later).
        validated_data["name"] = composed_name
        # validated_data["department"] = validated_data.pop("department_uid", None)
        # validated_data["designation"] = validated_data.pop("designation_uid", None)
        validated_data["shift"] = validated_data.pop("shift_uid", None)
        access_token = str(RefreshToken.for_user(user).access_token)
        # Creating company user
        cu, _ = CompanyUser.objects.get_or_create(
            user=user,
            defaults={"company": company},
        )

        # Resolve the role set: always include the system 'employee' role + any
        # admin-selected EMPLOYEE-kind roles. Both `company_role_uid` (legacy single)
        # and `company_role_uids` (new plural) are honoured.
        chosen_roles = list(validated_data.pop("company_role_uids", []) or [])
        # single_role = validated_data.pop("company_role_uid", None)
        # if single_role and single_role not in chosen_roles:
        #     chosen_roles.append(single_role)

        default_employee_role = CompanyRole.objects.filter(
            company=company,
            name=EMPLOYEE_GROUP_NAME,
            is_system=True,
        ).first()
        if default_employee_role and default_employee_role not in chosen_roles:
            chosen_roles.insert(0, default_employee_role)

        if chosen_roles:
            cu.roles.add(*chosen_roles)

        # Place the new user in the system 'employee' Django group.
        employee_group, _ = Group.objects.get_or_create(name=EMPLOYEE_GROUP_NAME)
        user.groups.add(employee_group)
        # chosen_role = single_role  # preserved name for downstream logging

        # Creating employee
        # Set default date fields to date instead of datetime to avoid serialization error
        if "confirmation_date" not in validated_data:
            validated_data["confirmation_date"] = timezone.now().date()
        if "offer_date" not in validated_data:
            validated_data["offer_date"] = timezone.now().date()
        if "terminate_date" not in validated_data:
            validated_data["terminate_date"] = timezone.now().date()
        if "last_date_of_work" not in validated_data:
            validated_data["last_date_of_work"] = timezone.now().date()

        # Login access is granted automatically for the self-onboarding kinds
        # (they receive an invitation email below). MANUAL_ENTRY employees start
        # with access disabled; an admin enables it later to send the invitation.
        validated_data["is_access_enabled"] = (
            validated_data["on_boarding_kind"]
            != EmployeeOnboardingKindChoices.MANUAL_ENTRY
        )

        # Scope the employee record to the company it is being created under.
        validated_data["company"] = company
        employee = Employee.objects.create(**validated_data)
        employee_uid = employee.uid

        actor = self.context["request"].user if "request" in self.context else None
        crud_log(
            logger,
            CrudAction.CREATED,
            user,
            actor=actor,
            extra={"flow": "employee_onboard", "company": company.name},
        )
        role_names = [r.name for r in chosen_roles]
        crud_log(
            logger,
            CrudAction.CREATED,
            employee,
            actor=actor,
            extra={
                "company": company.name,
                "on_boarding_kind": validated_data.get("on_boarding_kind"),
                "roles_assigned": "[" + ",".join(role_names) + "]",
            },
        )

        # Send the welcome / password-setup email to ALL new employees,
        # regardless of on_boarding_kind. Link is token-based; the password is
        # never embedded in the URL.
        if validated_data["on_boarding_kind"] in [
            EmployeeOnboardingKindChoices.SELF_ONBOARD,
            EmployeeOnboardingKindChoices.SELF_ONBOARD_WITH_I9,
        ]:
            invitation_token = generate_invitation_token(user.email)
            frontend_url = getattr(
                settings, "BASE_FRONTEND_URL", None
            ) or os.environ.get("BASE_FRONTEND_URL", "http://localhost:3000")
            # setup_url = f"{frontend_url}/auth/verify-invitation/{invitation_token}?emp={employee_uid}"
            onboarding_url = f"{frontend_url}/onboarding?access_token={access_token}&emp={employee_uid}"
            send_email_to_user(
                {
                    "company": company,
                    "employee": employee,
                    "url": onboarding_url,
                    # "on_boarding_kind": validated_data.get("on_boarding_kind"),
                },
                "emails/onboard/employee_email.html",
                [user.email],
                f"Welcome to {company.name}",
            )
        validated_data["uid"] = employee_uid

        return employee


class PrivateWeEmployeeDetailsSerializer(ModelSerializer):
    user = PrivateEmployeeUserSerializer(read_only=True)
    # Profile fields. These now live on Employee and are independent from the
    # User of the same name (allow_blank so PATCH can clear stored text with "").
    first_name = CharField(max_length=100, required=False, allow_blank=True)
    middle_name = CharField(max_length=100, required=False, allow_blank=True)
    last_name = CharField(max_length=100, required=False, allow_blank=True)
    gender = ChoiceField(
        choices=UserGenderChoices.choices, required=False, allow_blank=True
    )
    salutation = CharField(required=False, max_length=100, allow_blank=True)
    date_of_birth = DateField(required=False)
    ssn = CharField(required=False, max_length=100, allow_blank=True)
    country = ChoiceField(choices=COUNTRIES, required=False, allow_blank=True)
    # is_email_verified verifies the *login email* of the User, so it stays
    # routed to User in update() below.
    is_email_verified = BooleanField(write_only=True, required=False)

    # Department
    department = PrivateCompanyDepartmentSlimSerializer(read_only=True)
    department_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyDepartment.objects.filter(
            status=CompanyDepartmentStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    # Desgnation
    designation = PrivateCompanyDesignationSlimSerializer(read_only=True)
    designation_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyDesignation.objects.filter(
            status=CompanyDesignationStatusChoices.ACTIVE
        ),
        write_only=True,
        required=False,
    )

    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    shift_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyShift.objects.filter(status=CompanyShiftStatusChoices.ACTIVE),
        write_only=True,
        required=False,
    )

    company_roles = SerializerMethodField()
    company_role_uids = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyRole.objects.filter(
            kind=CompanyRoleKindChoices.EMPLOYEE,
            status=CompanyRoleStatusChoices.ACTIVE,
        ),
        write_only=True,
        required=False,
        many=True,
        help_text=(
            "Replace the user's EMPLOYEE-kind roles with this list (additive on top "
            "of the system 'employee' role, which is preserved automatically)."
        ),
    )

    # Report to information
    report_to = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    report_to_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.all().exclude(status=EmployeeStatusChoices.REMOVED),
        write_only=True,
    )

    def get_company_roles(self, obj):
        return [
            {
                "uid": str(r.uid),
                "name": r.name,
                "kind": r.kind,
                "is_system": r.is_system,
            }
            for r in obj.get_company_roles()
        ]

    addresses = PrivateAddressSerializer(
        many=True, read_only=True, source="get_addresses"
    )

    # Banking informations
    banaking_informations = PrivateEmployeeBankingInformationSlimSerializer(
        source="get_banking_informations", read_only=True, many=True
    )

    # Tax information
    taxes = PrivateWeEmployeeTaxDetailsSerializer(
        source="get_first_tax", read_only=True
    )

    # Pay shedule information
    pay_schedule = PrivateEmployeePayScheduleSerializer(read_only=True)
    pay_schedule_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PaySchedule.objects.all().exclude(
            status=EmployeeStatusChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )

    # Holyday information
    holiday = PrivateHolidaySlimSerializer(read_only=True)
    holiday_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Holiday.objects.all(),
        write_only=True,
        required=False,
    )
    payroll_salary_process = PayrollSalaryProcessSlimSerializerForEmployee(
        read_only=True, allow_null=True, source="employee_salary", many=True
    )

    # Work Location
    work_locations = PrivateWePayrollWorkLocationSlimSerializer(read_only=True)
    work_locations_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PayrollWorkLocation.objects.all().exclude(
            status=PayrollWorkLocationChoices.REMOVED
        ),
        write_only=True,
        required=False,
    )

    ein_number = SerializerMethodField(read_only=True)

    def _get_company_ein_number(self, company):
        """Company EIN from federal tax settings (one query per serializer instance)."""
        if not company:
            return None
        cache_key = "_company_ein_number"
        if hasattr(self, cache_key):
            return getattr(self, cache_key)
        ein_number = (
            PayrollFederalTaxInfoSetting.objects.filter(company=company)
            .values_list("ein_number", flat=True)
            .first()
        )
        setattr(self, cache_key, ein_number)
        return ein_number

    def get_ein_number(self, obj):
        company = obj.get_company() or self.context["request"].user.get_active_company()
        return self._get_company_ein_number(company)

    def validate(self, validated_data):
        company = self.context["request"].user.get_active_company()
        company_users = company.companyuser_set.values_list("user_id", flat=True)
        company_email = validated_data.get("preferred_email")
        employee_id = validated_data.get("employee_id")
        filters = Q(user__in=company_users)

        if company_email:
            filters &= Q(company_email=company_email)
        if employee_id:
            filters &= Q(employee_id=employee_id)

        if company_email or employee_id:
            if Employee.objects.filter(filters).exists():
                raise ValidationError(
                    {
                        "message": "An employee already exists with the given preferred email or employee ID."
                    }
                )
        validated_data["company"] = company
        return super().validate(validated_data)

    class Meta:
        model = Employee
        fields = [
            "uid",
            # User (login identity) — nested, read-only
            "user",
            # Employee profile (independent from User)
            "first_name",
            "middle_name",
            "last_name",
            "name",
            "gender",
            "image",
            "salutation",
            "date_of_birth",
            "blood_group",
            "nid_card_no",
            "ssn",
            "country",
            "description",
            "is_email_verified",
            # Employee information
            "code",
            "employee_id",
            "kind",
            "status",
            "company_phone_number",
            "company_email",
            "is_joined",
            "is_access_enabled",
            "on_boarding_kind",
            # Hiring information
            "confirmation_date",
            "notice_period",
            "offer_date",
            "contract_end_date",
            # Terminate information
            "terminate_date",
            "last_date_of_work",
            "terminate_kind",
            "terminate_description",
            # Company information
            "designation",
            "designation_uid",
            "department",
            "department_uid",
            "shift",
            "shift_uid",
            # Contact information
            "phone_number",
            "home_phone_number",
            "personal_email",
            "preferred_email",
            # Emargency contact information
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_phone_number",
            # Attendance information
            "attendance_device_id",
            # Company role information
            # "company_role",
            "company_roles",
            # "company_role_uid",
            "company_role_uids",
            # Report information
            "report_to",
            "report_to_uid",
            # Addresses
            "addresses",
            "is_same_address",
            # Baking informations
            "banaking_informations",
            # Tax information
            "taxes",
            # Payroll information
            "pay_kind",
            "is_over_time",
            "is_double_over_time",
            "is_holiday_pay",
            "is_bonus",
            "is_banking_info_verified",
            "salary_frequency",
            "total_salary",
            "total_hour_per_day",
            "total_day_per_week",
            "total_rate_per_hour",
            # pay scedule information
            "pay_schedule",
            "pay_schedule_uid",
            # Eligibility
            "citizenship_kind",
            "uscis_or_alien_registration_number",
            "from_i_94",
            "foreign_passport",
            "w4_signature",
            "authorized_to_work_until",
            "is_not_applicable",
            "is_included_social_security_number_from_i9",
            # Holiday information
            "holiday",
            "holiday_uid",
            # Payroll salary process
            "payroll_salary_process",
            # Work Location
            "work_locations",
            "work_locations_uid",
            "ein_number",
            "created_at",
            "updated_at",
        ]

    read_only_fields = [
        "uid",
        "name",
        "department",
        "designation",
        "shift",
        "ein_number",
        "created_at",
        "updated_at",
    ]

    def update(self, instance, validated_data):
        # Profile fields previously written here mutated the linked User. After
        # the schema split (employeeio/migrations/0060) they are real fields on
        # Employee — `super().update(...)` at the bottom will set them via
        # validated_data, leaving the User row alone.
        #
        # Two exceptions still write to User:
        #   - `is_email_verified` is a property of the login email, not the HR record.
        user = instance.user
        company = user.get_active_company()

        if "is_email_verified" in validated_data:
            user.is_email_verified = validated_data.pop("is_email_verified")
            user.save_dirty_fields()

        # Recompose Employee.name from the parts when at least one is supplied,
        # but only if the request didn't send an explicit `name`.
        if any(k in validated_data for k in ("first_name", "middle_name", "last_name")):
            first = validated_data.get("first_name", instance.first_name) or ""
            middle = validated_data.get("middle_name", instance.middle_name) or ""
            last = validated_data.get("last_name", instance.last_name) or ""
            composed = " ".join(part for part in (first, middle, last) if part)
            validated_data.setdefault("name", composed)

        # Update employee information
        if department := validated_data.pop("department_uid", None):
            validated_data["department"] = department
        if designation := validated_data.pop("designation_uid", None):
            validated_data["designation"] = designation
        if shift := validated_data.pop("shift_uid", None):
            validated_data["shift"] = shift
        if report_to := validated_data.pop("report_to_uid", None):
            validated_data["report_to"] = report_to
        if pay_schedule := validated_data.pop("pay_schedule_uid", None):
            validated_data["pay_schedule"] = pay_schedule
        if holiday := validated_data.pop("holiday_uid", None):
            validated_data["holiday"] = holiday

        # Work Location
        if work_locations := validated_data.pop("work_locations_uid", None):
            validated_data["work_locations"] = work_locations

        # Role assignment lives on CompanyUser, not Employee. Apply the requested
        # role set if either field is supplied; always preserve the system
        # 'employee' role.
        new_roles_input = list(validated_data.pop("company_role_uids", []) or [])
        # single_role = validated_data.pop("company_role_uid", None)
        # if single_role and single_role not in new_roles_input:
        #     new_roles_input.append(single_role)

        if new_roles_input:
            company_user = instance.user.companyuser_set.filter(company=company).first()
            if company_user:
                default_employee_role = CompanyRole.objects.filter(
                    company=company,
                    name=EMPLOYEE_GROUP_NAME,
                    is_system=True,
                ).first()
                if (
                    default_employee_role
                    and default_employee_role not in new_roles_input
                ):
                    new_roles_input.insert(0, default_employee_role)
                before = list(company_user.roles.values_list("name", flat=True))
                company_user.roles.set(new_roles_input)
                crud_log(
                    logger,
                    CrudAction.ROLES_CHANGED,
                    company_user,
                    actor=self.context["request"].user,
                    extra={
                        "user": user.email,
                        "before": "[" + ",".join(before) + "]",
                        "after": "[" + ",".join(r.name for r in new_roles_input) + "]",
                    },
                )

        # When an admin grants login access (flips is_access_enabled from
        # False -> True), send the invitation email so the employee can complete
        # account setup. This applies to ANY on_boarding_kind: MANUAL_ENTRY
        # employees start disabled and get enabled here, while self-onboard
        # employees whose access was previously revoked can be re-invited the
        # same way. The link is token-based; no credentials are ever embedded in
        # the URL. Revoking access (is_access_enabled -> False) is silent and
        # just persisted below.
        granting_access = (
            bool(validated_data.get("is_access_enabled"))
            and not instance.is_access_enabled
        )
        if granting_access:
            invitation_token = generate_invitation_token(user.email)
            frontend_url = getattr(
                settings, "BASE_FRONTEND_URL", None
            ) or os.environ.get("BASE_FRONTEND_URL", "http://localhost:3000")
            onboarding_url = (
                f"{frontend_url}/auth/verify-invitation/{invitation_token}"
                f"?emp={instance.uid}"
            )
            send_email_to_user(
                {
                    "company": company,
                    "employee": instance,
                    "url": onboarding_url,
                    "on_boarding_kind": instance.on_boarding_kind,
                },
                "emails/onboard/employee_email.html",
                [user.email],
                f"Welcome to {company.name}",
            )

        actor = self.context["request"].user if "request" in self.context else None
        crud_log(
            logger,
            CrudAction.UPDATED,
            instance,
            actor=actor,
            extra={
                "company": company.name if company else None,
                "fields_changed": ",".join(sorted(validated_data.keys())),
            },
        )
        return super().update(instance, validated_data)


class PrivateWeEmployeeEducationListSerializer(ModelSerializer):
    class Meta:
        model = EmployeeEducation
        fields = [
            "uid",
            "status",
            "institute_name",
            "degree",
            "level",
            "passing_year",
            "grade",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )

        validated_data["status"] = EmployeeEducationStatusChoices.ACTIVE
        return super().create(validated_data)


class PrivateWeEmployeeEducationDetailsSerializer(ModelSerializer):
    class Meta:
        model = EmployeeEducation
        fields = [
            "uid",
            "status",
            "institute_name",
            "degree",
            "level",
            "passing_year",
            "grade",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class PrivateWeEmployeeWorkExperienceListSerializer(ModelSerializer):
    class Meta:
        model = EmployeeWorkExperience
        fields = [
            "uid",
            "status",
            "kind",
            "company_name",
            "branch_name",
            "department",
            "designation",
            "start_date",
            "end_date",
            "total_salary",
            "full_address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        validated_data["status"] = EmployeeWorkExperienceStatusChoices.ACTIVE
        return super().create(validated_data)


class PrivateWeEmployeeWorkExperienceDetailsSerializer(ModelSerializer):
    class Meta:
        model = EmployeeWorkExperience
        fields = [
            "uid",
            "status",
            "kind",
            "company_name",
            "branch_name",
            "department",
            "designation",
            "start_date",
            "end_date",
            "total_salary",
            "full_address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class PrivateWeEmployeeBankingInformationListSerializer(ModelSerializer):

    class Meta:
        model = EmployeeBankingInformation
        fields = [
            "uid",
            "status",
            "kind",
            "bank_name",
            "bank_account_number",
            "bank_account_type",
            "routing_number",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["status"] = EmployeeBankingInformationStatusChoices.ACTIVE
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        return super().create(validated_data)


class PrivateWeEmployeeBankingInformationDetailsSerializer(ModelSerializer):

    class Meta:
        model = EmployeeBankingInformation
        fields = [
            "uid",
            "status",
            "kind",
            "bank_name",
            "bank_account_number",
            "bank_account_type",
            "routing_number",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]


class PrivateWeEmployeeEarningListSerializer(ModelSerializer):
    class Meta:
        model = EmployeeEarning
        fields = [
            "uid",
            "status",
            "pay_kind",
            "total_recurring_amount",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["status"] = EmployeeEarningStatusChoices.ACTIVE
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        return super().create(validated_data)


class PrivateWeEmployeeEarningDetilsSerializer(ModelSerializer):
    class Meta:
        model = EmployeeEarning
        fields = [
            "uid",
            "status",
            "pay_kind",
            "total_recurring_amount",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class PrivateWeEmployeeGarnishmentListSerializer(ModelSerializer):

    class Meta:
        model = EmployeeGarnishment
        fields = [
            "uid",
            "status",
            "kind",
            "description",
            "total_requsted_amount",
            "total_maximum_percentage_of_disposal_income",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["status"] = EmployeeGarnishmentStatusChoices.ACTIVE
        validated_data["employee"] = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )

        return super().create(validated_data)


class PrivateWeEmployeeGarnishmentDetailsSerializer(ModelSerializer):

    class Meta:
        model = EmployeeGarnishment
        fields = [
            "uid",
            "status",
            "kind",
            "description",
            "total_requsted_amount",
            "total_maximum_percentage_of_disposal_income",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status"]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class PrivateWeEmployeeDocuementListSerializer(ModelSerializer):

    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "file",
            "description",
            "status",
            "kind",
            "link",
            "is_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "title",
            "link",
            "is_report",
            "description",
            "status",
            "kind",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["company"] = self.context["request"].user.get_active_company()
        validated_data["title"] = validated_data["file"].name
        validated_data["status"] = FileItemStatusChoices.PUBLISHED
        validated_data["kind"] = get_file_kind(
            os.path.splitext(validated_data["title"])[1]
        )

        # Creating file item
        file_item = FileItem.objects.create(**validated_data)

        # Creating file item connector
        employee = get_object_or_404(
            Employee.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                company=self.context["request"].user.get_active_company(),
            )
        )
        FileItemConnector.objects.create(
            file_item=file_item,
            model_kind=FileItemConnectorModelKindChoices.EMPLOYEE,
            employee=employee,
        )
        return validated_data


class PrivateWeEmployeeDocuementDetailsSerializer(ModelSerializer):

    class Meta:
        model = FileItem
        fields = [
            "uid",
            "title",
            "file",
            "description",
            "status",
            "kind",
            "link",
            "is_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "title",
            "link",
            "is_report",
            "description",
            "status",
            "kind",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        validated_data["title"] = validated_data["file"].name
        validated_data["status"] = FileItemStatusChoices.PUBLISHED
        validated_data["kind"] = get_file_kind(
            os.path.splitext(validated_data["title"])[1]
        )
        return super().update(instance, validated_data)
