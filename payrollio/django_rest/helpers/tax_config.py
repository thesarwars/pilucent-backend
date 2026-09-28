"""Resolve and assemble statutory payroll tax config.

Storage is one ``PayrollTaxConfig`` row per ``(year, jurisdiction)`` — a shared
FEDERAL row plus one row per state. A read request names a set of states; this
module fetches FEDERAL + those states and assembles them back into the single
``CONFIG``-shaped document the frontend calculators read (``{federal, ny, ca}``).

Federal is always included (every state calculation needs it) and stored once
per year, never duplicated into state rows. States requested but not yet
published come back in an ``unavailable`` list — the seam between "payroll runs
for all states" and "every state has statutory tables".
"""

from datetime import date

from payrollio.choicess import PayrollTaxConfigStatusChoices
from payrollio.models import FEDERAL_JURISDICTION, PayrollTaxConfig
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    US_STATE_CODES,
    normalize_us_state,
)

VALID_JURISDICTIONS = frozenset({FEDERAL_JURISDICTION}) | US_STATE_CODES


def normalize_jurisdiction(value):
    """FEDERAL (any case) or a valid USPS/full-name state code, else None."""
    if not value:
        return None
    if str(value).strip().upper() == FEDERAL_JURISDICTION:
        return FEDERAL_JURISDICTION
    return normalize_us_state(value)


def parse_states_param(states_param):
    """Turn a ``?states=CA,NY,New York`` value into a normalized set of codes.

    Unrecognized tokens are dropped (never FEDERAL — that's added separately).
    """
    if not states_param:
        return set()
    codes = set()
    for token in str(states_param).split(","):
        code = normalize_us_state(token)
        if code:
            codes.add(code)
    return codes


def resolve_year(year_param):
    """Resolve a year path segment; 'current' / None -> current calendar year."""
    if year_param is None or str(year_param).lower() == "current":
        return date.today().year
    return int(year_param)


def assemble_tax_config(year, state_codes):
    """Assemble the FEDERAL + requested-state published config for ``year``.

    Returns a dict with the CONFIG-shaped ``data`` (keys lowercased: federal,
    ny, ca…), the per-jurisdiction ``versions``, and any ``unavailable``
    jurisdictions (requested but not published for this year).
    """
    requested = {FEDERAL_JURISDICTION} | set(state_codes)
    rows = PayrollTaxConfig.objects.filter(
        year=year,
        status=PayrollTaxConfigStatusChoices.PUBLISHED,
        jurisdiction__in=requested,
    )

    data = {"year": year}
    versions = {}
    found = set()
    for row in rows:
        data[row.jurisdiction.lower()] = row.data
        versions[row.jurisdiction] = row.version
        found.add(row.jurisdiction)

    unavailable = sorted(requested - found)
    return {"year": year, "versions": versions, "unavailable": unavailable, "data": data}
