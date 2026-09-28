"""
QuickBooks-style rules for federal tax deposit schedule settings.

Supported forms (``PayrollFederalTaxInfoTaxFormChoices``):
- **Form 941** — quarterly return; monthly / quarterly / semi-weekly deposit schedules.
- **Form 943** — annual agricultural return; deposit schedule can be semi-weekly, monthly,
  quarterly, or annual (IRS Pub. 15-A).
- **Form 944** — annual return for qualifying small employers; annual deposits only.

**Not full IRS lookback logic** — this module stores schedule *history* (effective dates,
upsert by form + date). IRS assignment of monthly vs semi-weekly is based on liability
lookback, not implemented here.

Per-form effective-date normalization:
- **941**: monthly Jan–Mar → Apr 1; quarterly → quarter start; semi-weekly unchanged.
- **943 / 944**: any frequency → **Jan 1** of the requested calendar year (one upsert
  slot per year; changing frequency on ``01-01-2025`` replaces the existing row).
- **944**: effective date always **Jan 1**; deposit frequencies match QuickBooks (monthly, etc.).
"""

from datetime import date

from rest_framework.exceptions import ValidationError

from payrollio.choicess import (
    PayrollFederalTaxInfoSettingChoices,
    PayrollFederalTaxInfoTaxFormChoices,
)

VALID_PAYMENT_FREQUENCIES = {
    choice for choice, _ in PayrollFederalTaxInfoSettingChoices.choices
}

VALID_TAX_FORMS = {choice for choice, _ in PayrollFederalTaxInfoTaxFormChoices.choices}

# Common API / UI typos → canonical ``PayrollFederalTaxInfoTaxFormChoices`` values.
TAX_FORM_ALIASES = {
    "FORM_941_EACH_YEAR": PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
    "FORM_941": PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
    "FORM_943": PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
    "FORM_944": PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR,
}

MAX_FEDERAL_TAX_SCHEDULE_ITEMS = 4  # QuickBooks shows at most four schedule rows

MONTHLY_START_MONTHS = (4, 7, 10)

FREQUENCY_ALIASES = {
    "MONTHLY": PayrollFederalTaxInfoSettingChoices.MONTHLY,
    "QUARTERLY": PayrollFederalTaxInfoSettingChoices.QUARTERLY,
    "QUATERLY": PayrollFederalTaxInfoSettingChoices.QUARTERLY,
    "SEMI_WEEKLY": PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
    "SEMI-WEEKLY": PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
    "SEMI WEEKLY": PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
    "SEMIWEEKLY": PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY,
    "ANNUALLY": PayrollFederalTaxInfoSettingChoices.ANNUALLY,
    "ANNUAL": PayrollFederalTaxInfoSettingChoices.ANNUALLY,
}


def normalize_payment_frequency(payment_frequency):
    """Map API / UI values to ``PayrollFederalTaxInfoSettingChoices`` values."""
    if not payment_frequency:
        return payment_frequency
    key = str(payment_frequency).strip().upper().replace("-", "_")
    if key in FREQUENCY_ALIASES:
        return FREQUENCY_ALIASES[key]
    return key


def validate_payment_frequency_value(value):
    """Validate and normalize a federal tax payment frequency for API payloads."""
    normalized = normalize_payment_frequency(value)
    if normalized not in VALID_PAYMENT_FREQUENCIES:
        raise ValidationError(
            f"Invalid payment_frequency '{value}'. Expected one of: "
            f"{', '.join(sorted(VALID_PAYMENT_FREQUENCIES))}."
        )
    return normalized


def normalize_tax_form(tax_form):
    """Map API aliases to canonical federal tax form choice values."""
    if not tax_form:
        return tax_form
    key = str(tax_form).strip().upper()
    return TAX_FORM_ALIASES.get(key, key)


def validate_tax_form_value(tax_form):
    """Ensure ``tax_form`` is present and a known federal form choice."""
    if not tax_form:
        raise ValidationError({"tax_form": "This field is required."})
    tax_form = normalize_tax_form(tax_form)
    if tax_form not in VALID_TAX_FORMS:
        raise ValidationError(
            {
                "tax_form": (
                    f"Invalid tax_form '{tax_form}'. Expected one of: "
                    f"{', '.join(sorted(VALID_TAX_FORMS))}."
                )
            }
        )
    return tax_form


def validate_tax_form_payment_frequency(tax_form, payment_frequency):
    """Validate frequency is allowed for the given federal tax form."""
    tax_form = validate_tax_form_value(tax_form)
    return validate_payment_frequency_value(payment_frequency)


def _normalize_calendar_year_start(effective_date):
    """Jan 1 of the calendar year (Form 943/944 annual tax year)."""
    return date(effective_date.year, 1, 1)


