from autoslug import AutoSlugField

from versatileimagefield.fields import VersatileImageField

from phonenumber_field.modelfields import PhoneNumberField

from simple_history.models import HistoricalRecords

from django.db import models
from django.contrib.auth.models import Permission

from common.choices import CurrencyChoices, MonthChoices, TaxKindChoices, WeekChoices
from common.models import BaseModelWithUID

from subscriptionio.choices import (
    CompanySubscriptionStatusChoices,
    CompanySubscriptionKindChoices,
)

from employeeio.models import Employee


from .choices import (
    CompanyStatusChoices,
    CompanyInvitationStatusChoices,
    CompanyShiftKindChoices,
    CompanyShiftStatusChoices,
    CompanyDepartmentStatusChoices,
    CompanySectionStatusChoices,
    CompanyDesignationStatusChoices,
    CompanyAccountingMethodChoices,
    CompanySettingTaxFormChoices,
    CompanyKindChoices,
)

from .django_rest.helpers.media_path import get_company_media_path_prefix
from .django_rest.helpers.slug_helpers import (
    get_company_slug,
    get_company_shift_slug,
    get_company_department_slug,
    get_company_section_slug,
    get_company_designation_slug,
    get_company_setting_slug,
)

from .managers import (
    CompanyDesignationQuerySet,
    CompanySectionQuerySet,
    CompanyDepartmentQuerySet,
    CompanyShiftQuerySet,
)


class Company(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_company_slug, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    legal_name = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=CompanyStatusChoices.choices,
        db_index=True,
        default=CompanyStatusChoices.ACTIVE,
    )
    kind = models.CharField(
        max_length=50,
        choices=CompanyKindChoices.choices,
        default=CompanyKindChoices.CONSTRUCTION,
    )
    business_id_no = models.CharField(max_length=100, blank=True, null=True)
    vat_number = models.CharField(max_length=100, blank=True, null=True)
    time_zone = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = PhoneNumberField(unique=True, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    company_addresses = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "JSON encoded keyword arguments"
            '(Example: {"address": "address", "city": "city", "state": "state", "country": "country", "zip_code": "zip_code"}),'
        ),
    )
    customer_facing_address = models.CharField(max_length=255, blank=True, null=True)
    logo = VersatileImageField(
        "Logo",
        upload_to=get_company_media_path_prefix,
        blank=True,
    )

    # simple history
    history = HistoricalRecords()

    def __str__(self):
        return f"ID: {self.id}, Name: {self.name}"

    class Meta:
        verbose_name = "Companies"

    def get_company_addresses_dict(self):
        """Return company_addresses as a dict, tolerating legacy string values.

        The JSONField can end up holding a JSON-encoded *string* when a client
        double-encodes it; coerce such values back to a mapping so callers can
        safely `.get(...)`.
        """
        value = self.company_addresses
        if isinstance(value, str):
            import json

            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value if isinstance(value, dict) else {}

    def get_legal_address(self):
        from payrollio.models import PayrollGeneralTaxSetting

        general_tax_setting = PayrollGeneralTaxSetting.objects.filter(
            company=self
        ).first()
        if not general_tax_setting or not general_tax_setting.address:
            return self.get_company_addresses_dict().get("address") or ""
        parts = [
            general_tax_setting.address,
            general_tax_setting.city,
            general_tax_setting.state,
            general_tax_setting.zip_code,
        ]
        return ", ".join(part for part in parts if part)

    @property
    def legal_address(self):
        return self.get_legal_address()

    def get_employees(self):
        return Employee.objects.filter(company=self)

    def get_currencies(self):
        return self.currency_set.all()

    def get_excange_rates(self, date, currency=None):
        return self.get_currencies().filter(date__date=date, kind=currency)

    def get_active_subscription_kinds(self):
        return set(
            self.companysubscription_set.filter(
                status=CompanySubscriptionStatusChoices.ACTIVE
            ).values_list("kind", flat=True)
        )

    def is_company_subscribed(self):
        return (
            CompanySubscriptionKindChoices.COMPANY_SUBSCRIPTION
            in self.get_active_subscription_kinds()
        )

    def is_accountant_subscribed(self):
        return (
            CompanySubscriptionKindChoices.ACCOUNTANT_SUBSCRIPTION
            in self.get_active_subscription_kinds()
        )


