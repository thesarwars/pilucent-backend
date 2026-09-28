import logging

from django.db import transaction

from payrollio.choicess import PayrollWorkLocationChoices
from payrollio.models import (
    PayrollAccountingPreferencesSetting,
    PayrollGeneralTaxSetting,
    PayrollStateTaxInfoSetting,
    PayrollWorkLocation,
)

from .accounting_preferences_setup import (
    normalize_us_state,
    setup_payroll_accounting_preferences,
    sync_tax_liability_components,
)

logger = logging.getLogger(__name__)


def get_primary_work_location(company):
    return PayrollWorkLocation.objects.filter(
        company=company,
        is_primary=True,
    ).exclude(status=PayrollWorkLocationChoices.REMOVED).first()


def ensure_state_tax_info_setting(company, state, *, created_by=None):
    # normalize_us_state validates against the full USPS code list, so any
    # recognized state gets its tax-info row; garbage stays out.
    normalized_state = normalize_us_state(state)
    if not normalized_state:
        return None

    state_tax_setting, _created = PayrollStateTaxInfoSetting.objects.get_or_create(
        company=company,
        state=normalized_state,
        defaults={"created_by": created_by},
    )
    return state_tax_setting


@transaction.atomic
def sync_primary_work_location_from_general_tax_setting(general_tax_setting):
    company = general_tax_setting.company
    normalized_state = normalize_us_state(general_tax_setting.state)
    primary_work_location = get_primary_work_location(company)

    location_fields = {
        "location_address": general_tax_setting.address,
        "location_city": general_tax_setting.city,
        "location_state": normalized_state or general_tax_setting.state,
        "location_zip": general_tax_setting.zip_code,
    }

    if primary_work_location:
        updated_fields = []
        for field, value in location_fields.items():
            if value and getattr(primary_work_location, field) != value:
                setattr(primary_work_location, field, value)
                updated_fields.append(field)
        if updated_fields:
            primary_work_location.save(update_fields=updated_fields)
        return primary_work_location

    return PayrollWorkLocation.objects.create(
        company=company,
        created_by=general_tax_setting.created_by,
        status=PayrollWorkLocationChoices.ACTIVE,
        is_primary=True,
        **location_fields,
    )


@transaction.atomic
def on_primary_work_location_created(work_location):
    if not work_location.is_primary:
        return None

    company = work_location.company
    raw_state = work_location.location_state
    if not raw_state:
        logger.warning(
            "Primary work location %s has no state; skipping payroll onboarding",
            work_location.uid,
        )
        return None

    state = normalize_us_state(raw_state)
    if not state:
        # Unrecognized value (typo, territory, "N.Y."-style formatting): still
        # onboard with the federal components so payroll can post; state
        # components can be synced later once the location is corrected.
        logger.warning(
            "Primary work location %s has unrecognized state %r; "
            "proceeding with federal-only payroll onboarding",
            work_location.uid,
            raw_state,
        )

    ensure_state_tax_info_setting(
        company,
        state,
        created_by=work_location.created_by,
    )

    if PayrollAccountingPreferencesSetting.objects.filter(company=company).exists():
        settings = PayrollAccountingPreferencesSetting.objects.filter(
            company=company
        ).first()
        sync_tax_liability_components(
            settings,
            company,
            state,
            include_federal=True,
        )
        return settings

    return setup_payroll_accounting_preferences(
        company,
        state=state,
        created_by=work_location.created_by,
    )


@transaction.atomic
def on_manual_work_location_created(work_location):
    if work_location.is_primary:
        return on_primary_work_location_created(work_location)

    company = work_location.company
    state = normalize_us_state(work_location.location_state)
    if not state:
        return None

    ensure_state_tax_info_setting(
        company,
        state,
        created_by=work_location.created_by,
    )

    settings = PayrollAccountingPreferencesSetting.objects.filter(
        company=company
    ).first()
    if not settings:
        logger.info(
            "Accounting preferences missing for company %s; "
            "manual work location %s did not sync tax liabilities",
            company.uid,
            work_location.uid,
        )
        return None

    sync_tax_liability_components(
        settings,
        company,
        state,
        include_federal=False,
    )
    return settings


@transaction.atomic
def on_general_tax_setting_saved(general_tax_setting):
    primary_work_location = sync_primary_work_location_from_general_tax_setting(
        general_tax_setting
    )
    if not primary_work_location:
        return None

    if not PayrollAccountingPreferencesSetting.objects.filter(
        company=general_tax_setting.company
    ).exists():
        return on_primary_work_location_created(primary_work_location)

    state = normalize_us_state(primary_work_location.location_state)
    if state:
        ensure_state_tax_info_setting(
            general_tax_setting.company,
            state,
            created_by=general_tax_setting.created_by,
        )
    return PayrollAccountingPreferencesSetting.objects.filter(
        company=general_tax_setting.company
    ).first()


def route_work_location_onboarding(work_location, *, created=False):
    if work_location.status == PayrollWorkLocationChoices.REMOVED:
        return None

    if not created:
        return None

    if work_location.is_primary:
        if PayrollAccountingPreferencesSetting.objects.filter(
            company=work_location.company
        ).exists():
            return on_manual_work_location_created(work_location)
        return on_primary_work_location_created(work_location)

    return on_manual_work_location_created(work_location)
