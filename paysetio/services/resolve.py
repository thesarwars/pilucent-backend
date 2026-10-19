"""The election-resolution contract (§4). The only way another module reads
an election.

`elections_for(company, site, as_of)` resolves all seven: a site's own
election first, the company-wide one otherwise (§4.1, `establishment_id
NULLS LAST`). No row is UNANSWERED -- never a default.

The rest turns a resolved election into the figure it governs, so the
attendance engine, the salary module and the consequence preview compute it
the same way. The election chooses the BASE; the rule book supplies the RATE
(§4.3): the multiplier, the gratuity days and the earned-leave ratios are not
stored here.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.db.models import Q

from common import clock
from common.money import ZERO, to_decimal

from ..choices import ELECTIONS, ELECTION_KEYS
from ..models import PayrollElection

GOVERNING = ("ACTIVE", "SUPERSEDED")  # a superseded row still governs its own window
TEN = Decimal("10")
TWELVE = Decimal("12")
HUNDRED = Decimal("100")


class ElectionUnanswered(Exception):
    """An unanswered election refuses the computation it governs (§1.2)."""

    def __init__(self, key, citation=None):
        self.key = key
        self.citation = citation or ""
        meta = ELECTIONS[key]
        self.message = (f"The {meta['label'].lower()} has not been elected, so {meta['governs']} cannot be computed. "
                        f"Elect it in Payroll settings{f' ({citation})' if citation else ''}.")
        super().__init__(self.message)


@dataclass(frozen=True)
class Resolved:
    key: str
    row: object  # PayrollElection | None

    @property
    def answered(self):
        return self.row is not None

    @property
    def value(self):
        return self.row.value_text if self.row else None

    @property
    def data(self):
        return (self.row.value_json or {}) if self.row else {}

    @property
    def hours(self):
        return self.row.standard_month_hours if self.row else None

    @property
    def scope(self):
        if self.row is None:
            return None
        return "SITE" if self.row.site_id else "COMPANY"

    def require(self):
        if self.row is None:
            raise ElectionUnanswered(self.key, citation_now(self.key))
        return self

    def as_dict(self):
        r = self.row
        return {
            "key": self.key, "answered": self.answered, "value": self.value,
            "data": r.value_json if r else None, "standardMonthHours": self.hours,
            "citation": r.statutory_citation if r else citation_now(self.key),
            "scope": self.scope, "uid": str(r.uid) if r else None,
            "effectiveFrom": r.effective_from.isoformat() if r else None,
            "effectiveTo": r.effective_to.isoformat() if r and r.effective_to else None,
            "decidedBy": (r.decided_by_name or None) if r else None,
            "approvedBy": (r.approved_by_name or None) if r else None,
            "source": r.source if r else None,
            "decidedAt": r.created_at.isoformat() if r else None,
        }


def citation_now(key, labour=None):
    """The citation as the labour rule set in force states it -- what a NEW
    election captures. A stored election keeps its own. `labour` is a
    `RuleSetView`; today's when omitted."""
    from rulebookio.book import rule_book

    meta = ELECTIONS[key]
    try:
        text = (labour or rule_book(clock.today()).labour).citation(meta["citation"])
    except Exception:  # noqa: BLE001 -- no rule set in force: say nothing rather than guess
        text = ""
    return f"{text}{meta.get('suffix', '')}" if text else ""


def _rows(company, site, as_of, keys=ELECTION_KEYS):
    q = (PayrollElection.objects.filter(company=company, election_key__in=keys, status__in=GOVERNING,
                                        effective_from__lte=as_of)
         .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of)))
    q = q.filter(Q(site__isnull=True) | Q(site=site)) if site is not None else q.filter(site__isnull=True)
    return q


def elections_for(company, site=None, as_of=None):
    """{key: Resolved} for all seven keys."""
    as_of = as_of or clock.today()
    if not PayrollElection.objects.filter(company=company).exists():
        from .ops import ensure_settings

        ensure_settings(company)  # the presets, once, for a company that predates them
    best = {}
    for row in _rows(company, site, as_of).order_by("effective_from"):
        cur = best.get(row.election_key)
        # A site row beats a company row; among equals the later start wins.
        if cur is None or (row.site_id is not None, row.effective_from) >= (cur.site_id is not None, cur.effective_from):
            best[row.election_key] = row
    return {k: Resolved(k, best.get(k)) for k in ELECTION_KEYS}


