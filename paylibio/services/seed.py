"""What a company's library starts with (spec §3.2, §3.5), seeded on first use.

Components: the salary module's lines (BASIC, HRA, MED, CONV, DA, FOOD,
OTHER) and the spec's attendance bonus, night shift, overtime, provident fund
and advance recovery. Flags are the canonical eight; only BASIC carries the
statutory five, and ATTB and NIGHT do not prorate -- they are earned by a
condition, not by days.

Templates: the company's officer, worker and staff splits as rows, and RMG
as the gazette template -- basic-up, its figures from the rule book.
GL accounts are matched to the company's own chart of accounts by title,
where one exists; the rest stay unmapped, which blocks the journal until
someone maps them.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction

SEED_FROM = date(2000, 1, 1)

BLA = "Bangladesh Labour Act 2006"
# code, name, name_bn, kind, calc_basis, expression, flags (taxable, pf, ot, gratuity, festival, prorate, wages,
# perquisite), gl (code, title, kind), statutory basis, locked flags, frozen
ALL = ("in_taxable_income", "in_pf_base", "in_ot_base_s108", "in_gratuity_base", "in_festival_base",
       "prorate_part_month", "in_wages_base", "in_perquisite_ceiling")


def _flags(*on):
    return {f: f in on for f in ALL}


ALLOWANCE = _flags("in_taxable_income", "prorate_part_month", "in_wages_base", "in_perquisite_ceiling")
COMPONENTS = [
    ("BASIC", "Basic salary", "মূল বেতন", "EARNING", "PCT_OF_GROSS", "",
     _flags("in_taxable_income", "in_pf_base", "in_ot_base_s108", "in_gratuity_base", "in_festival_base",
            "prorate_part_month", "in_wages_base"),
     ("5110", "Salaries", "EXPENSES"), f"{BLA}, s.2(45) (basic wage)",
     ["in_taxable_income", "in_pf_base", "in_ot_base_s108", "in_gratuity_base", "in_festival_base",
      "prorate_part_month"], False),
    ("HRA", "House rent allowance", "বাড়ি ভাড়া ভাতা", "EARNING", "PCT_OF_BASIC", "", ALLOWANCE,
     ("5112", "House rent", "EXPENSES"), "", [], False),
    ("MED", "Medical allowance", "চিকিৎসা ভাতা", "EARNING", "PCT_OF_GROSS", "", ALLOWANCE,
     ("5113", "Medical", "EXPENSES"), "", [], False),
    ("CONV", "Conveyance allowance", "যাতায়াত ভাতা", "EARNING", "PCT_OF_GROSS", "", ALLOWANCE,
     ("5114", "Conveyance", "EXPENSES"), "", [], False),
    # s.108: overtime is paid on basic plus dearness allowance.
    ("DA", "Dearness allowance", "মহার্ঘ ভাতা", "EARNING", "PCT_OF_GROSS", "",
     _flags("in_taxable_income", "in_ot_base_s108", "prorate_part_month", "in_wages_base", "in_perquisite_ceiling"),
     None, f"{BLA}, s.108 (overtime on basic and dearness allowance)", ["in_ot_base_s108"], False),
    ("FOOD", "Food allowance", "খাদ্য ভাতা", "EARNING", "FIXED", "", ALLOWANCE,
     ("5115", "Food", "EXPENSES"), "", [], False),
    ("OTHER", "Other allowance", "অন্যান্য ভাতা", "EARNING", "FIXED", "", ALLOWANCE, None, "", [], False),
    ("ATTB", "Attendance bonus", "উপস্থিতি বোনাস", "EARNING", "FIXED", "",
     _flags("in_taxable_income", "in_wages_base"), ("5116", "Attendance bonus", "EXPENSES"), "", [], False),
    ("NIGHT", "Night shift allowance", "নৈশ ভাতা", "EARNING", "PER_SHIFT", "",
     _flags("in_taxable_income", "in_wages_base"), None, "", [], False),
    ("OT", "Overtime", "অতিরিক্ত সময়", "EARNING", "DERIVED", "Basic ÷ 208 × 2",
     _flags("in_taxable_income", "in_wages_base"), ("5120", "Overtime", "EXPENSES"), f"{BLA}, s.108",
     ["in_taxable_income"], False),
    ("PFE", "Provident fund — employee", "ভবিষ্য তহবিল", "DEDUCTION", "PCT_OF_BASIC", "", _flags(),
     ("2130", "PF payable", "LIABILITIES"), f"{BLA}, s.264", [], True),
    ("ADV", "Advance recovery", "অগ্রিম কর্তন", "DEDUCTION", "FIXED", "", _flags(),
     ("1310", "Employee advances", "ASSETS"), "", [], False),
]
# An employee advance is an ASSET, not an expense: the company is owed the money.
GL_ACCOUNTS = {c[0]: c[7] for c in COMPONENTS if c[7]}

TEMPLATES = (
    {"code": "officer", "name": "Officer grade template", "rows": [("BASIC", "PCT_OF_GROSS", "60"),
     ("HRA", "PCT_OF_BASIC", "50"), ("MED", "PCT_OF_GROSS", "6"), ("CONV", "PCT_OF_GROSS", "4")],
     "balancing": "BASIC", "order": 1,
     "note": "Officers and above. The default for anyone outside a gazetted worker grade. Allocates all of gross; "
             "basic absorbs the rounding."},
    {"code": "worker", "name": "Worker grade template", "rows": [("BASIC", "PCT_OF_GROSS", "55"),
     ("HRA", "PCT_OF_BASIC", "50"), ("MED", "PCT_OF_GROSS", "8"), ("CONV", "PCT_OF_GROSS", "5")],
     "balancing": "OTHER", "order": 2,
     "note": "Gazetted worker grades. Basic is held at 55%, which needs a higher gross to clear the same grade "
             "floor; the 4.5% of gross the split leaves is paid as Other allowance."},
    {"code": "staff", "name": "Staff grade template", "rows": [("BASIC", "PCT_OF_GROSS", "58"),
     ("HRA", "PCT_OF_BASIC", "50"), ("MED", "PCT_OF_GROSS", "7"), ("CONV", "PCT_OF_GROSS", "5")],
     "balancing": "OTHER", "order": 3,
     "note": "Supervisory and administrative staff. The 1% of gross the split leaves is paid as Other allowance."},
)
RMG = {"code": "rmg", "name": "RMG gazette grade template", "order": 9,
       "note": "The gazetted RMG grade wage: basic from the grade, the gazette's allowances on top. Builds up from "
               "basic, so gross is the output — forcing it gross-down back-solves a gross and the rounding lands a "
               "few taka under the floor."}


def match_account(company, code):
    """The company's own account for a component, by its seeded title."""
    from accounts.models import ChartOfAccount

    spec = GL_ACCOUNTS.get(code)
    if not spec:
        return None
    return (ChartOfAccount.objects.filter(company=company, title__iexact=spec[1]).exclude(status="REMOVED").first()
            or ChartOfAccount.objects.filter(company=company, code=spec[0]).exclude(status="REMOVED").first())


