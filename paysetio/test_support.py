"""Test helpers for payroll settings. Nothing here is imported by production code."""

from datetime import date

from .choices import ELECTIONS, SCHEMES
from .models import PayrollElection, StatutoryScheme

LONG_AGO = date(2000, 1, 1)
# What the system applied before the elections existed, so the older suites
# keep computing the figures they were written against.
LEGACY = {"overtime_base": "BASIC_PLUS_DA", "proration_method": "CALENDAR_DAYS", "gratuity_basis": "BASIC",
          "festival_bonus_policy": "NONE"}


def _labour():
    from rulebookio.models import RuleSet

    return RuleSet.objects.filter(family="LABOUR", status="PUBLISHED").order_by("effective_from").first()


def answer_elections(company, on=LONG_AGO, skip=(), **values):
    """Every election answered from `on`; `values` override the legacy
    answers (a value, or a (value, json) pair); `skip` leaves keys unanswered."""
    from .services.ops import default_config

    labour = _labour()
    for key, meta in ELECTIONS.items():
        if key in skip or PayrollElection.objects.filter(company=company, election_key=key).exists():
            continue
        v = values.get(key, LEGACY.get(key, meta["preset"]))
        text, js = (v if isinstance(v, tuple) else ((None, v) if isinstance(v, dict) else (v, None)))
        PayrollElection.objects.create(company=company, election_key=key, value_text=text, value_json=js,
                                       statutory_citation=f"cite {key}", rule_set=labour, effective_from=on)
    for code in SCHEMES:
        if not StatutoryScheme.objects.filter(company=company, scheme_code=code).exists():
            StatutoryScheme.objects.create(company=company, scheme_code=code, applies=code == "GRATUITY",
                                           statutory_citation=code, config_json=default_config(code),
                                           effective_from=on)


def constitute_pf(company, on=LONG_AGO, **config):
    from .services.ops import default_config

    StatutoryScheme.objects.filter(company=company, scheme_code="PF").delete()
    StatutoryScheme.objects.create(company=company, scheme_code="PF", applies=True, statutory_citation="s.264",
                                   config_json={**default_config("PF"), "constituted": True,
                                                "constitutionDate": on.isoformat(), "eligibility": "ON_JOINING",
                                                **config}, effective_from=on)


def join(employee, code, on=LONG_AGO, **rates):
    from .models import SchemeParticipation

    return SchemeParticipation.objects.create(company=employee.company, employee=employee, scheme_code=code,
                                              enrolled_on=on, **rates)


def set_election(company, key, value=None, data=None, on=LONG_AGO, site=None, hours=None):
    """Replace what governs `key` from `on` -- a test shortcut past approval."""
    for row in PayrollElection.objects.filter(company=company, election_key=key, site=site,
                                              status__in=("ACTIVE", "SUPERSEDED")):
        if row.effective_from >= on:
            row.status = "REJECTED"
        else:
            from datetime import timedelta

            row.effective_to = on - timedelta(days=1)
            row.status = "SUPERSEDED"
        row.save()
    return PayrollElection.objects.create(company=company, site=site, election_key=key, value_text=value,
                                          value_json=data, standard_month_hours=hours,
                                          statutory_citation=f"cite {key}", rule_set=_labour(), effective_from=on)


class FakeCalendar:
    """Working days on a fixed weekly pattern (ISO weekdays off)."""

    def __init__(self, off=(5,)):
        self.off = set(off)

    def working(self, d):
        return d.isoweekday() not in self.off

    def working_days(self, first, last):
        from datetime import timedelta

        n, d = 0, first
        while d <= last:
            n += self.working(d)
            d += timedelta(days=1)
        return n