class CompanyShift(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_company_shift_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=CompanyShiftStatusChoices.choices,
        db_index=True,
        default=CompanyShiftStatusChoices.ACTIVE,
    )
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    kind = models.CharField(
        max_length=50,
        choices=CompanyShiftKindChoices,
        default=CompanyShiftKindChoices.DAY,
    )

    # Regular
    regular_hour = models.PositiveIntegerField(blank=True, null=True)
    grace_time = models.PositiveIntegerField(blank=True, null=True)
    in_time = models.TimeField()
    out_time = models.TimeField()

    # Associate with lunch
    lunch_time = models.PositiveIntegerField(blank=True, null=True)
    lunch_in_time = models.TimeField(blank=True, null=True)
    lunch_out_time = models.TimeField(blank=True, null=True)

    # Associate with tiffin
    tiffin_time = models.PositiveIntegerField(blank=True, null=True)
    tiffin_in_time = models.TimeField(null=True, blank=True)
    tiffin_out_time = models.TimeField(null=True, blank=True)

    # FK
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, blank=True, null=True
    )

    # simple history
    history = HistoricalRecords()
    objects = CompanyShiftQuerySet.as_manager()

    class Meta:
        verbose_name = "Shift"

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"

    def get_workable_hour(self):
        in_time = int(self.in_time.strftime("%H")) + int(self.in_time.strftime("%M"))
        out_time = int(self.out_time.strftime("%H")) + int(self.out_time.strftime("%M"))
        if out_time < in_time:
            out_time += 24
        return out_time - in_time


class CompanyDepartment(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_company_department_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=CompanyDepartmentStatusChoices.choices,
        db_index=True,
        default=CompanyDepartmentStatusChoices.ACTIVE,
    )
    code = models.CharField(max_length=100)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    # simple history
    history = HistoricalRecords()
    objects = CompanyDepartmentQuerySet.as_manager()

    class Meta:
        # Uniqueness is enforced per-company among ACTIVE rows at the serializer
        # layer (like CompanyShift), so a removed/inactive title can be reused.
        # The old unique_together here was dead code — shadowed by this second
        # Meta, so it never reached the database.
        verbose_name = "Department"

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"


class CompanySection(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_company_section_slug, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=CompanySectionStatusChoices.choices,
        db_index=True,
        default=CompanySectionStatusChoices.ACTIVE,
    )
    department = models.ForeignKey(CompanyDepartment, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    # simple history
    history = HistoricalRecords()
    objects = CompanySectionQuerySet.as_manager()

    class Meta:
        verbose_name = "Section"

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"


class CompanyDesignation(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_company_designation_slug, unique=True, db_index=True
    )
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=CompanyDesignationStatusChoices.choices,
        db_index=True,
        default=CompanyDesignationStatusChoices.ACTIVE,
    )
    code = models.CharField(max_length=100, blank=True, null=True)
    # simple history
    history = HistoricalRecords()
    objects = CompanyDesignationQuerySet.as_manager()

    class Meta:
        verbose_name = "Designation"
        # Unique per-company among ACTIVE rows only, so a removed/inactive title
        # can be reused (matches CompanyShift/CompanyDepartment behaviour).
        constraints = [
            models.UniqueConstraint(
                fields=["company", "title"],
                condition=models.Q(
                    status=CompanyDesignationStatusChoices.ACTIVE
                ),
                name="uniq_active_designation_company_title",
            )
        ]

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"


class CompanyUser(BaseModelWithUID):
    # TODO: nedd to add slug here
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    roles = models.ManyToManyField(
        "adminio.CompanyRole",
        blank=True,
        related_name="company_users",
        help_text="Roles assigned to this user in this company. Multiple roles are additive.",
    )
    permission = models.ManyToManyField(
        Permission,
        blank=True,
        help_text="Per-user permission overlay applied on top of the user's roles.",
    )
    # Workspace-switcher state (per user, per company).
    is_pinned = models.BooleanField(
        default=False,
        help_text="Whether the user pinned this company to the top of their workspace switcher.",
    )
    last_opened_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the user last selected/entered this company. Drives the 'last opened' sort and label.",
    )

    class Meta:
        unique_together = ("user", "company")

    def __str__(self):
        return f"ID: {self.id}, Name: {self.user.name}, Company: {self.company.name}"


