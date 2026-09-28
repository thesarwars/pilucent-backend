"""Registration + settings helpers for the nexus agency handoff (Phase 2).

Records a company's registration (or manual physical-nexus mark) for a state and
keeps the dashboard status row in sync. Creating the actual ``agencyio.Agency``
(which provisions Sales Tax Payable accounts and rate calculation) stays owned by
the Sales Tax module — this only stores the handoff facts and links the agency
once it exists.
"""

from django.db.models import Q

from nexusio.choices import (
    NexusRegistrationStatusChoices,
    NexusRegistrationTypeChoices,
)
from nexusio.models import NexusAgencyRegistration, NexusSettings


def registered_state_codes(company):
    """State codes the company has registered or manually marked (→ REGISTERED)."""
    return set(
        NexusAgencyRegistration.objects.filter(company=company)
        .filter(
            Q(registration_status=NexusRegistrationStatusChoices.REGISTERED)
            | Q(registration_type=NexusRegistrationTypeChoices.PHYSICAL_MANUAL)
        )
        .values_list("state_code", flat=True)
    )


def _apply(reg, *, collection_start_date, filing_frequency, permit, tax_agency):
    if collection_start_date is not None:
        reg.collection_start_date = collection_start_date
    if filing_frequency is not None:
        reg.filing_frequency = filing_frequency
    if permit is not None:
        reg.sales_tax_permit_number = permit
    if tax_agency is not None:
        reg.tax_agency = tax_agency


def mark_physical_nexus(
    company, state_code, *, collection_start_date=None, filing_frequency=None,
    permit=None, tax_agency=None,
):
    """Mark a state as having physical (manual) nexus → shows REGISTERED."""
    reg, _ = NexusAgencyRegistration.objects.get_or_create(
        company=company, state_code=state_code
    )
    reg.registration_type = NexusRegistrationTypeChoices.PHYSICAL_MANUAL
    reg.registration_status = NexusRegistrationStatusChoices.REGISTERED
    _apply(
        reg, collection_start_date=collection_start_date,
        filing_frequency=filing_frequency, permit=permit, tax_agency=tax_agency,
    )
    reg.save()
    return reg


def start_agency_setup(
    company, state_code, *, collection_start_date=None, filing_frequency=None,
    permit=None, tax_agency=None, mark_registered=False,
):
    """Record the economic-nexus registration intent (and link an agency if given)."""
    reg, _ = NexusAgencyRegistration.objects.get_or_create(
        company=company, state_code=state_code
    )
    reg.registration_type = NexusRegistrationTypeChoices.ECONOMIC
    _apply(
        reg, collection_start_date=collection_start_date,
        filing_frequency=filing_frequency, permit=permit, tax_agency=tax_agency,
    )
    # Only an explicit confirmation registers the state. Merely linking an agency
    # that happens to exist must NOT claim "registered" (it may have no rates and
    # would over-state compliance, masking a live obligation).
    if mark_registered:
        reg.registration_status = NexusRegistrationStatusChoices.REGISTERED
    reg.save()
    return reg


def remove_registration(company, state_code):
    """Delete a state's registration (de-register / un-mark)."""
    NexusAgencyRegistration.objects.filter(
        company=company, state_code=state_code
    ).delete()


def get_or_create_settings(company):
    settings, _ = NexusSettings.objects.get_or_create(company=company)
    return settings


def find_existing_agency(company, state_code, state_name=None):
    """Best-effort link to an existing Sales Tax agency for the state (free-text)."""
    from agencyio.models import Agency

    candidates = [state_code]
    if state_name:
        candidates.append(state_name)
    return (
        Agency.objects.filter(company=company, state__in=candidates).first()
        or Agency.objects.filter(company=company, state__iexact=state_code).first()
    )
