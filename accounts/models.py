from autoslug import AutoSlugField

from datetime import date

from phonenumber_field.modelfields import PhoneNumberField

from versatileimagefield.fields import VersatileImageField

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models import Sum, Q, Count
from django.db.models.functions import Upper
from django.utils import timezone

from common.choices import CurrencyChoices
from common.django_rest.helpers.countries import COUNTRIES
from common.models import BaseModelWithUID

from companyio.models import Company

from customerio.models import Customer

from purchaseio.models import Purchase

from salesio.models import Sale

from supplierio.models import Supplier

from .choices import (
    UserStatusChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountKindChoices,
    ChartOfAccountSystemKeyChoices,
    UserGenderChoices,
)
from .managers import CustomUserManager, ChartOfAccountQuerySet
from .django_rest.helpers.slug_helpers import get_user_slug, get_chart_of_account_slug
from .django_rest.helpers.media_path import get_user_media_path_prefix


class User(AbstractBaseUser, PermissionsMixin, BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_user_slug, unique=True, db_index=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=250, blank=True, null=True)
    salutation = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=10, null=True, blank=True)
    gender = models.CharField(
        max_length=50,
        choices=UserGenderChoices.choices,
        db_index=True,
        default=UserGenderChoices.MALE,
    )
    nid_card_no = models.CharField(max_length=50, null=True, blank=True)
    ssn = models.CharField(max_length=100, blank=True, null=True)
    phone = PhoneNumberField(blank=True, null=True)
    email = models.EmailField(unique=True, db_index=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    is_terms_service = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=UserStatusChoices.choices,
        db_index=True,
        default=UserStatusChoices.ACTIVE,
    )
    image = VersatileImageField(
        "Image", upload_to=get_user_media_path_prefix, blank=True, null=True
    )

    is_staff = models.BooleanField(default=False)
    is_sms_verification_enabled = models.BooleanField(
        default=False, help_text="Enable two-step verification via SMS."
    )
    is_email_verification_enabled = models.BooleanField(
        default=False, help_text="Enable two-step verification via email passcode."
    )
    description = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    country = models.CharField(
        max_length=2, choices=COUNTRIES, default="us", db_index=True
    )
    # Realtime / presence
    last_seen = models.DateTimeField(null=True, blank=True)
    is_admin = models.BooleanField(default=False)
    USERNAME_FIELD = "email"
    # Django adds the password prompt automatically; listing it here causes a
    # duplicate prompt in `createsuperuser`.
    REQUIRED_FIELDS = ("name",)

    # Managers
    objects = CustomUserManager()

    def __str__(self):
        return (
            f"Name: {self.name}, Email: {self.email}"
            if len(self.email) > 0
            else f"Name: {self.name} Phone: {self.phone}"
        )

    def activate(self):
        self.status = UserStatusChoices.ACTIVE
        self.save_dirty_fields()

    def deactivate(self):
        self.status = UserStatusChoices.INACTIVE
        self.save_dirty_fields()

    def removed(self):
        self.status = UserStatusChoices.REMOVED
        self.is_active = False
        self.save_dirty_fields()

    def get_active_company(self):
        """Return the company this request is scoped to.

        When a company has been selected (its id is set on the per-request
        tenant context by ``TenantContextMiddleware`` from the JWT claim), we
        return that company -- but only if the user actually belongs to it, so
        a tampered/stale token can never widen access. When no company is
        selected (login, company-selection endpoints, management commands) we
        fall back to the user's first membership for backwards compatibility.
        """
        from common.tenant import get_current_company_id
        from companyio.choices import CompanyStatusChoices

        company_id = get_current_company_id()
        if company_id is not None:
            companyuser = (
                self.companyuser_set.select_related("company")
                .filter(company_id=company_id)
                .exclude(company__status=CompanyStatusChoices.REMOVED)
                .first()
            )
            if companyuser is not None:
                return companyuser.company
            # Context points at a company the user is not a member of, or at one
            # that has been removed: do not silently fall back to another
            # company -- deny instead.
            return None

        companyuser = (
            self.companyuser_set.select_related("company")
            .exclude(company__status=CompanyStatusChoices.REMOVED)
            .first()
        )
        return companyuser.company if companyuser else None

    # These three guard against `get_active_company()` returning None. It can:
    # when the token points at a company the user is not a member of, when the
    # user has no membership at all, or when their company has been removed.
    # Dereferencing None here raised AttributeError *before* the callers' own
    # `if not setting: raise NotFound` could run, turning a clean 404 into a 500.
    def get_company_setting(self):
        company = self.get_active_company()
        return company.companysetting_set.first() if company else None

    def get_company_purchase_setting(self):
        company = self.get_active_company()
        return company.purchasesetting_set.first() if company else None

    def get_company_sale_setting(self):
        company = self.get_active_company()
        return company.salesetting_set.first() if company else None

    def get_employee(self):
        """Return this user's employee record for the active company.

        Employees are per-company, so when a company is in context we return the
        matching employee record. With no context (or no per-company match) we
        fall back to any employee record for backwards compatibility.
        """
        from common.tenant import get_current_company_id

        company_id = get_current_company_id()
        if company_id is not None:
            employee = self.employee_set.filter(company_id=company_id).first()
            if employee is not None:
                return employee
        return self.employee_set.filter().first()

    def get_designation(self):
        employee = self.get_employee()
        return employee.designation if employee else None

    def get_is_agent(self):
        return self.is_superuser


