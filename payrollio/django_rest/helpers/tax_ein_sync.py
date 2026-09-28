"""Keep federal EIN aligned on general and federal payroll tax settings."""

from django.db import transaction

from payrollio.models import PayrollFederalTaxInfoSetting, PayrollGeneralTaxSetting

FEDERAL_TAX_INFO_EIN_MAX_LENGTH = 15


def normalize_ein(ein_number):
    if ein_number is None:
        return None
    value = str(ein_number).strip()
    return value or None


def federal_ein_value(ein_number):
    """PayrollFederalTaxInfoSetting.ein_number allows max 15 characters."""
    normalized = normalize_ein(ein_number)
    if not normalized:
        return None
    return normalized[:FEDERAL_TAX_INFO_EIN_MAX_LENGTH]


@transaction.atomic
def sync_company_federal_ein(company, ein_number):
    """
    When either PayrollGeneralTaxSetting or PayrollFederalTaxInfoSetting
    EIN is created or updated, mirror the value on all settings for the company.
    """
    normalized = normalize_ein(ein_number)
    federal_value = federal_ein_value(normalized)

    for general in PayrollGeneralTaxSetting.objects.filter(company=company):
        if general.ein_number != normalized:
            general.ein_number = normalized
            general.save(update_fields=["ein_number", "updated_at"])

    for federal in PayrollFederalTaxInfoSetting.objects.filter(company=company):
        if federal.ein_number != federal_value:
            federal.ein_number = federal_value
            federal.save(update_fields=["ein_number", "updated_at"])