def election(company, key, as_of=None, site=None):
    return elections_for(company, site, as_of)[key]


def unanswered(resolved):
    return [k for k, r in resolved.items() if not r.answered]


# ===================================================== what each one governs


def amounts(structure):
    """{code: amount} of a saved structure or a `Built`."""
    out = {}
    if isinstance(getattr(structure, "components", None), list):
        pairs = structure.components
    else:
        pairs = [(c.code, c.amount) for c in structure.components.all()]
    for code, amount in pairs:
        out[code] = out.get(code, ZERO) + to_decimal(amount)
    return out


def _custom(structure, resolved):
    codes = list(resolved.data.get("components") or [])
    a = amounts(structure)
    return sum((a.get(c, ZERO) for c in codes), ZERO), codes


def overtime_base(structure, resolved):
    """(amount, codes, label). BASIC_PLUS_DA is the library's s.108 base --
    the components flagged toward it, basic and DA as seeded."""
    from employeeio.services.statutory import base_label, line_base

    r = resolved.require()
    if r.value == "GROSS":
        return structure.gross, ["GROSS"], "Gross"
    if r.value == "CUSTOM":
        total, codes = _custom(structure, r)
        return total, codes, base_label(codes)
    total, codes = line_base(structure, "in_ot_base_s108")
    return total, codes, base_label(codes)


def month_hours(resolved, book):
    """The election's standard month hours, else the rule book's 208. 208 is
    conventional, not statutory (open question 3): an election, as built."""
    if resolved.answered and resolved.hours:
        return Decimal(resolved.hours)
    return book.labour.decimal("standardMonthHours")


def gratuity_base(structure, resolved):
    from employeeio.services.statutory import base_label, line_base

    r = resolved.require()
    if r.value == "GROSS":
        return structure.gross, ["GROSS"], "monthly gross"
    if r.value == "CUSTOM":
        total, codes = _custom(structure, r)
        return total, codes, f"gratuity base ({base_label(codes)})"
    total, codes = line_base(structure, "in_gratuity_base")
    return total, codes, "basic" if codes == ["BASIC"] else f"gratuity base ({base_label(codes)})"


def days_worked_flags(resolved):
    """The five flags; `present` always counts (s.117)."""
    from ..choices import DAYS_WORKED_FLAGS

    data = resolved.require().data
    out = {f: bool(data.get(f)) for f in DAYS_WORKED_FLAGS}
    out["present"] = True
    return out


def band_pct(bands, months):
    for b in bands:
        if int(b["fromMonths"]) <= months <= int(b["toMonths"]):
            return to_decimal(str(b["pct"]))
    return None


def festival_under_year(full, completed_months, resolved):
    """(amount, basis) of one festival bonus for an employee under a year."""
    r = resolved.require()
    full = to_decimal(full)
    if r.value == "FULL":
        return full, "Full bonus (company election — above the statutory position)"
    if r.value == "PRO_RATA":
        return full * Decimal(completed_months) / TWELVE, f"Pro rata: {completed_months} of 12 completed months"
    if r.value == "BANDED":
        pct = band_pct(r.data.get("bands") or [], completed_months)
        if pct is None:
            raise ValueError(f"No bonus band covers {completed_months} months.")
        return full * pct / HUNDRED, f"Banded: {pct.normalize():f}% at {completed_months} completed months"
    return ZERO, "Nothing under a year — the statutory position"


def round_line(value, mode):
    """§4.4: once, at the payslip line, and never below the paisa figure.

    The spec says "half-up, never down"; half-up alone still takes ৳1,234 to
    ৳1,230, a ৳4 deduction s.123 does not authorise. The rule kept is the
    property (§9.2): a rounded line is never less than its PAISA value, so
    TAKA and TEN_TAKA round the paisa figure UP to the step."""
    value = to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if mode == "PAISA":
        return value
    if mode == "TAKA":
        return value.quantize(Decimal("1"), rounding=ROUND_CEILING)
    if mode == "TEN_TAKA":
        return (value / TEN).quantize(Decimal("1"), rounding=ROUND_CEILING) * TEN
    raise ValueError(f"Unknown rounding mode {mode!r}.")


@dataclass(frozen=True)
class Hypothetical:
    """A value being previewed, shaped like a `Resolved`."""

    key: str
    value: object
    data: dict
    hours: object = None
    answered = True
    scope = None
    row = None

    def require(self):
        return self
