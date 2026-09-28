from django.contrib.auth.base_user import BaseUserManager
from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

from .choices import UserStatusChoices, ChartOfAccountStatusChoices

from companyio.models import Company
from companyio.models import CompanyUser

from employeeio.models import Employee


class UserQuerySet(QuerySet):
    def get_status_active(self):
        return self.filter(status=UserStatusChoices.ACTIVE)


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def get_queryset(self):
        return UserQuerySet(model=self.model, using=self._db, hints=self._hints)

    def create_user(self, name, email, password, **extra_fields):
        if not email:
            raise ValidationError(_("Email address is required"))
        if not password:
            raise ValidationError(_("Password is required"))

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.name = name.title()
        user.save(using=self._db)
        return user

    def create_superuser(self, name, email, password, **extra_fields):
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_staff", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        # Create super user
        user = self.create_user(name, email, password, **extra_fields)

        # Creating employee (superuser is an operational/developer account; HR record is convenient)
        Employee.objects.create(user=user, company_email=email)

        # Create the superuser's home company and seed system roles, then attach
        # the admin role. Imported here to avoid import-time cycles.
        from weapi.django_rest.serializers.companies import PrivateWeCompanySerializer

        company = Company.objects.create(name=f"{name}-organization", email=email)
        admin_role, _, _ = PrivateWeCompanySerializer().seed_company_roles(company)
        cu = CompanyUser.objects.create(user=user, company=company)
        cu.roles.add(admin_role)

        return user


# The two account-type categories the seed defines as ones money moves through
# (`categoryio/management/commands/data/chart_of_accounts.py`). "Credit Cards"
# is plural there; "Credit Card" is the detail type beneath it.
MONEY_ACCOUNT_TYPE_TITLES = ("Bank", "Credit Cards")


class ChartOfAccountQuerySet(QuerySet):

    def money(self):
        """Accounts money actually moves through -- banks and credit cards.

        One predicate, in one place, because before this every money picker in
        the product had its own idea and most of them had none: they took any
        selectable account, which is why half the reconciliations on production
        target an expense account.

        Three arms, and each earns its place:

        - `is_money_account` is the authoritative signal. It survives an account
          type being renamed, which the title match does not, and a tenant can
          set it on an account the taxonomy never covered.
        - The account-type title is a fallback so this is correct **before** the
          backfill has run -- notably in tests, where the project disables
          migrations, and for any row created after 0047 by a path that does not
          set the flag.
        - A NULL account type is admitted deliberately. The field is nullable
          and legacy charts predate the taxonomy; refusing the unknown would
          lock those tenants out of deposits and reconciliation entirely, which
          is a worse failure than the one being fixed. An account positively
          typed as something else is still refused, and that is the case this
          exists for.

        The NULL arm is transitional. When Phase 2 shows no tenant still has
        untyped accounts, it comes out.
        """
        return self.filter(
            Q(is_money_account=True)
            | Q(account_type__title__in=MONEY_ACCOUNT_TYPE_TITLES)
            | Q(account_type__isnull=True)
        )

    def selectable(self):
        """Accounts a user may choose when building a new document.

        The picker half of deactivation. An inactive account keeps its balance,
        its history and its place in every report -- it is withheld from data
        entry and nothing else -- so this is narrower than `get_status_all()`,
        which excludes only REMOVED and is what reports and resolvers keep
        using.

        Narrower by exactly one state, and no more. The first cut of this
        filtered to ACTIVE, which reads as the same thing and is not: `status`
        **defaults to DRAFT** on the model, so every account created without an
        explicit status -- which is most of them outside the seeding path --
        vanished from every picker at once. Production hides that, because
        seeding sets ACTIVE explicitly and holds no DRAFT rows; 73 tests found
        it.

        So: exclude what has been retired, and leave every other state exactly
        as it was before deactivation existed.
        """
        return self.exclude(
            status__in=[
                ChartOfAccountStatusChoices.REMOVED,
                ChartOfAccountStatusChoices.INACTIVE,
            ]
        ).exclude(
            # Spec s9.2 / COA-131: a parent with children is a summarising
            # header, and data belongs at leaf level. Production shows why --
            # one company put 13,500 of payroll into "Company Contributions",
            # which is a parent, so the figure sits on a summary line while its
            # children total something else.
            #
            # `parents` is the reverse accessor for `parent`, so this reads "has
            # at least one live child". The name is backwards on the model.
            #
            # Withheld from pickers rather than refused at posting time. The
            # spec makes COA-131 a validation error, but four accounts already
            # carry lines and one of them is a live payroll route -- refusing
            # outright would turn a working pay run into a 400. This stops the
            # pattern growing; hard enforcement wants those four resolved first.
            #
            # The per-account relaxation s9.2 allows ("companies may relax this")
            # is NOT built. There is no override field yet, so a company that
            # genuinely wants to post to a parent has no way to say so.
            parents__status__in=[
                ChartOfAccountStatusChoices.ACTIVE,
                ChartOfAccountStatusChoices.DRAFT,
                ChartOfAccountStatusChoices.PENDING,
            ]
        )

    def get_status_all(self):
        return self.all().exclude(status=ChartOfAccountStatusChoices.REMOVED)

    def get_status_active(self):
        return self.filter(status=ChartOfAccountStatusChoices.ACTIVE)

    def get_status_pending(self):
        return self.filter(status=ChartOfAccountStatusChoices.PENDING)
    
    def get_status_draft(self):
        return self.filter(status=ChartOfAccountStatusChoices.DRAFT)