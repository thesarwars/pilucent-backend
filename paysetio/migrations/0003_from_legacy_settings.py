"""Carry the old settings over (§10), before employeeio 0011 drops them.

- The four elections without a default are NOT carried: the old columns held
  defaults nobody chose (calendar-actual proration, a basic + DA overtime
  base), and the honest state of a migrated company is unanswered (§10.1).
- The three presets are seeded, from the company's start (§10.5: never
  backfilled to anyone's joining date). Days worked carries the company's own
  three flags, which the attendance screen let it set.
- The schemes take the company's flags and rates; participation comes from
  each employee's own record, never inferred from a company flag (§10.3).
- GL mapping is left for later: the journal stays blocked until it is done,
  which is correct (§10.4).
"""

from datetime import date
from decimal import Decimal

from django.db import migrations

PRESET_REASON = "Preset: the value the system applied before payroll settings existed."
CITE = {"days_worked_basis": ("earnedLeave", ""),
        "rounding_mode": ("wagePayment", " — wages payable without unauthorised deduction"),
        "balancing_component": ("wagePayment", "")}
SCHEME_CITE = {"PF": "pf", "GRATUITY": "gratuity", "GROUP_INSURANCE": "insurance", "WPPF": "wppf"}


def _pct4(v):
    return f"{Decimal(str(v)).quantize(Decimal('0.0001'))}"


def forwards(apps, schema_editor):
    Company = apps.get_model("companyio", "Company")
    Site = apps.get_model("employeeio", "Site")
    Profile = apps.get_model("employeeio", "CompanyStatutoryProfile")
    Statutory = apps.get_model("employeeio", "EmployeeStatutory")
    RuleSet = apps.get_model("rulebookio", "RuleSet")
    Election = apps.get_model("paysetio", "PayrollElection")
    Scheme = apps.get_model("paysetio", "StatutoryScheme")
    Participation = apps.get_model("paysetio", "SchemeParticipation")
    try:
        Policy = apps.get_model("paylibio", "PayrollPolicy")
    except LookupError:
        Policy = None

    today = date.today()
    labour = (RuleSet.objects.filter(jurisdiction="BD", family="LABOUR", status="PUBLISHED", effective_from__lte=today)
              .order_by("-effective_from").first())
    cites = (labour.data or {}).get("citations", {}) if labour else {}
    companies = set(Site.objects.values_list("company_id", flat=True)) | set(Profile.objects.values_list("company_id", flat=True))
    for company in Company.objects.filter(pk__in=companies):
        start = company.created_at.date() if getattr(company, "created_at", None) else today
        p = Profile.objects.filter(company=company).first()
        policy = Policy.objects.filter(company=company).first() if Policy else None
        if labour is not None:
            presets = {
                "days_worked_basis": (None, {"present": True, "paidLeave": bool(p and p.days_worked_paid_leave),
                                             "festival": bool(p and p.days_worked_festival),
                                             "weekly": bool(p and p.days_worked_weekly), "maternity": False}),
                "rounding_mode": ("TAKA", None),
                "balancing_component": ("BASIC", None),
            }
            for key, (text, js) in presets.items():
                if Election.objects.filter(company=company, site__isnull=True, election_key=key).exists():
                    continue
                name, suffix = CITE[key]
                Election.objects.create(company=company, election_key=key, value_text=text, value_json=js,
                                        statutory_citation=(cites.get(name) or key) + (suffix if cites.get(name) else ""),
                                        rule_set=labour, effective_from=start, source="SEEDED", reason=PRESET_REASON)

        statutory = list(Statutory.objects.filter(employee__company=company).select_related("employee"))
        insured = [s for s in statutory if s.insurance_covered]
        pf_emp = policy.pf_rate_employee * 100 if policy else Decimal("8")
        pf_er = (policy.pf_rate_employer * 100 if policy else (p.pf_employer_rate if p else Decimal("8")))
        configs = {
            "PF": (bool(p and p.pf_constituted), {
                "constituted": bool(p and p.pf_constituted), "constitutionDate": None,
                "employeeRatePct": _pct4(pf_emp), "employerRatePct": _pct4(pf_er), "eligibility": "ON_CONFIRMATION",
                "eligibilityMonths": None, "autoEnrol": False, "trustDeedRef": None}),
            "GRATUITY": (True, {"method": "MONTHLY_PROVISION", "fundName": None, "minServiceYears": 1}),
            "GROUP_INSURANCE": (bool(insured), {
                "inForce": bool(insured), "insurer": next((s.insurer for s in insured if s.insurer), None),
                "policyNo": next((s.insurance_policy for s in insured if s.insurance_policy), None),
                "renewalDate": None, "coverage": "ALL_WORKERS", "sumAssured": None,
                "premiumMonthly": _pct4(p.insurance_premium_monthly if p else Decimal("148"))}),
            "WPPF": (False, {"eligibilityMonths": 6, "profitSharePct": "5.0000",
                             "distributionSplit": {"workers": 80, "welfareFund": 10, "govtFund": 10}}),
        }
        for code, (applies, config) in configs.items():
            if Scheme.objects.filter(company=company, scheme_code=code).exists():
                continue
            Scheme.objects.create(company=company, scheme_code=code, applies=applies, config_json=config,
                                  statutory_citation=cites.get(SCHEME_CITE[code]) or code, effective_from=start,
                                  reason="Carried over from the employee profile settings")
        for s in statutory:
            e = s.employee
            joined = e.doj or start
            for code, on, when in (("PF", s.pf_member, s.pf_enrolled or joined),
                                   ("GRATUITY", s.gratuity_eligible, joined),
                                   ("GROUP_INSURANCE", s.insurance_covered, joined)):
                if on and not Participation.objects.filter(employee=e, scheme_code=code).exists():
                    Participation.objects.create(
                        company=company, employee=e, scheme_code=code, enrolled_on=when,
                        override_rate_pct=s.pf_employee if code == "PF" else None,
                        override_employer_rate_pct=s.pf_employer if code == "PF" else None)


class Migration(migrations.Migration):

    dependencies = [
        ("paysetio", "0002_permissions_guards"),
        ("paylibio", "0003_da_in_overtime_base"),
        ("employeeio", "0010_pay_library_cleanup"),
        ("rulebookio", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