class OTP(BaseModelWithUID):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    is_consumed = models.BooleanField(
        default=False
    )  # Checks if OTP has been used or not

    def is_valid(self):
        # OTP is valid for 5 minutes and it can be used only once
        return (
            not self.is_consumed
            and timezone.now() <= self.created_at + timezone.timedelta(minutes=15)
        )


class ChartOfAccount(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_chart_of_account_slug, unique=True, db_index=True
    )
    date = models.DateField(default=date.today)
    code = models.CharField(max_length=50)
    status = models.CharField(
        choices=ChartOfAccountStatusChoices,
        default=ChartOfAccountStatusChoices.DRAFT,
        max_length=50,
    )
    kind = models.CharField(
        choices=ChartOfAccountKindChoices,
        default=ChartOfAccountKindChoices.ASSETS,
        max_length=50,
    )

    # TODO: account_type and details_type will be required field
    account_type = models.ForeignKey(
        "categoryio.Category",
        on_delete=models.CASCADE,
        related_name="account_categories",
        blank=True,
        null=True,
    )
    detail_type = models.ForeignKey(
        "categoryio.Category",
        on_delete=models.CASCADE,
        related_name="detail_categories",
        blank=True,
        null=True,
    )
    # Stable identifier for the accounts the posting engine has to find.
    # Null for ordinary accounts; set only on the control-account spine.
    # `title` is a user-editable label -- resolving control accounts by it meant
    # a rename silently broke posting. See ChartOfAccountSystemKeyChoices.
    system_key = models.CharField(
        max_length=50,
        choices=ChartOfAccountSystemKeyChoices,
        blank=True,
        null=True,
        db_index=True,
    )
    opening_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    used_amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    currency = models.CharField(
        choices=CurrencyChoices, default=CurrencyChoices.USD, max_length=50
    )
    description = models.TextField(blank=True, null=True)
    is_fixed = models.BooleanField(default=False)

    # Is this an account money actually moves through -- a bank account or a
    # credit card -- as opposed to one that merely has a balance?
    #
    # Nothing could answer that before. The de-facto test was
    # `account_type__title == "Bank"`, a **user-editable Category title matched
    # exactly** (see `weapi/.../dashboards/v1/dashboards.py:113`), which a
    # rename breaks silently and which omits credit cards altogether. So every
    # money-account picker in the product accepted any selectable account, and
    # half the reconciliations on production point at an expense account.
    #
    # `system_key` is the codebase's answer to "resolve this account reliably",
    # but it is unique per company and a company has many bank accounts, so it
    # is the wrong shape here. A flag is.
    #
    # Backfilled from the two account types the seed calls money -- "Bank" and
    # "Credit Cards" (`categoryio/management/commands/data/chart_of_accounts.py`)
    # -- and writable thereafter, because an account type can be renamed and a
    # tenant may have built its chart before this existed.
    is_money_account = models.BooleanField(default=False, db_index=True)

    # Plaid related
    bank_balance = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    bank_id = models.CharField(max_length=255, blank=True, null=True)

    # FK
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="parents"
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    objects = ChartOfAccountQuerySet.as_manager()

    # Inherits `ordering = ("-created_at",)` from BaseModelWithUID. Declaring a
    # bare `class Meta` here would silently drop it and reorder every
    # ChartOfAccount query in the product.
    class Meta(BaseModelWithUID.Meta):
        abstract = False
        constraints = [
            # One account per system key per company. Removed accounts are
            # excluded so a soft-deleted control account cannot block its
            # replacement -- deletion is soft everywhere here, so without the
            # carve-out a company could never recover from removing one.
            models.UniqueConstraint(
                fields=["company", "system_key"],
                condition=Q(system_key__isnull=False)
                & ~Q(status=ChartOfAccountStatusChoices.REMOVED),
                name="unique_system_key_per_company",
            ),
            # One live account per title per company, case-insensitively. COA #16.
            #
            # UPPER(title), not title. The gap this closes is justified by
            # payroll's `title__iexact` lookup, so a case-sensitive index would
            # not close it -- "Health Insurance" beside "health insurance" would
            # still resolve to whichever the lookup happened to find. The
            # pre-flight made exactly that mistake and reported that pair clean
            # until d9816a53.
            #
            # Blank titles are carved out as well as REMOVED ones. `title` is a
            # non-null CharField with no default, so an omitted kwarg persists as
            # `''` rather than NULL: without the carve-out two accounts saved
            # without a title would collide, and the NULL-based carve-out that
            # makes `unique_system_key_per_company` work does not transfer.
            #
            # There is deliberately NO companion index on (company, code).
            # `code` has no consumer -- posting resolves by system_key then
            # title, both report engines bucket on Category titles, and nothing
            # exports by code. Blank codes self-collide for the same reason as
            # blank titles, and renumbering a seeded `is_fixed` account is
            # one-way for the tenant, since the serializer refuses to modify one.
            models.UniqueConstraint(
                Upper("title"),
                "company",
                condition=~Q(status=ChartOfAccountStatusChoices.REMOVED)
                & ~Q(title__isnull=True)
                & ~Q(title__exact=""),
                name="unique_title_per_company_ci",
            ),
        ]

    # Changing any of these moves the account to a different place on the
    # financial statements. Doing that after the account has been posted to
    # silently restates every prior period.
    CLASSIFICATION_FIELDS = ("kind", "account_type", "detail_type")

    def has_journal_lines(self):
        return self.journalentryconnector_set.exists()

    def save(self, *args, **kwargs):
        """Block reclassification of an account that has already been posted to.

        Enforced here rather than in a serializer because the serializer is not
        the only writer -- the admin, the shell, the CSV importer and the
        rollback services all reach the model directly.

        This deliberately checks `get_dirty_fields()` first. `save()` runs on
        every single balance update (`update_opening_balance` ends in
        `save_dirty_fields()`), so an unconditional journal-lines query here
        would put a COUNT on the hot posting path. The lookup only happens when
        one of the three classification fields actually changed, which is rare.
        """
        if self.pk and not self._state.adding:
            dirty = self.get_dirty_fields(check_relationship=True)
            changed = [f for f in self.CLASSIFICATION_FIELDS if f in dirty]
            if changed and self.has_journal_lines():
                raise DjangoValidationError(
                    {
                        field: (
                            f"Cannot change {field} on an account that already has "
                            "journal entries -- it would restate every period this "
                            "account appears in. Create a new account and move the "
                            "balance across with a dated journal entry instead."
                        )
                        for field in changed
                    }
                )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"ID: {self.pk}, Title: {self.title}, Company: {self.company.name}, Status: {self.status}"

    def get_total_debit_credit(self):
        company = self.company
        if self.title == "Historical Adjustment":
            total_debit_credit = (
                ChartOfAccount.objects.get_status_all()
                .filter(Q(company=company, journalentryconnector__isnull=False))
                .aggregate(
                    total_debit=Sum("journalentryconnector__debit"),
                    total_credit=Sum("journalentryconnector__credit"),
                )
            )
            total_debit = total_debit_credit["total_debit"] or 0
            total_credit = total_debit_credit["total_credit"] or 0
        else:
            total_debit_credit = self.journalentryconnector_set.aggregate(
                total_debit=Sum("debit"), total_credit=Sum("credit")
            )
            total_debit = total_debit_credit["total_debit"] or 0
            total_credit = total_debit_credit["total_credit"] or 0

        if total_debit > total_credit:
            total_debit -= total_credit
            total_credit = 0
        else:
            total_credit -= total_debit
            total_debit = 0
        return {"total_debit": total_debit, "total_credit": total_credit}

    def get_total_debit(self):
        return self.get_total_debit_credit()["total_debit"]

    def get_total_credit(self):
        return self.get_total_debit_credit()["total_credit"]

    def get_total_transacted_amount(self):
        return (
            self.journalentryconnector_set.aggregate(total=Sum("total"))["total"] or 0
        )

    def get_counts(self):
        if not hasattr(self, "_cached_counts"):
            self._cached_counts = self.journalentryconnector_set.aggregate(
                supplier_count=Count("id", filter=Q(supplier__isnull=False)),
                customer_count=Count("id", filter=Q(customer__isnull=False)),
                invoice_count=Count(
                    "id",
                    filter=Q(
                        journal__sale__isnull=False, journal__sale__is_invoice=True
                    ),
                ),
                bill_count=Count(
                    "id",
                    filter=Q(
                        journal__purchase__isnull=False, journal__purchase__is_bill=True
                    ),
                ),
            )
        return self._cached_counts

    def get_supplier_count(self):
        return Supplier.objects.get_status_active().filter(company=self.company).count()

    def get_customer_count(self):
        return Customer.objects.get_status_active().filter(company=self.company).count()

    def get_invoice_count(self):
        return Sale.objects.filter(company=self.company, is_invoice=True).count()

    def get_bill_count(self):
        return Purchase.objects.filter(company=self.company, is_bill=True).count()

    def get_last_balance(self, dates=None):
        """This account's movement over `dates`, computed from its lines.

        It used to return the newest connector's stored `last_balance` -- an
        account-wide running total frozen at the moment of last activity. With
        a date filter that reported a figure belonging to no period at all: not
        the movement during the window, and not the balance at the end of it,
        but wherever the account happened to stand when it was last touched
        inside the window. Reports summed those into headline totals.

        It was also filtered on `created_at`, the row insertion timestamp, so a
        backdated document counted into the period it was entered in rather
        than the one it belongs to.

        Now derived: see `common/django_rest/helpers/ledger_balances.py`. Use
        `account_balance_as_of` when a closing position is what is wanted --
        a period movement is not a balance.
        """
        from common.django_rest.helpers.ledger_balances import account_movement

        return account_movement(self, dates)