class CompanyInvitation(BaseModelWithUID):
    """A pending invitation for someone to join a company.

    Backs the multi-company invite flows:
      * an admin invites an email into their company (email-bound), and
      * the recipient joins via the link or by typing the shareable ``code``
        in the workspace 'Add a company -> Join with code' modal.

    Unlike the legacy stateless signed-token invite, this row is listable and
    revocable, and -- crucially for multi-tenancy -- lets an *existing* user be
    invited into an additional company without creating a duplicate account: on
    acceptance we simply add a CompanyUser for them.
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField(
        db_index=True,
        help_text="Invitee email. Acceptance requires the accepting user's email to match.",
    )
    invited_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_company_invitations",
    )
    roles = models.ManyToManyField(
        "adminio.CompanyRole",
        blank=True,
        related_name="invitations",
        help_text="Roles to grant the invitee on acceptance.",
    )
    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Human-enterable code for the 'Join with code' flow.",
    )
    status = models.CharField(
        max_length=20,
        choices=CompanyInvitationStatusChoices.choices,
        default=CompanyInvitationStatusChoices.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_company_invitations",
    )

    class Meta:
        # At most one live (pending) invitation per email per company; accepted/
        # revoked rows are kept for history and don't collide on this constraint.
        constraints = [
            models.UniqueConstraint(
                fields=["company", "email"],
                condition=models.Q(status=CompanyInvitationStatusChoices.PENDING),
                name="uniq_pending_invitation_per_company_email",
            )
        ]

    def __str__(self):
        return f"Invite {self.email} -> {self.company.name} ({self.status})"

    def is_expired(self):
        from django.utils import timezone

        return self.expires_at is not None and timezone.now() > self.expires_at


class CompanySetting(BaseModelWithUID):
    """Always keep setting-related models at the bottom for better maintainability.
    Insert any new models above `CompanySetting` as needed to preserve logical structure.
    """

    slug = AutoSlugField(
        populate_from=get_company_setting_slug, unique=True, db_index=True
    )

    # Accounting
    preffered_first_financial_month = models.CharField(
        max_length=50, choices=MonthChoices, blank=True, null=True
    )
    preffered_first_tax_month = models.CharField(
        max_length=50, choices=MonthChoices, blank=True, null=True
    )
    accounting_method = models.CharField(
        max_length=50, choices=CompanyAccountingMethodChoices, blank=True, null=True
    )
    preffered_tax = models.CharField(
        max_length=50, choices=TaxKindChoices, blank=True, null=True
    )

    # Company type
    tax_form = models.CharField(
        max_length=50, choices=CompanySettingTaxFormChoices, blank=True, null=True
    )

    # Chart or accounts
    is_chart_of_account = models.BooleanField(default=False)

    # Categories
    is_track_classes = models.BooleanField(default=False)
    is_track_location = models.BooleanField(default=False)

    # Automations
    prefill_forms = models.BooleanField(
        blank=True, null=True
    )  # Pre-fill forms with previously entered content
    auto_invoice_unbilled_activity = models.BooleanField(blank=True, null=True)
    auto_apply_bill_payments = models.BooleanField(blank=True, null=True)

    # Projects
    is_organized_job_related_activity = models.BooleanField(blank=True, null=True)

    # Language

    # Currency
    home_currency = models.CharField(
        max_length=50, choices=CurrencyChoices, default=CurrencyChoices.USD
    )
    multi_currency = models.CharField(
        max_length=50, choices=CurrencyChoices, default=CurrencyChoices.USD
    )

    # Other perfomance
    is_warn_duplicate_cheque_number = models.BooleanField(default=False)
    is_warn_duplicate_bill_number = models.BooleanField(default=False)
    is_warn_duplicate_journal_number = models.BooleanField(default=False)
    sing_me_out = models.FloatField(blank=True, null=True)

    tax_id = models.CharField(max_length=50, blank=True, null=True)

    # Time
    preffered_first_day = models.CharField(
        max_length=50,
        choices=WeekChoices,
        blank=True,
        null=True,
    )
    is_service_field = models.BooleanField(default=False)
    is_allow_time_to_billable = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}, Preffered financial month: {self.preffered_first_financial_month}"
