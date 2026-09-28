from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from companyio.models import CompanyUser

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    normalize_us_state,
    resolve_state_from_general_tax_setting,
    setup_payroll_accounting_preferences,
)
from payrollio.django_rest.helpers.payroll_onboarding import (
    get_primary_work_location,
    on_general_tax_setting_saved,
    on_manual_work_location_created,
    on_primary_work_location_created,
)
from payrollio.models import (
    PayrollAccountingPreferencesSetting,
    PayrollGeneralTaxSetting,
    PayrollWorkLocation,
)


class Command(BaseCommand):
    help = (
        "Ensure payroll work location and default accounting preferences exist "
        "for a company (state tax components for any US state; NY/MN keep "
        "their bespoke component sets)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=True,
            help="User email whose active company should be configured.",
        )
        parser.add_argument(
            "--state",
            help="Override state code (e.g. NY, MN). Defaults to general tax setting state.",
        )

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(email=options["email"]).first()
        if not user:
            raise CommandError(f"No user found for email {options['email']!r}")

        company_user = (
            CompanyUser.objects.filter(user=user).select_related("company").first()
        )
        if not company_user:
            raise CommandError(f"No company found for user {options['email']!r}")

        company = company_user.company
        state = normalize_us_state(options.get("state")) or resolve_state_from_general_tax_setting(
            company
        )

        general_tax_setting = PayrollGeneralTaxSetting.objects.filter(
            company=company
        ).first()
        if general_tax_setting:
            on_general_tax_setting_saved(general_tax_setting)
        elif not state:
            raise CommandError(
                "No general tax setting found. Pass --state or create general tax setting first."
            )

        work_location = get_primary_work_location(company)
        if not work_location:
            work_location = PayrollWorkLocation.objects.filter(company=company).first()

        if work_location and not state:
            state = normalize_us_state(work_location.location_state)

        if not work_location:
            raise CommandError(
                "No work location exists. Create a PayrollGeneralTaxSetting first."
            )

        settings = PayrollAccountingPreferencesSetting.objects.filter(
            company=company
        ).first()
        if not settings:
            if work_location.is_primary:
                settings = on_primary_work_location_created(work_location)
            else:
                settings = setup_payroll_accounting_preferences(
                    company,
                    state=state,
                    created_by=work_location.created_by,
                )
        elif state:
            on_manual_work_location_created(work_location)

        if not settings:
            raise CommandError(
                "Payroll accounting preferences were not created. "
                "Confirm chart of accounts exist for this company."
            )

        components = settings.expense_accounts.filter(
            payroll_accounting_preferences_type=settings.tax_liability_expense_type
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Company {company.name!r} ({company.kind}): "
                f"work_location_state={work_location.location_state!r}, "
                f"is_primary={work_location.is_primary}, "
                f"preferences_uid={settings.uid}, "
                f"tax_liability_components={components.count()}"
            )
        )
        for component in components:
            self.stdout.write(
                f"  - {component.account_type} -> "
                f"{component.expense_account.title if component.expense_account else 'N/A'}"
            )
