"""Salary templates (salary profile §7; components & structures §3.4-§4.3).

A template is now a row-based structure template in the pay library
(`paylibio.StructureTemplate`): each row a component with a basis -- % of
gross, % of basic, or a fixed amount. A gross-down template splits a gross;
whatever its rows leave goes to the balancing component (the rounding residue
on a split that allocates all of gross, or the unallocated share on one that
does not). A basic-up template stacks its rows on a basic, so gross is the
output. The RMG template is the gazette's, built from the rule book.

`Split` is a template's rows as the engine reads them; `build_split` the
gross-down computation. The officer, worker and staff splits behave exactly as
they did as four fixed columns.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from common.money import ZERO, round_to_taka, to_decimal

from ..choices import OverrideBasisChoices, SalaryComponentChoices

C = SalaryComponentChoices
B = OverrideBasisChoices
HUNDRED = Decimal("100")
_ONE_DP = Decimal("0.1")
# Overridden when the effective percentage is this far from the template's:
# wide enough to absorb rounding, narrow enough to catch a real deviation.
OVERRIDE_TOLERANCE = Decimal("0.5")
# Library row basis -> the salary module's override basis.
ROW_BASIS = {"PCT_OF_GROSS": B.PCT_GROSS, "PCT_OF_BASIC": B.PCT_BASIC, "FIXED": B.FIXED}


def ensure_templates(company):
    from paylibio.services.seed import ensure_library

    ensure_library(company)


def _current(company, on, code=None):
    """The published version of each template in force on `on`."""
    from paylibio.models import StructureTemplate

    ensure_templates(company)
    qs = (StructureTemplate.objects.filter(company=company, status__in=("PUBLISHED", "ARCHIVED"),
                                           effective_from__lte=on).prefetch_related("rows")
          .order_by("code", "-effective_from", "-version"))
    if code is not None:
        qs = qs.filter(code=code)
    current = {}
    for row in qs:
        current.setdefault(row.code, row)
    return current


def templates_on(company, on):
    """The company (non-gazette) templates a structure can be built on, in
    display order. An archived template still resolves a structure built on
    it, but is not offered."""
    rows = [t for t in _current(company, on).values() if not t.gazette and t.status == "PUBLISHED"]
    return sorted(rows, key=lambda r: (r.display_order, r.code))


def template_on(company, code, on):
    """The version of `code` in force on `on` (company or gazette), or None."""
    return _current(company, on, code).get(code)


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
    """A template's rows: ((code, basis, value), ...) in order, with BASIC first."""

    rows: tuple
    balancing: str
    mode: str = "GROSS_DOWN"

    @classmethod
    def of(cls, template):
        rows = sorted(template.rows.all(), key=lambda r: (r.component_code != C.BASIC, r.display_order, r.id or 0))
        return cls(tuple((r.component_code, ROW_BASIS[r.basis], to_decimal(r.value)) for r in rows),
                   template.balancing_code, template.mode)

    def row(self, code):
        return next(((b, v) for c, b, v in self.rows if c == code), None)

    def _pct(self, code, basis):
        r = self.row(code)
        return r[1] if r and r[0] == basis else ZERO

    @property
    def basic(self):  # % of gross
        return self._pct(C.BASIC, B.PCT_GROSS)

    @property
    def hr(self):  # % of BASIC
        return self._pct(C.HRA, B.PCT_BASIC)

    @property
    def med(self):
        return self._pct(C.MED, B.PCT_GROSS)

    @property
    def conv(self):
        return self._pct(C.CONV, B.PCT_GROSS)

    @property
    def has_fixed(self):
        return any(b == B.FIXED for _, b, _ in self.rows)

    @property
    def remainder(self):
        """The share of gross the rows leave, in % of gross. None when a fixed
        row makes it depend on the gross."""
        if self.has_fixed:
            return None
        of_gross = sum((v for c, b, v in self.rows if b == B.PCT_GROSS), ZERO)
        of_basic = sum((v for c, b, v in self.rows if b == B.PCT_BASIC), ZERO)
        return HUNDRED - (of_gross + self.basic * of_basic / HUNDRED)

    @property
    def notation(self):
        """'60 / 50 / 6 / 4' -- each row's figure, in order."""
        return " / ".join(pct_text(v) if b != B.FIXED else f"৳{v:,.0f}" for _, b, v in self.rows)

    def template_pct(self, code):
        """The template's percentage for a line, on the line's own base; the
        balance for the balancing Other line; None where it has none."""
        if code == C.OTHER and C.OTHER not in self.codes:
            rem = self.remainder
            return (rem if rem is not None else None) if self.balancing == C.OTHER else ZERO
        r = self.row(code)
        if r is None or r[0] == B.FIXED:
            return None
        return r[1]

    @property
    def codes(self):
        return [c for c, _, _ in self.rows]

    def default_basis(self, code):
        """How the template expresses a line (the override grid's baseline)."""
        r = self.row(code)
        return r if r is not None else (B.FIXED, ZERO)


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
    """The components of `gross` under `split` (§4.3 GROSS_DOWN), with
    `overrides` ({code: (basis, value)}) set line by line.

    Basic first; each other row on its basis; each line rounded to the taka;
    the balancing line absorbs what is left so the parts sum to gross
    exactly. With overrides the balancing line is Other allowance, as on the
    override grid. `keep_gross=False` lets gross become the sum of the lines
    instead (the grid's "let gross change"). Raises ComponentsExceedGross
    when the lines leave the balancing line below zero.
    """
    overrides = overrides or {}
    gross = round_to_taka(gross)
    basis, value = overrides.get(C.BASIC, split.default_basis(C.BASIC))
    basic = line_amount(C.BASIC, basis, value, gross, ZERO)
    lines = {C.BASIC: basic}
    for code in split.codes:
        if code == C.BASIC:
            continue
        basis, value = overrides.get(code, split.default_basis(code))
        lines[code] = line_amount(code, basis, value, gross, basic)
    for code, (basis, value) in overrides.items():
        if code not in lines:
            lines[code] = line_amount(code, basis, value, gross, basic)
    if not keep_gross:
        return [(code, amount) for code, amount in lines.items() if amount or code != C.OTHER]
    balancing = C.OTHER if overrides else split.balancing
    if balancing == C.BASIC:
        lines[C.BASIC] = basic + gross - sum(lines.values())
    else:
        # The balancing line is the output here, whatever was typed into it.
        lines[balancing] = gross - sum(a for c, a in lines.items() if c != balancing)
    if any(a < 0 for a in lines.values()):
        raise ComponentsExceedGross(-min(a for a in lines.values()))
    return [(code, amount) for code, amount in lines.items() if amount or code == balancing]


def build_basic_up(split, basic):
    """§4.3 BASIC_UP: the rows stack on `basic`; gross is their sum -- an
    output, with no residue and no balancing line."""
    basic = round_to_taka(basic)
    lines = [(C.BASIC, basic)]
    for code, basis, value in split.rows:
        if code == C.BASIC:
            continue
        lines.append((code, line_amount(code, basis, value, ZERO, basic)))
    return [(c, a) for c, a in lines if a or c == C.BASIC]