def _normalize_form_941_deposit_effective_date(payment_frequency, effective_date):
    """Deposit schedule period starts for Form 941-style frequencies."""
    frequency = normalize_payment_frequency(payment_frequency)

    if frequency == PayrollFederalTaxInfoSettingChoices.MONTHLY:
        year = effective_date.year
        if effective_date.month <= 3:
            return date(year, 4, 1)
        candidates = [date(year, month, 1) for month in MONTHLY_START_MONTHS]
        candidates.append(date(year + 1, 1, 1))
        for candidate in candidates:
            if candidate >= effective_date:
                return candidate
        return date(year + 1, 1, 1)

    if frequency == PayrollFederalTaxInfoSettingChoices.QUARTERLY:
        month = effective_date.month
        if month <= 3:
            return date(effective_date.year, 1, 1)
        if month <= 6:
            return date(effective_date.year, 4, 1)
        if month <= 9:
            return date(effective_date.year, 7, 1)
        return date(effective_date.year, 10, 1)

    if frequency == PayrollFederalTaxInfoSettingChoices.ANNUALLY:
        return _normalize_calendar_year_start(effective_date)

    return effective_date


def normalize_federal_tax_effective_date(tax_form, payment_frequency, effective_date):
    """
    Align effective dates per tax form and deposit frequency (QuickBooks-style).

    Args:
        tax_form: ``PayrollFederalTaxInfoTaxFormChoices`` value.
        payment_frequency: Raw or normalized frequency string.
        effective_date: Requested effective date.

    Returns:
        Normalized date stored on ``PayrollFederalTaxInfoSettingItems``.
    """
    if not effective_date:
        return effective_date

    if tax_form in (
        PayrollFederalTaxInfoTaxFormChoices.FORM_943_EACH_YEAR,
        PayrollFederalTaxInfoTaxFormChoices.FORM_944_EACH_YEAR,
    ):
        return _normalize_calendar_year_start(effective_date)

    if tax_form == PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER:
        return _normalize_form_941_deposit_effective_date(
            payment_frequency, effective_date
        )

    return _normalize_form_941_deposit_effective_date(payment_frequency, effective_date)


def get_current_federal_tax_item(items, tax_form, *, reference_date=None):
    """Return the active schedule for ``tax_form`` (latest effective_date <= reference_date)."""
    from django.utils import timezone

    reference_date = reference_date or timezone.now().date()
    active = [
        item
        for item in items
        if item.tax_form == tax_form
        and item.effective_date
        and item.effective_date <= reference_date
    ]
    if not active:
        return None
    return max(active, key=lambda item: item.effective_date)


def _pick_schedule_to_evict(items, *, tax_form, normalized_date, reference_date=None):
    """
    Choose which schedule row to remove when at the QuickBooks four-row cap.

    Priority:
    1. Another row for the same ``tax_form`` (oldest effective date).
    2. Any row that is not the current schedule for its form (oldest effective date).
    3. Oldest effective date overall.
    """
    from django.utils import timezone

    reference_date = reference_date or timezone.now().date()

    same_form = [
        item
        for item in items
        if item.tax_form == tax_form and item.effective_date != normalized_date
    ]
    if same_form:
        return min(same_form, key=lambda item: item.effective_date or date.min)

    non_current = []
    for item in items:
        current = get_current_federal_tax_item(
            items, item.tax_form, reference_date=reference_date
        )
        if current is None or current.pk != item.pk:
            non_current.append(item)

    candidates = non_current or list(items)
    return min(
        candidates,
        key=lambda item: (item.effective_date or date.min, item.pk),
    )


def _evict_schedule_for_new_item(items_qs, *, tax_form, normalized_date):
    """Delete one schedule row so a new slot can be created (QuickBooks-style)."""
    items = list(items_qs.order_by("effective_date", "pk"))
    victim = _pick_schedule_to_evict(
        items, tax_form=tax_form, normalized_date=normalized_date
    )
    victim.delete()


def upsert_federal_tax_setting_item(
    payroll_federal_tax_info,
    *,
    tax_form,
    payment_frequency,
    effective_date,
):
    """
    Create or update a federal tax schedule line for a specific tax form.

    One row per ``tax_form`` + normalized ``effective_date``. Same slot with a
    different frequency updates the row; identical values are idempotent.

    Returns:
        tuple[item, action]: ``created``, ``updated``, or ``unchanged``.

    When four schedules already exist, the oldest non-current row (or oldest
    same-form row) is deleted automatically before creating the new one.
    """
    from django.db import transaction

    from payrollio.models import PayrollFederalTaxInfoSettingItems

    tax_form = validate_tax_form_value(tax_form)
    frequency = validate_tax_form_payment_frequency(tax_form, payment_frequency)
    normalized_date = normalize_federal_tax_effective_date(
        tax_form, frequency, effective_date
    )

    items_qs = PayrollFederalTaxInfoSettingItems.objects.filter(
        payroll_federal_tax_info=payroll_federal_tax_info,
    )

    existing = items_qs.filter(
        tax_form=tax_form,
        effective_date=normalized_date,
    ).first()

    if existing:
        if existing.payment_frequency == frequency:
            return existing, "unchanged"
        existing.payment_frequency = frequency
        existing.save(update_fields=["payment_frequency", "updated_at"])
        return existing, "updated"

    with transaction.atomic():
        if items_qs.count() >= MAX_FEDERAL_TAX_SCHEDULE_ITEMS:
            _evict_schedule_for_new_item(
                items_qs, tax_form=tax_form, normalized_date=normalized_date
            )

        item = PayrollFederalTaxInfoSettingItems.objects.create(
            payroll_federal_tax_info=payroll_federal_tax_info,
            tax_form=tax_form,
            payment_frequency=frequency,
            effective_date=normalized_date,
        )
    return item, "created"