def ensure_components(company):
    from ..models import PayComponent

    have = set(PayComponent.objects.filter(company=company).values_list("code", flat=True))
    with transaction.atomic():
        for order, (code, name, bn, kind, basis, expr, flags, _gl, basis_text, locked, frozen) in enumerate(COMPONENTS):
            if code in have:
                continue
            PayComponent.objects.create(
                company=company, code=code, version=1, name=name, name_bn=bn, kind=kind, calc_basis=basis,
                calc_expression=expr, gl_account=match_account(company, code), is_statutory=bool(basis_text),
                statutory_basis=basis_text, locked_flags=locked, flags_frozen=frozen, display_order=order + 1,
                effective_from=SEED_FROM, **flags)


def ensure_templates(company):
    from ..models import StructureTemplate, StructureTemplateRow

    have = set(StructureTemplate.objects.filter(company=company).values_list("code", flat=True))
    with transaction.atomic():
        for t in TEMPLATES:
            if t["code"] in have:
                continue
            row = StructureTemplate.objects.create(
                company=company, code=t["code"], version=1, name=t["name"], mode="GROSS_DOWN", note=t["note"],
                balancing_code=t["balancing"], status="PUBLISHED", display_order=t["order"], effective_from=SEED_FROM)
            for i, (code, basis, value) in enumerate(t["rows"]):
                StructureTemplateRow.objects.create(template=row, component_code=code, basis=basis,
                                                    value=Decimal(value), display_order=i)
        if RMG["code"] not in have:
            StructureTemplate.objects.create(
                company=company, code=RMG["code"], version=1, name=RMG["name"], mode="BASIC_UP", note=RMG["note"],
                balancing_code="BASIC", gazette=True, status="PUBLISHED", display_order=RMG["order"],
                effective_from=SEED_FROM)


def ensure_policy(company):
    from ..models import PayrollPolicy

    return PayrollPolicy.objects.get_or_create(company=company)[0]


def ensure_library(company):
    ensure_components(company)
    ensure_templates(company)
    ensure_policy(company)
