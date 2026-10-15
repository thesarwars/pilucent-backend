"""Salary templates (salary profile §7; backend §3.1, §4.1, §4.2).

A template is a split of gross: basic as a percentage of gross, house rent as
a percentage of BASIC, medical and conveyance of gross. Whatever the four
leave of gross goes to the template's balancing component -- the rounding
residue on a split that allocates all of gross (officer, balanced on basic),
or the unallocated share on one that does not (worker 95.5%, staff 99%, which
balance on Other allowance so basic stays at its percentage).

Templates are rows per company, versioned by `effective_from`, seeded on
first use. Management (65/50/5/3) allocates 105.5% of gross and is left out
of the seed until its split is settled.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from common.money import ZERO, round_to_taka, to_decimal

from ..choices import OverrideBasisChoices, SalaryComponentChoices
from ..models import SalaryTemplate

C = SalaryComponentChoices
B = OverrideBasisChoices
HUNDRED = Decimal("100")
_ONE_DP = Decimal("0.1")
# Overridden when the effective percentage is this far from the template's:
# wide enough to absorb rounding, narrow enough to catch a real deviation.
OVERRIDE_TOLERANCE = Decimal("0.5")

# Before any structure: a template has to be in force on the oldest joining date.
SEED_FROM = date(2000, 1, 1)
SEED = (
    {"code": "officer", "label": "Officer grade template", "basic": "60", "hr": "50", "med": "6", "conv": "4",
     "balancing": C.BASIC, "order": 1,
     "note": "Officers and above. The default for anyone outside a gazetted worker grade. Allocates all of gross; "
             "basic absorbs the rounding."},
    {"code": "worker", "label": "Worker grade template", "basic": "55", "hr": "50", "med": "8", "conv": "5",
     "balancing": C.OTHER, "order": 2,
     "note": "Gazetted worker grades. Basic is held at 55%, which needs a higher gross to clear the same grade "
             "floor; the 4.5% of gross the split leaves is paid as Other allowance."},
    {"code": "staff", "label": "Staff grade template", "basic": "58", "hr": "50", "med": "7", "conv": "5",
     "balancing": C.OTHER, "order": 3,
     "note": "Supervisory and administrative staff. The 1% of gross the split leaves is paid as Other allowance."},
)


def ensure_templates(company):
    """Seed the company's templates the first time they are needed. A code
    that already has any version is left alone -- a company that revised its
    officer split keeps its own."""
    have = set(SalaryTemplate.objects.filter(company=company).values_list("code", flat=True))
    missing = [s for s in SEED if s["code"] not in have]
    if not missing:
        return
    with transaction.atomic():
        for s in missing:
            SalaryTemplate.objects.get_or_create(
                company=company, code=s["code"], effective_from=SEED_FROM,
                defaults={
                    "label": s["label"], "note": s["note"], "basic_pct": Decimal(s["basic"]),
                    "hr_pct_of_basic": Decimal(s["hr"]), "med_pct": Decimal(s["med"]),
                    "conv_pct": Decimal(s["conv"]), "balancing_component": s["balancing"],
                    "display_order": s["order"],
                },
            )


def templates_on(company, on):
    """The version of each active template in force on `on`, in display order."""
    ensure_templates(company)
    rows = SalaryTemplate.objects.filter(company=company, is_active=True, effective_from__lte=on).order_by(
        "code", "-effective_from")
    current = {}
    for row in rows:
        current.setdefault(row.code, row)
    return sorted(current.values(), key=lambda r: (r.display_order, r.code))


def template_on(company, code, on):
    ensure_templates(company)
    return (SalaryTemplate.objects.filter(company=company, code=code, is_active=True, effective_from__lte=on)
            .order_by("-effective_from").first())


# ------------------------------------------------------------------- splits


def pct(amount, whole):
    """amount ÷ whole × 100, to one decimal (§4.2)."""
    if not whole:
        return None
    return (to_decimal(amount) * HUNDRED / to_decimal(whole)).quantize(_ONE_DP, rounding=ROUND_HALF_UP)


def pct_text(value):
    """60 -> "60", 58.60 -> "58.6"."""
    text = f"{to_decimal(value).quantize(_ONE_DP, rounding=ROUND_HALF_UP):f}"
    return text[:-2] if text.endswith(".0") else text


@dataclass(frozen=True)
class Split:
    basic: Decimal  # % of gross
    hr: Decimal  # % of BASIC
    med: Decimal  # % of gross
    conv: Decimal  # % of gross
    balancing: str

    @classmethod
    def of(cls, row):
        return cls(row.basic_pct, row.hr_pct_of_basic, row.med_pct, row.conv_pct, row.balancing_component)

    @property
    def remainder(self):
        """The share of gross the four leave, in % of gross."""
        return HUNDRED - (self.basic + self.med + self.conv + self.basic * self.hr / HUNDRED)

    @property
    def notation(self):
        return " / ".join(pct_text(x) for x in (self.basic, self.hr, self.med, self.conv))

    def template_pct(self, code):
        """The template's percentage for a line, on the line's own base."""
        return {
            C.BASIC: self.basic, C.HRA: self.hr, C.MED: self.med, C.CONV: self.conv,
            C.OTHER: self.remainder if self.balancing == C.OTHER else ZERO,
        }.get(code)

    def default_basis(self, code):
        """How the template expresses a line (the override grid's baseline)."""
        if code == C.HRA:
            return B.PCT_BASIC, self.hr
        if code == C.OTHER:
            return B.FIXED, ZERO
        return B.PCT_GROSS, self.template_pct(code)


class ComponentsExceedGross(ValueError):
    def __init__(self, excess):
        self.excess = excess
        super().__init__(f"Components exceed gross by {excess}.")


def line_amount(code, basis, value, gross, basic):
    v = to_decimal(value)
    if basis == B.FIXED:
        return round_to_taka(v)
    if basis == B.PCT_BASIC:
        return round_to_taka(basic * v / HUNDRED)
    return round_to_taka(gross * v / HUNDRED)


def build_split(split, gross, overrides=None, keep_gross=True):
    """The components of `gross` under `split` (§4.1), with `overrides`
    ({code: (basis, value)}) set line by line.

    Each line is rounded to the taka; the balancing line absorbs what is left
    so the parts sum to gross exactly. With overrides the balancing line is
    Other allowance, as on the override grid. `keep_gross=False` lets gross
    become the sum of the lines instead (the grid's "let gross change").
    Raises ComponentsExceedGross when the lines leave the balancing line
    below zero.
    """
    overrides = overrides or {}
    gross = round_to_taka(gross)
    basis, value = overrides.get(C.BASIC, (B.PCT_GROSS, split.basic))
    basic = line_amount(C.BASIC, basis, value, gross, ZERO)
    lines = {C.BASIC: basic}
    for code in (C.HRA, C.MED, C.CONV):
        basis, value = overrides.get(code, split.default_basis(code))
        lines[code] = line_amount(code, basis, value, gross, basic)
    if C.OTHER in overrides:
        basis, value = overrides[C.OTHER]
        lines[C.OTHER] = line_amount(C.OTHER, basis, value, gross, basic)
    if not keep_gross:
        return [(code, amount) for code, amount in lines.items() if amount or code != C.OTHER]
    balancing = C.OTHER if overrides else split.balancing
    if balancing == C.BASIC:
        lines[C.BASIC] = basic + gross - sum(lines.values())
    else:
        # The balancing line is the output here, whatever was typed into it.
        lines[C.OTHER] = gross - sum(a for c, a in lines.items() if c != C.OTHER)
    if any(a < 0 for a in lines.values()):
        raise ComponentsExceedGross(-min(a for a in lines.values()))
    return [(code, amount) for code, amount in lines.items() if amount or code == balancing]
