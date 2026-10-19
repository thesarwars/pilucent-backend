"""Salary structures (employee profile §5-§6.2; salary profile backend §3-§8).

A structure is effective-dated and append-only. A revision **closes** the
structure in force (`effective_to`, `superseded_by`) and adds a new one; it
never overwrites, so any period already paid on the old one stays
reproducible. A structure dated after today is a scheduled change: it can be
cancelled until it takes effect, and a cancelled one stays on file.

Amounts, not percentages, are stored. Each line is rounded to the taka where
the template says so and the balancing line absorbs the rest, so the parts
always sum to gross exactly; reading a structure never rebuilds it from the
template. Whether a line is overridden is MEASURED on write -- the effective
percentage against the template's -- never a flag someone sets.

Every structure pins the labour rule set its floor was checked against.
Every write and every look at the figures goes to the salary audit.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from common import clock
from common.money import ZERO, money_str, round_to_paisa, round_to_taka, to_decimal
from common.words import both_words, format_money, group_south_asian
from rulebookio.book import RuleBookError, UnknownRule, rule_book

from ..choices import (
    ArrearsRunChoices,
    GradeChoices,
    OverrideBasisChoices,
    ProrationDivisorChoices,
    RevisionMethodChoices,
    RevisionTypeChoices,
    SalaryAuditActionChoices,
    SalaryComponentChoices,
    SalaryStatusChoices,
    SalaryTemplateChoices,
    TrackedFieldChoices,
)
from ..models import (
    Employee,
    EmployeeFieldHistory,
    EmployeeSalaryComponent,
    EmployeeSalaryStructure,
    SalaryAudit,
    SalaryOverride,
)
from .periods import next_unprocessed_period, period_label, reopened_periods
from .salary_access import actor_role
from .salary_templates import (
    OVERRIDE_TOLERANCE,
    ComponentsExceedGross,
    Split,
    build_basic_up,
    build_split,
    pct,
    pct_text,
    template_on,
    templates_on,
)
from .validation import validate_reason

# Pinned on every audit row and every structure's outcome, so a consumer
# recomputing under a different engine can tell.
ENGINE_VERSION = "pilucent-salary/2"

# Company policy, not statute (the profile screen's `salRules`): a warning,
# never a block.
INCREMENT_WARN_PCT = Decimal("25")
BASIC_SHARE_WARN_PCT = Decimal("50")
ROUNDING_STEPS = (0, 100, 500, 1000)
# A monthly figure past this is a typing error, and well inside the money
# column (Decimal(19, 3)).
MAX_AMOUNT = Decimal("1000000000")
HUNDRED = Decimal("100")
MONTHS = 12
_ONE_DP = Decimal("0.1")

C = SalaryComponentChoices
T = SalaryTemplateChoices
M = RevisionMethodChoices
R = RevisionTypeChoices
B = OverrideBasisChoices
A = SalaryAuditActionChoices

# Retired before the pay library: structures on them still read, and their
# next revision moves them to a current template.
RETIRED_TEMPLATES = (T.STD, T.CLASSIC)
GROSS_DOWN, BASIC_UP = "GROSS_DOWN", "BASIC_UP"
OVERRIDABLE = (C.BASIC, C.HRA, C.MED, C.CONV, C.OTHER)

# Unchecked optimistic concurrency, for callers inside the service.
UNCHECKED = object()


def library_template(company, code, on=None):
    """The pay library's template `code` in force on `on`, or None."""
    if company is None or not code:
        return None
    return template_on(company, code, on or clock.today())


def is_table(company, code, on=None):
    """A company template (gross-down or basic-up), not the gazette's."""
    t = library_template(company, code, on)
    return t is not None and not t.gazette


def is_basic_up(company, code, on=None):
    """Built up from basic, so the amount means basic and gross is the output."""
    if code == T.RMG:
        return True
    t = library_template(company, code, on)
    return t is not None and t.mode == BASIC_UP


def template_label(code, company=None):
    t = library_template(company, code) if company is not None else None
    if t is not None:
        return t.name
    return T(code).label if code in T.values else code


# --------------------------------------------------------------------- reads


def _structures(employee):
    return EmployeeSalaryStructure.objects.filter(employee=employee)


def structure_in_force(employee, on=None):
    on = on or clock.today()
    return (_structures(employee).in_force_on(on).prefetch_related("components")
            .order_by("-effective_from").first())


def latest_structure(employee):
    """The newest live structure: in force, or scheduled."""
    return _structures(employee).live().prefetch_related("components").order_by("-effective_from").first()


def scheduled_structure(employee, today=None):
    today = today or clock.today()
    return (_structures(employee).live().filter(effective_from__gt=today).prefetch_related("components")
            .order_by("effective_from").first())


# ----------------------------------------------------------------- templates


RMG_RULE = "Basic from the gazetted grade wage · gazetted allowances on top"


def templates_out(company, on=None):
    """The templates a structure can be built on today: the company's rows,
    then the gazette's RMG builder."""
    on = on or clock.today()
    out = []
    for row in templates_on(company, on):
        split = Split.of(row)
        basic_up = row.mode == BASIC_UP
        rows = [{"code": c, "name": C(c).label if c in C.values else c, "basis": b, "value": pct_text(v)
                 if b != B.FIXED else money_str(v)} for c, b, v in split.rows]
        rule = " · ".join(f"{r['name']} {r['value']}{'% of basic' if r['basis'] == B.PCT_BASIC else '% of gross' if r['basis'] == B.PCT_GROSS else ' fixed'}"
                          for r in rows)
        out.append({
            "id": row.code, "name": row.name, "nameBn": row.name_bn or None, "note": row.note,
            "split": split.notation, "basicPct": pct_text(split.basic), "hrPctOfBasic": pct_text(split.hr),
            "medPct": pct_text(split.med), "convPct": pct_text(split.conv),
            "remainderPct": pct_text(split.remainder) if split.remainder is not None else None,
            "balancing": None if basic_up else row.balancing_code,
            "mode": row.mode, "amountMeans": "basic" if basic_up else "gross", "version": row.effective_from.isoformat(),
            "versionNumber": row.version, "rows": rows, "rule": rule,
        })
    out.append({
        "id": T.RMG.value, "name": T.RMG.label, "nameBn": None,
        "note": "The gazetted RMG grade wage: basic from the grade, the gazette's allowances on top. "
                "Builds up from basic, so gross is the output.",
        "split": None, "basicPct": None, "hrPctOfBasic": None, "medPct": None, "convPct": None,
        "remainderPct": None, "balancing": None, "mode": BASIC_UP, "amountMeans": "basic", "version": None,
        "rule": RMG_RULE,
    })
    return out


@dataclass
class Intent:
    """A deliberate deviation from the template, as recorded (§3.6)."""

    basis: str
    value: Decimal
    reason: str


@dataclass
class Built:
    template: str
    components: list  # [(code, amount)] in display order
    rules: list = field(default_factory=list)  # RuleValues a statutory template rests on
    row: object = None  # the SalaryTemplate version it was built on
    split: object = None  # its Split, the baseline overrides are measured against
    overrides: dict = field(default_factory=dict)  # {code: Intent}
    balancing: str = None
    company: object = None  # whose library resolves each line's component version
    on: object = None

    @property
    def gross(self):
        return sum((amount for _, amount in self.components), ZERO)

    @property
    def basic(self):
        return self.amount(C.BASIC)

    def amount(self, code):
        return sum((a for c, a in self.components if c == code), ZERO)

    def same_as(self, structure):
        mine = {c: a for c, a in self.components if a}
        theirs = {c.code: c.amount for c in structure.components.all() if c.amount}
        return mine == theirs


def grade_label(grade):
    return GradeChoices(grade).label if grade in GradeChoices.values else "no grade recorded — the default floor"


def grade_floor_rules(grade, book):
    """(basic floor, total floor, grade label) for the grade, or the default
    floor when no grade is recorded. The rule book is the one source: its
    floors are dated, versioned and confidence-labelled."""
    basic = book.labour.get("gradeWageFloors")
    total = book.labour.get("gradeTotalWageFloors")
    if grade and grade in basic.value and grade in total.value:
        return (to_decimal(basic.value[grade]), basic), (to_decimal(total.value[grade]), total), grade_label(grade)
    return ((book.labour.decimal("gradeWageFloorDefault"), book.labour.get("gradeWageFloorDefault")),
            (book.labour.decimal("gradeTotalWageFloorDefault"), book.labour.get("gradeTotalWageFloorDefault")),
            grade_label(grade))


def _refused_template(template):
    if template in RETIRED_TEMPLATES:
        return SalaryRefused({"template": [
            f"{template_label(template)} is retired. Build the structure on a current template."]})
    return SalaryRefused({"template": [f"Unknown salary template {template!r}."]})


def build(template, amount, book, grade="", company=None, on=None, overrides=None, keep_gross=True):
    """The components a template gives for `amount` (gross for a gross-down
    template, basic for RMG). RMG with no amount starts from the grade's
    gazetted basic -- raised, where the grade's gazetted total needs it, to
    the lowest basic whose structure clears both floors. (The drafted G1/G2
    totals do not reconcile with their basics under the gazetted allowances;
    whichever series is wrong, the default must not fall below either.)

    `overrides` ({code: Intent}) set lines one by one against the template;
    the balancing line is then Other allowance. `keep_gross=False` lets gross
    become the sum of the lines."""
    if template == T.RMG:
        if overrides:
            raise SalaryRefused({"rows": ["An RMG structure follows the gazette: revise it instead of overriding."]})
        allowances = book.labour.get("rmgAllowances")
        a = allowances.value
        rate = to_decimal(a["houseRentRateOfBasic"])
        fixed = to_decimal(a["medical"]) + to_decimal(a["transport"]) + to_decimal(a["food"])

        def parts(basic):
            return [(C.BASIC, basic), (C.HRA, round_to_taka(basic * rate)), (C.MED, to_decimal(a["medical"])),
                    (C.CONV, to_decimal(a["transport"])), (C.FOOD, to_decimal(a["food"]))]

        if amount is None:
            (floor, floor_rule), (total, total_rule), _ = grade_floor_rules(grade, book)
            basic = max(floor, round_to_taka((total - fixed) / (1 + rate)))
            while sum(x for _, x in parts(basic)) < total:
                basic += 1
            return Built(template, parts(basic), [allowances, floor_rule, total_rule], balancing=C.BASIC,
                         company=company, on=on, row=library_template(company, T.RMG, on))
        return Built(template, parts(round_to_taka(amount)), [allowances], balancing=C.BASIC, company=company, on=on,
                     row=library_template(company, T.RMG, on))
    row = library_template(company, template, on or clock.today())
    if row is None or row.gazette:
        if template in RETIRED_TEMPLATES or company is None or row is None:
            raise _refused_template(template)
    split = Split.of(row)
    overrides = overrides or {}
    if split.mode == BASIC_UP:
        if overrides:
            raise SalaryRefused({"rows": [f"{row.name} builds up from basic: revise it instead of overriding."]})
        if amount is None:
            fixed = split.row(C.BASIC)
            (floor, floor_rule), _, _ = grade_floor_rules(grade, book)
            amount = max(fixed[1] if fixed and fixed[0] == B.FIXED else ZERO, floor)
        return Built(template, build_basic_up(split, amount), [], row, split, {}, None, company, on)
    try:
        components = build_split(split, amount, {c: (i.basis, i.value) for c, i in overrides.items()}, keep_gross)
    except ComponentsExceedGross as exc:
        raise SalaryRefused({"rows": [
            f"Components exceed gross by {format_money(exc.excess)}. The balancing line cannot go below zero: "
            "reduce a component, or let gross change."]}) from None
    return Built(template, components, [], row, split, overrides, C.OTHER if overrides else split.balancing,
                 company, on)


def template_input(structure):
    """What a template was given to build `structure`: gross, or basic for a
    basic-up template (RMG and the like)."""
    if is_basic_up(structure.employee.company, structure.template, structure.effective_from):
        return structure.basic
    return structure.gross


# ------------------------------------------------- describing the components


def percent_of(amount, whole):
    """Back-solved from the amounts on file, to one decimal (§5.1): a document
    says 58.6% of gross when that is what is in force, never the template's
    60% -- and 60, not 60.0, when it is exactly that."""
    value = pct(amount, whole)
    return None if value is None else pct_text(value)


def component_version(company, code, on):
    """The library version of `code` a line built on `on` pins (§9): a later
    flag change makes a new version and never rewrites this line's bases."""
    from paylibio.services.library import version_on

    c = version_on(company, code, on) if company is not None else None
    return c.version if c is not None else 1


def base_flags(company, code, version):
    """The line's bases, read from the component version it pins."""
    from paylibio.services.library import flags_of

    return flags_of(company, code, version)


def describe(built):
    """Each line with its basis, the template's percentage and whether it is
    overridden -- measured, |effective - template| >= 0.5pp (§5.2)."""
    gross, basic = built.gross, built.basic
    rows = []
    for code, amount in built.components:
        of_basic = code == C.HRA
        effective = pct(amount, basic if of_basic else gross)
        template_pct = built.split.template_pct(code) if built.split else None
        balancing = code == built.balancing
        if code == C.OTHER and balancing:
            basis = "Balance of gross"
        elif built.template == T.RMG and code in (C.MED, C.CONV, C.FOOD):
            basis = "Gazetted allowance"
        elif built.template == T.RMG and code == C.BASIC:
            basis = "Gazetted grade basic"
        elif effective is None:
            basis = ""
        else:
            basis = f"{pct_text(effective)}% of {'basic' if of_basic else 'gross'}"
        overridden = (template_pct is not None and effective is not None
                      and abs(effective - template_pct) >= OVERRIDE_TOLERANCE)
        rows.append({
            "code": code, "amount": amount, "basis_text": basis, "template_pct": template_pct,
            "effective_pct": effective, "is_overridden": overridden, "is_balancing": balancing,
            "component_version": component_version(built.company, code, built.on or clock.today()),
        })
    return rows


def _template_basis(code, template_pct):
    if template_pct is None:
        return None
    if code == C.OTHER:
        return f"Template: {pct_text(template_pct)}% of gross (balance)"
    return f"Template: {pct_text(template_pct)}% of {'basic' if code == C.HRA else 'gross'}"


def _line_out(code, amount, gross, *, basis, template_pct, effective_pct, overridden, balancing, flags):
    return {
        "code": code,
        "name": C(code).label if code in C.values else code,
        "amount": money_str(amount),
        "percentOfGross": percent_of(amount, gross),
        "basis": basis or (f"{percent_of(amount, gross)}% of gross" if gross else None),
        "templatePct": None if template_pct is None else pct_text(template_pct),
        "effectivePct": None if effective_pct is None else pct_text(effective_pct),
        "templateBasis": _template_basis(code, template_pct) if overridden else None,
        "isOverridden": overridden,
        "isBalancing": balancing,
        "bases": {"overtime": flags["in_ot_base_s108"], "providentFund": flags["in_pf_base"],
                  "gratuity": flags["in_gratuity_base"], "wages": flags["in_wages_base"],
                  "perquisiteCeiling": flags["in_perquisite_ceiling"], "taxable": flags["in_taxable_income"],
                  "festival": flags["in_festival_base"], "prorate": flags["prorate_part_month"]},
        "componentVersion": flags.get("version"),
    }


def described_out(built):
    gross = built.gross
    return [_line_out(r["code"], r["amount"], gross, basis=r["basis_text"], template_pct=r["template_pct"],
                      effective_pct=r["effective_pct"], overridden=r["is_overridden"], balancing=r["is_balancing"],
                      flags=base_flags(built.company, r["code"], r["component_version"]))
            for r in describe(built)]


def components_out(components, gross):
    """Plain lines (code, name, amount, percent of gross): issued documents."""
    return [{
        "code": code,
        "name": C(code).label if code in C.values else code,
        "amount": money_str(amount),
        "percentOfGross": percent_of(amount, gross),
        "basis": f"{percent_of(amount, gross)}% of gross" if gross else None,
    } for code, amount in components]


def _stored_lines(structure, gross):
    out = []
    company = structure.employee.company
    for c in structure.components.all():
        flags = base_flags(company, c.code, c.component_version)
        effective = c.effective_pct
        if effective is None:  # from before the metadata was recorded
            effective = pct(c.amount, gross)
        out.append(_line_out(c.code, c.amount, gross, basis=c.basis_text, template_pct=c.template_pct,
                             effective_pct=effective, overridden=c.is_overridden, balancing=c.is_balancing,
                             flags=flags))
    return out


def _override_out(o):
    return {
        "code": o.component_code,
        "name": C(o.component_code).label if o.component_code in C.values else o.component_code,
        "basis": B.FIXED if o.override_amount is not None else (B.PCT_BASIC if o.of_basic else B.PCT_GROSS),
        "value": money_str(o.override_amount) if o.override_amount is not None else pct_text(o.override_pct),
        "templatePct": None if o.template_pct is None else pct_text(o.template_pct),
        "reason": o.reason,
        "approvedBy": _actor(o.approved_by),
        "approvedAt": o.approved_at.isoformat() if o.approved_at else None,
        "excludedFromTemplateRevision": o.excluded_from_template_revision,
    }


def structure_out(structure, today=None):
    if structure is None:
        return None
    today = today or clock.today()
    components = [(c.code, c.amount) for c in structure.components.all()]
    gross = sum((a for _, a in components), ZERO)
    basic = sum((a for c, a in components if c == C.BASIC), ZERO)
    lines = _stored_lines(structure, gross)
    rtype = structure.revision_type or None
    return {
        "uid": str(structure.uid),
        "masked": False,
        "status": structure.status_on(today),
        "effectiveFrom": structure.effective_from.isoformat(),
        "effectiveTo": structure.effective_to.isoformat() if structure.effective_to else None,
        "template": structure.template,
        "templateName": template_label(structure.template, structure.employee.company),
        "templateRetired": structure.template in RETIRED_TEMPLATES,
        "templateVersion": (structure.template_version.effective_from.isoformat()
                            if structure.template_version_id else None),
        "gross": money_str(gross),
        "grossInWords": both_words(gross),
        "basic": money_str(basic),
        "basicPercentOfGross": percent_of(basic, gross),
        "components": lines,
        "overrideCount": sum(1 for line in lines if line["isOverridden"]),
        "overrides": [_override_out(o) for o in structure.overrides.all()],
        "revisionType": rtype,
        "revisionTypeLabel": R(rtype).label if rtype in R.values else None,
        "method": structure.method or None,
        "reason": structure.reason,
        "reopenedPeriods": structure.reopened_periods,
        "arrearsFrom": structure.reopened_periods[0] if structure.reopened_periods else None,
        "arrears": money_str(structure.arrears),
        "arrearsRun": structure.arrears_run or None,
        "supersededBy": str(structure.superseded_by.uid) if structure.superseded_by_id else None,
        "ruleSet": structure.rule_set.version if structure.rule_set_id else None,
        "gradeFloorApplied": money_str(structure.grade_floor_applied),
        "clearsFloor": structure.clears_floor,
        "approvedBy": _actor(structure.approved_by) or None,
        "approvedAt": structure.approved_at.isoformat() if structure.approved_at else None,
        "cancelledAt": structure.cancelled_at.isoformat() if structure.cancelled_at else None,
        "cancelReason": structure.cancel_reason or None,
    }


def masked_structure_out(structure, today=None):
    """What a caller who may not see figures is sent (§7): that a structure
    exists, its template, its dates and its floor position -- no amounts, not
    even hidden ones."""
    if structure is None:
        return None
    today = today or clock.today()
    rtype = structure.revision_type or None
    return {
        "uid": str(structure.uid),
        "masked": True,
        "status": structure.status_on(today),
        "effectiveFrom": structure.effective_from.isoformat(),
        "effectiveTo": structure.effective_to.isoformat() if structure.effective_to else None,
        "template": structure.template,
        "templateName": template_label(structure.template, structure.employee.company),
        "revisionType": rtype,
        "revisionTypeLabel": R(rtype).label if rtype in R.values else None,
        "clearsFloor": structure.clears_floor,
    }


# ----------------------------------------------------------- floors, warnings


def penalty_note(book):
    try:
        rule = book.labour.get("penalties.minimumWageNonPayment")
    except UnknownRule:
        return "Non-payment of the minimum wage is an offence."
    v = rule.value
    return (f"Non-payment of the minimum wage carries a fine of Tk {group_south_asian(v['min'])}–"
            f"{group_south_asian(v['max'])} and up to "
            f"{v['imprisonmentMonths']} months' imprisonment ({rule.citation}).")


def floor_checks(grade, basic, gross, book):
    """Both gazetted floors, checked on the FULL monthly rate (§5.3): a
    structure can clear one and fail the other. The floor applies to BASIC;
    the total-wage floor to gross. Proration is not underpayment, so nothing
    prorated is ever passed in here."""
    (basic_floor, basic_rule), (total_floor, total_rule), label = grade_floor_rules(grade, book)
    penalty = penalty_note(book)
    checks = []
    for kind, amount, floor, rule, what in (
        ("basic", basic, basic_floor, basic_rule, "Basic"),
        ("total", gross, total_floor, total_rule, "Total monthly wage"),
    ):
        passed = amount >= floor
        checks.append({
            "kind": kind,
            "grade": grade or None,
            "floor": money_str(floor),
            "amount": money_str(amount),
            "passed": passed,
            "message": None if passed else (
                f"{what} {format_money(amount)} is below the gazetted {kind} floor of {format_money(floor)} "
                f"for {label}. {penalty}"
            ),
            "rule": rule.rule,
            "citation": rule.citation,
            "confidence": rule.confidence,
        })
    return checks


def floor_position(grade, basic, book):
    """The profile's floor pill (§10.3): the failure states the penalty."""
    (floor, rule), (total, _), label = grade_floor_rules(grade, book)
    clears = basic >= floor
    note = (f"Basic of {format_money(basic)} clears the {format_money(floor)} gazetted minimum for {label}."
            if clears else
            f"Basic of {format_money(basic)} is below the {format_money(floor)} gazetted minimum for {label}. "
            f"{penalty_note(book)}")
    return {"floor": money_str(floor), "totalFloor": money_str(total), "basic": money_str(basic), "clears": clears,
            "note": note, "grade": grade or None, "gradeLabel": label, "rule": rule.rule,
            "citation": rule.citation, "confidence": rule.confidence}


def required_gross(template, book, grade, company, on):
    """The lowest gross whose structure clears both floors on `template` --
    the wizard's "Raise to the minimum". None for RMG, which builds up from
    the floor by itself."""
    row = library_template(company, template, on)
    if row is None or row.gazette or row.mode == BASIC_UP:
        return None
    (floor, _), (total, _), _ = grade_floor_rules(grade, book)
    split = Split.of(row)
    if not split.basic:
        return None
    gross = max((floor * HUNDRED / split.basic).quantize(Decimal(1), rounding=ROUND_CEILING), total)
    while True:
        lines = dict(build_split(split, gross))
        if lines[C.BASIC] >= floor:
            return gross
        gross += 1


def warnings_for(built, current_gross=None):
    """Warn, do not block (§5.2)."""
    out = []
    if current_gross:
        increase = (built.gross - current_gross) * HUNDRED / current_gross
        if increase > INCREMENT_WARN_PCT:
            out.append({"key": "salary.largeIncrement",
                        "message": f"This is a {increase.quantize(_ONE_DP, rounding=ROUND_HALF_UP)}% increase. "
                                   "Confirm this is intentional."})
    share = built.basic * HUNDRED / built.gross if built.gross else ZERO
    if built.gross and share < BASIC_SHARE_WARN_PCT:
        out.append({"key": "salary.lowBasicShare",
                    "message": f"Basic is {share.quantize(_ONE_DP, rounding=ROUND_HALF_UP)}% of gross. Overtime, "
                               "provident fund, gratuity and festival bonus are all calculated on basic; a low basic "
                               "reduces all four. Confirm this is intentional."})
    return out


# ------------------------------------------------------------------- arrears


def arrears_for(employee, effective_from, new_gross, old_gross, book):
    """Each processed period the change reaches back into, and what it owes:
    (new − paid) × the share of the period the new rate covers, rounded to the
    paisa per period. A part period prorates by the company's divisor --
    calendar actual where the election needs what is not on file: hours
    (HOURS_208) or the weekly holidays in the part period (WORKING_26)."""
    from .statutory import proration_factor

    profile = getattr(employee.company, "bd_statutory_profile", None)
    divisor = profile.proration_divisor if profile else ProrationDivisorChoices.CALENDAR_ACTUAL
    if divisor in (ProrationDivisorChoices.HOURS_208, ProrationDivisorChoices.WORKING_26):
        divisor = ProrationDivisorChoices.CALENDAR_ACTUAL
    rows, total = [], ZERO
    for period in reopened_periods(employee, effective_from):
        starts = max(d for d in (effective_from, employee.doj, period) if d)
        factor = proration_factor(period, divisor, book, join_date=starts, leave_date=employee.separated_on)
        due = round_to_paisa((new_gross - old_gross) * factor)
        total += due
        rows.append({
            "period": period_label(period),
            "paid": money_str(round_to_paisa(old_gross * factor)),
            "due": money_str(round_to_paisa(new_gross * factor)),
            "arrears": money_str(due),
            "factor": str(factor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        })
    return {
        "reopenedPeriods": [r["period"] for r in rows],
        "reopenedCount": len(rows),
        "periods": rows,
        "arrears": money_str(total),
        "prorationDivisor": divisor,
        "total": total,
    }


def public(consequence):
    """The consequence as it goes on the wire (the Decimal total is internal)."""
    return {k: v for k, v in consequence.items() if k != "total"}


# ------------------------------------------------------------- employer cost


def _statutory(employee):
    try:
        return employee.statutory
    except Employee.statutory.RelatedObjectDoesNotExist:
        return None


def employer_cost(employee, structure, as_of, book):
    """What the employee costs, line by line, each with its arithmetic (§4.3).
    `structure` is a saved structure or a `Built`. The provident-fund rate and
    the insurance premium are the company's elections; the gratuity days and
    the festival count are law, from the rule book."""
    from .statutory import gratuity

    gross, basic = structure.gross, structure.basic
    profile = getattr(employee.company, "bd_statutory_profile", None)
    statutory = _statutory(employee)
    rows = [("gross", "Gross", gross, "Structure total")]

    if statutory is not None and statutory.pf_member:
        rate = statutory.pf_employer if statutory.pf_employer is not None else (
            profile.pf_employer_rate if profile else Decimal("8"))
        rows.append(("providentFund", "Provident fund — employer", round_to_taka(basic * rate / HUNDRED),
                     f"{pct_text(rate)}% of basic"))
    else:
        rows.append(("providentFund", "Provident fund — employer", ZERO, "Not a provident-fund member"))

    tenure = None
    if employee.doj and statutory is not None:
        g = gratuity(employee, structure, as_of, book)
        parts = g.service
        served = f"{parts.years}y {parts.residual_months}m"
        basis = f"{served} · {g.days} days ÷ {MONTHS}"
        if g.rounded_up:
            fraction = book.labour.value("gratuityFractionMonths")
            basis += f" ({served} rounded up — a part-year over {fraction} months counts as a full year)"
        rows.append(("gratuity", "Gratuity provision", g.monthly_provision.value, basis))
        tenure = {"service": parts.as_dict(), "years": g.years, "roundedUp": g.rounded_up, "daysPerYear": g.days,
                  "label": served}
    else:
        rows.append(("gratuity", "Gratuity provision", ZERO, "No date of joining on file"))

    per_year = book.labour.get("festivalBonusesPerYear")
    cap = book.labour.get("festivalBonusCapMultiple")
    bonus = round_to_paisa(basic * cap.decimal * per_year.decimal / MONTHS)
    times = f"Basic × {per_year.value}" if cap.decimal == 1 else f"Basic × {cap.value} × {per_year.value}"
    rows.append(("festivalBonus", "Festival bonus provision", bonus, f"{times} ÷ {MONTHS}"))

    premium = profile.insurance_premium_monthly if profile else Decimal("148")
    covered = statutory is not None and statutory.insurance_covered
    rows.append(("insurance", "Group insurance", premium if covered else ZERO,
                 "Flat premium (company policy)" if covered else "Not covered"))

    total = sum((amount for _, _, amount, _ in rows), ZERO)
    overhead = pct(total - gross, gross) if gross else None
    return {
        "rows": [{"key": k, "label": label, "amount": money_str(amount), "basis": basis}
                 for k, label, amount, basis in rows],
        "total": money_str(round_to_taka(total)),
        "annual": money_str(round_to_taka(total * MONTHS)),
        "overheadPct": None if overhead is None else pct_text(overhead),
        "overheadLabel": None if overhead is None else f"{pct_text(overhead)}% over gross",
        "tenure": tenure,
        "lead": "An owner asking what someone costs is not asking for gross.",
    }


def gratuity_consequence(employee, current, built, as_of, book):
    """Gratuity is computed on the last drawn wage: a revision moves the
    liability for every completed year, not only future ones (§11.3)."""
    from .statutory import gratuity

    if current is None or not employee.doj or _statutory(employee) is None:
        return None
    before = gratuity(employee, current, as_of, book)
    after = gratuity(employee, built, as_of, book)
    delta = after.amount.value - before.amount.value
    if not delta:
        return None
    years = after.years
    verb = "increases" if delta > 0 else "reduces"
    return {
        "years": years, "before": money_str(before.amount.value), "after": money_str(after.amount.value),
        "delta": money_str(delta),
        "note": (f"Gratuity is computed on the last drawn wage, so this revision {verb} the accrued liability "
                 f"for all {years} completed year{'s' if years != 1 else ''}, not just future ones."),
    }


# ----------------------------------------------------------------- outcomes


class SalaryRefused(Exception):
    """A refused assignment or revision. `errors` is field -> messages;
    `consequence` is what it would have done (§9: a gated operation refused
    for a missing reason still states the periods and arrears)."""

    def __init__(self, errors, consequence=None, status=400):
        self.errors = errors
        self.consequence = consequence
        self.status = status
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _history_value(gross, basic):
    return f"Gross {format_money(gross)} · Basic {format_money(basic)}"


def _actor(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _rule_set(book):
    try:
        return book.labour.rule_set if book is not None else None
    except RuleBookError:
        return None


def _snapshot(structure_or_built):
    if structure_or_built is None:
        return None
    if isinstance(structure_or_built, Built):
        lines = structure_or_built.components
        return {"template": structure_or_built.template, "gross": money_str(structure_or_built.gross),
                "components": {c: money_str(a) for c, a in lines}}
    s = structure_or_built
    return {"uid": str(s.uid), "effectiveFrom": s.effective_from.isoformat(), "template": s.template,
            "gross": money_str(s.gross), "components": {c.code: money_str(c.amount) for c in s.components.all()}}


def audit(employee, action, user, *, structure=None, before=None, after=None, reason="", book=None):
    SalaryAudit.objects.create(
        company=employee.company, employee=employee, structure=structure, action=action,
        actor=user if user is not None and getattr(user, "is_authenticated", False) else None,
        actor_name=_actor(user), actor_role=actor_role(user, employee.company),
        before_json=before, after_json=after, reason=reason or "", rule_set=_rule_set(book),
        engine_version=ENGINE_VERSION,
    )


def _save(employee, built, effective_from, *, reason, user, consequence, arrears_run, checks, book,
          revision_type, method, closes, history_reason, from_value, idempotency_key=""):
    now = timezone.now()
    basic_check = next(c for c in checks if c["kind"] == "basic")
    structure = EmployeeSalaryStructure.objects.create(
        employee=employee, effective_from=effective_from, template=built.template, template_version=built.row,
        reason=reason, created_by=user, revision_type=revision_type, method=method,
        reopened_periods=consequence["reopenedPeriods"], arrears=consequence["total"],
        arrears_run=arrears_run if consequence["reopenedCount"] else "",
        rule_set=_rule_set(book), grade_floor_applied=to_decimal(basic_check["floor"]),
        clears_floor=basic_check["passed"], approved_by=user, approved_at=now,
        idempotency_key=idempotency_key or "",
    )
    EmployeeSalaryComponent.objects.bulk_create([
        EmployeeSalaryComponent(structure=structure, position=position, **line)
        for position, line in enumerate(describe(built))
    ])
    SalaryOverride.objects.bulk_create([
        SalaryOverride(
            structure=structure, component_code=code,
            template_pct=built.split.template_pct(code) if built.split else None,
            override_pct=None if intent.basis == B.FIXED else intent.value,
            of_basic=intent.basis == B.PCT_BASIC,
            override_amount=intent.value if intent.basis == B.FIXED else None,
            reason=intent.reason, approved_by=user, approved_at=now,
        )
        for code, intent in built.overrides.items()
    ])
    if closes is not None:
        closes.effective_to = effective_from - timedelta(days=1)
        closes.superseded_by = structure
        closes.save(update_fields=["effective_to", "superseded_by", "updated_at"])
        audit(employee, A.SUPERSEDED, user, structure=closes, before=_snapshot(closes), reason=history_reason,
              book=book)
    EmployeeFieldHistory.objects.create(
        employee=employee, field=TrackedFieldChoices.SALARY, date=effective_from,
        from_value=from_value, to_value=_history_value(built.gross, built.basic),
        by=user, by_name=_actor(user), reason=history_reason,
    )
    if method == M.OVERRIDE:
        action = A.OVERRIDDEN
    elif effective_from > clock.today():
        action = A.SCHEDULED
    elif closes is None:
        action = A.ASSIGNED
    else:
        action = A.REVISED
    audit(employee, action, user, structure=structure, before=_snapshot(closes), after=_snapshot(built),
          reason=reason or history_reason, book=book)
    return structure


def _outcome(employee, built, effective_from, checks, warnings, consequence, *, book, current=None, saved=None,
             backdated=False, preview=False):
    today = clock.today()
    return {
        "preview": preview,
        "saved": saved is not None,
        "effectiveFrom": effective_from.isoformat(),
        "status": (SalaryStatusChoices.SCHEDULED if effective_from > today else SalaryStatusChoices.ACTIVE),
        "backdated": backdated,
        "template": built.template,
        "templateName": template_label(built.template, built.company),
        "gross": money_str(built.gross),
        "grossInWords": both_words(built.gross),
        "basic": money_str(built.basic),
        "components": described_out(built),
        "floors": checks,
        "floor": floor_position(employee.grade, built.basic, book),
        "warnings": warnings,
        "consequence": public(consequence),
        "employerCost": employer_cost(employee, built, max(effective_from, today), book),
        "gratuity": gratuity_consequence(employee, current, built, today, book),
        "structure": structure_out(saved) if saved is not None else None,
        "engineVersion": ENGINE_VERSION,
    }


def floor_book(effective_from):
    """The rules a new structure is checked against: those in force on a day
    it will actually be paid. A structure opened in the past is still in force
    today, so today's floors apply to it -- and a joining date from before the
    rule book's first set must not make it unassignable."""
    return rule_book(max(effective_from, clock.today()))


def _floors_or_refuse(employee, built, book, consequence, effective_from):
    """Below the floor is refused (422), with the gross that would clear it."""
    checks = floor_checks(employee.grade, built.basic, built.gross, book)
    failed = [c["message"] for c in checks if not c["passed"]]
    if failed:
        need = None if built.overrides else required_gross(built.template, book, employee.grade, employee.company,
                                                           effective_from)
        if need is not None:
            failed.append(f"A gross of {format_money(need)} on this template clears both floors.")
        raise SalaryRefused({"amount": failed}, {**public(consequence), "floors": checks,
                                                 "requiredGross": money_str(need)}, status=422)
    return checks


def _check_expected(current, expected):
    """Optimistic concurrency (§8.1): the write names the structure it was
    based on. Two people revising the same employee in the same minute must
    not silently overwrite one another."""
    if expected is UNCHECKED:
        return
    have = str(current.uid) if current is not None else None
    if (expected or None) != have:
        if current is None:
            message = "The structure you were looking at is gone. Reload and try again."
        else:
            message = (f"This salary changed since you opened it: a structure from "
                       f"{current.effective_from.isoformat()} is now the latest"
                       f"{' (saved by ' + _actor(current.created_by) + ')' if current.created_by_id else ''}. "
                       "Reload and try again.")
        raise SalaryRefused({"expectedStructure": [message]}, status=409)


def replay(employee, idempotency_key):
    """A retried write (§8.3): the structure the key already created, or None."""
    if not idempotency_key:
        return None
    return (_structures(employee).filter(idempotency_key=idempotency_key)
            .prefetch_related("components", "overrides").first())


def replayed_outcome(employee, structure):
    book = rule_book(max(structure.effective_from, clock.today()))
    lines = [(c.code, c.amount) for c in structure.components.all()]
    built = Built(structure.template, lines, balancing=next(
        (c.code for c in structure.components.all() if c.is_balancing), None))
    checks = floor_checks(employee.grade, built.basic, built.gross, book)
    consequence = {"reopenedPeriods": structure.reopened_periods, "reopenedCount": len(structure.reopened_periods),
                   "periods": [], "arrears": money_str(structure.arrears), "prorationDivisor": None}
    out = _outcome(employee, built, structure.effective_from, checks, [], {**consequence, "total": ZERO},
                   book=book, saved=structure)
    out["replayed"] = True
    return out


def _commit(employee, built, effective_from, *, current, book, reason, user, preview, arrears_run, revision_type,
            method, history_label, warnings=None, idempotency_key="", needs_reason_when_backdated=True):
    """The pipeline every write shares (§6.1): floors, the backdate check,
    then -- unless previewing -- close the prior structure and insert the new
    one in one transaction, and audit."""
    old_gross = current.gross if current is not None else ZERO
    consequence = arrears_for(employee, effective_from, built.gross, old_gross, book)
    checks = _floors_or_refuse(employee, built, book, consequence, effective_from)
    warnings = list(warnings or []) + warnings_for(built, old_gross or None)
    today = clock.today()
    next_open = next_unprocessed_period(employee.company, today)
    backdated = effective_from < next_open
    if backdated and current is not None and needs_reason_when_backdated:
        warnings.append({"key": "salary.backdated", "message": (
            f"Backdated before {period_label(next_open)}, the next unprocessed period: "
            f"{consequence['reopenedCount']} processed period(s) reopen and "
            f"{format_money(consequence['total'], places=2)} of arrears are queued.")})
        try:
            reason = validate_reason(reason)
        except ValidationError as exc:
            raise SalaryRefused(
                {"reason": [f"A backdated revision needs a stated reason. {' '.join(exc.messages)}"]},
                {**public(consequence), "floors": checks, "warnings": warnings},
                status=422,
            ) from None
    reason = (reason or "").strip()
    if preview:
        return _outcome(employee, built, effective_from, checks, warnings, consequence, book=book, current=current,
                        backdated=backdated, preview=True)
    with transaction.atomic():
        if current is None:
            # Two first assignments racing: the second waits here, then finds the first.
            Employee.objects.select_for_update().filter(pk=employee.pk).first()
            if latest_structure(employee) is not None:
                raise SalaryRefused({"salary": ["A structure was assigned meanwhile. Reload and revise it."]},
                                    status=409)
            locked = None
        else:
            locked = EmployeeSalaryStructure.objects.select_for_update().get(pk=current.pk)
            if locked.effective_to is not None or locked.cancelled_at is not None:
                raise SalaryRefused({"salary": ["The structure was revised meanwhile. Reload and try again."]},
                                    status=409)
        saved = _save(
            employee, built, effective_from, reason=reason, user=user, consequence=consequence,
            arrears_run=arrears_run or ArrearsRunChoices.NEXT_RUN, checks=checks, book=book,
            revision_type=revision_type, method=method, closes=locked,
            history_reason=reason or history_label,
            from_value=_history_value(old_gross, current.basic) if current is not None else "—",
            idempotency_key=idempotency_key,
        )
    saved = (EmployeeSalaryStructure.objects.select_related("template_version", "rule_set", "approved_by")
             .prefetch_related("components", "overrides").get(pk=saved.pk))
    return _outcome(employee, built, effective_from, checks, warnings, consequence, book=book, current=current,
                    saved=saved, backdated=backdated)


# ---------------------------------------------------------------- assignment


def checked_amount(value, field="value"):
    """A finite decimal within reason, or a refusal naming the field."""
    try:
        amount = to_decimal(value)
    except (TypeError, ValueError):
        raise SalaryRefused({field: ["Send a decimal string, e.g. \"22000\" or \"8.5\"."]}) from None
    if not amount.is_finite() or abs(amount) >= MAX_AMOUNT:
        raise SalaryRefused({field: [f"Must be a finite amount below {group_south_asian(MAX_AMOUNT)}."]})
    return amount


def assign(employee, *, template, amount=None, effective_from=None, arrears_run=None, user=None, preview=False,
           revision_type=None, expected=UNCHECKED, idempotency_key=""):
    """The first structure. `effective_from` defaults to the date of joining."""
    current = latest_structure(employee)
    if current is not None:
        raise SalaryRefused({"salary": ["This employee already has a salary structure. Revise it instead."]},
                            status=409)
    _check_expected(None, expected)
    effective_from = effective_from or employee.doj
    if effective_from is None:
        raise SalaryRefused({"effective_from": ["An effective date is required: no date of joining is on file."]})
    if employee.doj and effective_from < employee.doj:
        raise SalaryRefused({"effective_from": [
            f"A structure cannot take effect before the date of joining ({employee.doj.isoformat()})."]})
    if employee.separated_on and effective_from > employee.separated_on:
        raise SalaryRefused({"effective_from": [f"The employee separated on {employee.separated_on.isoformat()}."]})
    if amount is None and not is_basic_up(employee.company, template, effective_from):
        raise SalaryRefused({"amount": ["A gross amount is required for this template."]})
    if amount is not None and checked_amount(amount, "amount") <= 0:
        raise SalaryRefused({"amount": ["The amount must be above zero."]})
    if revision_type not in (None, "", R.FIRST_ASSIGNMENT, R.OPENING_BALANCE):
        raise SalaryRefused({"revisionType": ["A first structure is a FIRST_ASSIGNMENT or an OPENING_BALANCE."]})
    book = floor_book(effective_from)
    built = build(template, amount, book, employee.grade, employee.company, effective_from)
    return _commit(employee, built, effective_from, current=None, book=book, reason="", user=user, preview=preview,
                   arrears_run=arrears_run, revision_type=revision_type or R.FIRST_ASSIGNMENT, method="",
                   history_label=f"Assigned on the {template_label(template, employee.company)}",
                   idempotency_key=idempotency_key)


# ------------------------------------------------------------------ revision


def revision_default(employee, current, today=None):
    """The start of the next unprocessed period (§5.2) -- never the joining
    date, which silently offered a nine-year backdate -- and after the
    structure being replaced."""
    default = next_unprocessed_period(employee.company, today)
    if current is not None and default <= current.effective_from:
        default = current.effective_from + timedelta(days=1)
    return default


def _revised_amount(method, value, current, template, company=None, on=None):
    """The new template input (gross, or basic for a basic-up template)."""
    means = "basic" if is_basic_up(company, template, on) else "gross"
    if method == M.CHANGE_TEMPLATE:
        if value is not None:
            return checked_amount(value)
        return current.basic if means == "basic" else current.gross
    if value is None:
        raise SalaryRefused({"value": ["A value is required for this method."]})
    v = checked_amount(value)
    base = template_input(current) if current.template == template else (
        current.basic if means == "basic" else current.gross)
    if method == M.PERCENTAGE_INCREASE:
        return base * (1 + v / HUNDRED)
    if method == M.FIXED_INCREASE:
        return base + v
    if method == M.NEW_GROSS:
        if means == "basic":
            raise SalaryRefused({"method": ["This template is built up from basic: revise it with NEW_BASIC."]})
        return v
    if method == M.NEW_BASIC:
        if means != "basic":
            raise SalaryRefused({"method": ["NEW_BASIC applies to a basic-up structure; use NEW_GROSS."]})
        return v
    raise SalaryRefused({"method": [f"Unknown revision method {method!r}."]})


def carried_overrides(structure):
    """The deliberate deviations on `structure`, to carry to the next one: an
    override survives a revision (§3.6)."""
    return {o.component_code: Intent(
        B.FIXED if o.override_amount is not None else (B.PCT_BASIC if o.of_basic else B.PCT_GROSS),
        o.override_amount if o.override_amount is not None else o.override_pct, o.reason,
    ) for o in structure.overrides.all() if o.excluded_from_template_revision}


def _current_or_refuse(employee):
    current = latest_structure(employee)
    if current is None:
        raise SalaryRefused({"salary": ["No salary structure to revise. Assign one first."]}, status=409)
    if current.effective_to is not None:
        raise SalaryRefused({"salary": [
            f"The latest structure closed on {current.effective_to.isoformat()}; there is nothing in force to revise."
        ]}, status=409)
    return current


def _effective_or_refuse(employee, current, effective_from, today):
    effective_from = effective_from or revision_default(employee, current, today)
    if effective_from <= current.effective_from:
        raise SalaryRefused({"effective_from": [
            f"A revision must take effect after the structure it replaces, in force from "
            f"{current.effective_from.isoformat()}."]})
    if employee.separated_on and effective_from > employee.separated_on:
        raise SalaryRefused({"effective_from": [f"The employee separated on {employee.separated_on.isoformat()}."]})
    return effective_from


def revise(employee, *, method, value=None, effective_from=None, reason="", template=None, rounding=0,
           revision_type=None, arrears_run=None, user=None, preview=False, expected=UNCHECKED,
           idempotency_key=""):
    current = _current_or_refuse(employee)
    _check_expected(current, expected)
    today = clock.today()
    effective_from = _effective_or_refuse(employee, current, effective_from, today)
    if rounding not in ROUNDING_STEPS:
        raise SalaryRefused({"rounding": [f"Rounding must be one of {', '.join(map(str, ROUNDING_STEPS))}."]})
    if revision_type in (R.FIRST_ASSIGNMENT, R.OPENING_BALANCE):
        raise SalaryRefused({"revisionType": [f"{R(revision_type).label} applies only to a first structure."]})

    warnings = []
    company = employee.company

    def known(code):
        return code == T.RMG or is_table(company, code, effective_from)

    if method == M.CHANGE_TEMPLATE:
        template = template or (str(value) if known(str(value)) else None)
        if template is None:
            raise SalaryRefused({"template": ["Name the template to change to."]})
        if template == current.template:
            raise SalaryRefused({"template": ["The structure is already on this template."]})
        value = None if known(str(value)) else value
    elif current.template in RETIRED_TEMPLATES and (template is None or template == current.template):
        raise SalaryRefused({"template": [
            f"This structure is on the {template_label(current.template, employee.company)}. Choose a current template: revise it "
            "with CHANGE_TEMPLATE."]})
    template = template or current.template
    if not known(template):
        raise _refused_template(template)
    amount = _revised_amount(method, value, current, template, company, effective_from)
    if rounding:
        amount = (amount / rounding).quantize(Decimal(1), rounding=ROUND_HALF_UP) * rounding
    if amount <= 0:
        raise SalaryRefused({"value": ["The revised amount must be above zero."]})
    checked_amount(amount)

    overrides = {}
    if template == current.template and is_table(company, template, effective_from) \
            and not is_basic_up(company, template, effective_from):
        overrides = carried_overrides(current)
    elif current.overrides.exists():
        warnings.append({"key": "salary.overridesDropped", "message": (
            "The overrides on the current structure do not carry to a new template; it is built on the "
            "template's own split.")})
    book = floor_book(effective_from)
    built = build(template, amount, book, employee.grade, employee.company, effective_from, overrides)
    if built.same_as(current) and template == current.template:
        raise SalaryRefused({"value": ["The revised structure is the same as the one in force."]})
    label = R(revision_type).label if revision_type else M(method).label
    return _commit(employee, built, effective_from, current=current, book=book, reason=reason, user=user,
                   preview=preview, arrears_run=arrears_run, revision_type=revision_type or "", method=method,
                   history_label=label, warnings=warnings, idempotency_key=idempotency_key)


def reassign(employee, *, template, amount=None, effective_from=None, reason="", revision_type=None,
             arrears_run=None, user=None, preview=False, expected=UNCHECKED, idempotency_key=""):
    """Assign or reassign: one operation (§6.1, §13.2). A reassignment builds
    `amount` on `template` from the next unprocessed period by default."""
    current = latest_structure(employee)
    if current is None:
        return assign(employee, template=template, amount=amount, effective_from=effective_from,
                      arrears_run=arrears_run, user=user, preview=preview, revision_type=revision_type,
                      expected=expected, idempotency_key=idempotency_key)
    if template != current.template:
        method = M.CHANGE_TEMPLATE
    else:
        method = M.NEW_BASIC if is_basic_up(employee.company, template, effective_from) else M.NEW_GROSS
        if amount is None:
            raise SalaryRefused({"amount": ["A gross amount is required to reassign on the same template."]})
    return revise(employee, method=method, value=amount, effective_from=effective_from, reason=reason,
                  template=template, revision_type=revision_type or R.STRUCTURE_CHANGE, arrears_run=arrears_run,
                  user=user, preview=preview, expected=expected, idempotency_key=idempotency_key)


# ----------------------------------------------------------------- overrides


OVERRIDE_MODES = ("REBALANCE", "CHANGE")


def _intents(rows, split, reason):
    """The override rows that actually differ from the template, as intents.
    A row equal to the template's own basis and value is not an override."""
    out = {}
    for row in rows:
        code, basis = row.get("code"), row.get("basis")
        if code not in OVERRIDABLE:
            raise SalaryRefused({"rows": [f"{code!r} cannot be overridden; use one of {', '.join(OVERRIDABLE)}."]})
        if basis not in B.values or (code == C.BASIC and basis == B.PCT_BASIC):
            raise SalaryRefused({"rows": [f"{C(code).label}: basis must be one of "
                                          f"{', '.join(b for b in B.values if not (code == C.BASIC and b == B.PCT_BASIC))}."]})
        value = checked_amount(row.get("value"), "rows")
        if value < 0:
            raise SalaryRefused({"rows": [f"{C(code).label} cannot be negative."]})
        if basis != B.FIXED and value > HUNDRED:
            raise SalaryRefused({"rows": [f"{C(code).label}: a percentage cannot exceed 100."]})
        t_basis, t_value = split.default_basis(code)
        if basis == t_basis and to_decimal(value) == to_decimal(t_value):
            continue
        if code in out:
            raise SalaryRefused({"rows": [f"{C(code).label} is listed twice."]})
        out[code] = Intent(basis, value, reason)
    return out


def override(employee, base, *, rows, mode="REBALANCE", reason="", effective_from=None, revision_type=None,
             arrears_run=None, user=None, preview=False, idempotency_key=""):
    """Deviate from the template without abandoning it (§6.2, §11.2). The
    result is a NEW structure from the next unprocessed period; the current
    one is closed, never updated in place. `base` is the structure the grid
    was built from: if it is no longer the latest, someone else got there
    first (§8.1)."""
    current = _current_or_refuse(employee)
    if base.pk != current.pk:
        raise SalaryRefused({"structure": [
            "This is no longer the latest structure. Reload the overrides from the one now in force."]}, status=409)
    if not is_table(employee.company, current.template) or is_basic_up(employee.company, current.template):
        raise SalaryRefused({"structure": [
            f"Overrides apply to a gross-down template structure; this one is on the "
            f"{template_label(current.template, employee.company)}. Revise it instead."]})
    if mode not in OVERRIDE_MODES:
        raise SalaryRefused({"mode": [f"Mode must be one of {', '.join(OVERRIDE_MODES)}."]})
    if not preview:
        # Checked on save, not on preview: the grid previews as it is edited.
        try:
            reason = validate_reason(reason)
        except ValidationError as exc:
            raise SalaryRefused({"reason": [f"An override needs a stated reason. {' '.join(exc.messages)}"]}) from None
    today = clock.today()
    effective_from = _effective_or_refuse(employee, current, effective_from, today)
    book = floor_book(effective_from)
    row = template_on(employee.company, current.template, effective_from)
    split = Split.of(row)
    intents = _intents(rows, split, reason)
    if mode == "REBALANCE":
        intents.pop(C.OTHER, None)  # the balancing line is the output when gross is kept
    built = build(current.template, current.gross, book, employee.grade, employee.company, effective_from,
                  intents, keep_gross=mode == "REBALANCE")
    if built.same_as(current):
        raise SalaryRefused({"rows": ["Nothing differs from the structure in force."]})
    return _commit(employee, built, effective_from, current=current, book=book, reason=reason, user=user,
                   preview=preview, arrears_run=arrears_run, revision_type=revision_type or R.STRUCTURE_CHANGE,
                   method=M.OVERRIDE, history_label="Component override", idempotency_key=idempotency_key)


# ------------------------------------------------------------------- cancel


def cancel(employee, structure, *, reason, user=None):
    """Cancel a scheduled change (§6.5). Only one that has not taken effect: a
    structure that has been paid on can only be superseded by a correction.
    The cancelled structure stays on file; the one it would have closed is
    reopened."""
    today = clock.today()
    if structure.cancelled_at is not None:
        raise SalaryRefused({"structure": ["This scheduled change is already cancelled."]}, status=409)
    if structure.effective_from <= today:
        raise SalaryRefused({"structure": [
            f"In force since {structure.effective_from.isoformat()}: only a scheduled change can be cancelled. "
            "Correct it with a revision that carries a reason."]}, status=409)
    if structure.superseded_by_id is not None:
        raise SalaryRefused({"structure": ["A later scheduled change follows this one. Cancel that one first."]},
                            status=409)
    try:
        reason = validate_reason(reason)
    except ValidationError as exc:
        raise SalaryRefused({"reason": [f"Say why it is cancelled. {' '.join(exc.messages)}"]}) from None
    with transaction.atomic():
        locked = EmployeeSalaryStructure.objects.select_for_update().get(pk=structure.pk)
        if locked.cancelled_at is not None or locked.superseded_by_id is not None:
            raise SalaryRefused({"structure": ["This structure changed meanwhile. Reload and try again."]},
                                status=409)
        previous = EmployeeSalaryStructure.objects.select_for_update().filter(superseded_by=locked).first()
        locked.cancelled_at = timezone.now()
        locked.cancelled_by = user
        locked.cancel_reason = reason
        locked.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason", "updated_at"])
        if previous is not None:
            previous.effective_to = None
            previous.superseded_by = None
            previous.save(update_fields=["effective_to", "superseded_by", "updated_at"])
        EmployeeFieldHistory.objects.create(
            employee=employee, field=TrackedFieldChoices.SALARY, date=locked.effective_from,
            from_value=_history_value(locked.gross, locked.basic),
            to_value=_history_value(previous.gross, previous.basic) if previous else "—",
            by=user, by_name=_actor(user), reason=f"Scheduled change cancelled: {reason}",
        )
        audit(employee, A.CANCELLED, user, structure=locked, before=_snapshot(locked), reason=reason)
    return locked


# ------------------------------------------------------------------- history


def history(employee):
    """Every structure, newest first, including superseded and cancelled ones (§5.2)."""
    structures = (_structures(employee).select_related("superseded_by", "template_version", "rule_set",
                                                       "approved_by")
                  .prefetch_related("components", "overrides").order_by("-effective_from", "-created_at"))
    today = clock.today()
    return [structure_out(s, today) for s in structures]


def _inferred_type(structure, previous, employee, today):
    """What the history calls a row whose type was not stored (§11.3)."""
    if structure.cancelled_at is not None:
        return "Cancelled scheduled change"
    if structure.revision_type in R.values:
        label = R(structure.revision_type).label
        return f"Scheduled — {label.lower()}" if structure.effective_from > today else label
    if structure.effective_from > today:
        return "Scheduled change"
    if previous is None:
        # Near the joining date is a first assignment; years after it is the
        # earliest record this system holds, and calling it a first
        # assignment would misstate the employment history.
        near = employee.doj is not None and 0 <= (structure.effective_from - employee.doj).days <= 31
        return "First assignment" if near else "Earliest record on file"
    if structure.gross > previous.gross:
        return "Increment"
    if structure.gross < previous.gross:
        return "Downward revision"
    return "Restructure"


def history_rows(employee):
    """The salary history (§6.4): every structure newest first, with its
    type, the change against the prior gross, and the floor as at its own
    effective date -- a structure that cleared the 2024 floor and fails the
    2026 one was compliant when written."""
    today = clock.today()
    structures = list(_structures(employee).select_related("superseded_by", "template_version", "rule_set",
                                                           "approved_by")
                      .prefetch_related("components", "overrides").order_by("effective_from", "created_at"))
    rows, previous, previous_obj = [], None, None
    for s in structures:
        out = structure_out(s, today)
        gross, basic = to_decimal(out["gross"]), to_decimal(out["basic"])
        prior = to_decimal(previous["gross"]) if previous else None
        try:
            book = rule_book(s.effective_from)
            (floor, rule), _, _ = grade_floor_rules(employee.grade, book)
            floor_then = {"floor": money_str(floor), "clears": basic >= floor, "confidence": rule.confidence,
                          "ruleSet": book.labour.version}
        except RuleBookError as exc:
            floor_then = {"floor": None, "clears": None, "confidence": None, "ruleSet": None,
                          "message": str(exc)}
        out.update({
            "typeLabel": _inferred_type(s, previous_obj, employee, today),
            "deltaAmount": money_str(gross - prior) if prior is not None else None,
            "deltaPct": pct_text(pct(gross - prior, prior)) if prior else None,
            "floorThen": floor_then,
        })
        rows.append(out)
        if s.cancelled_at is None:
            previous, previous_obj = out, s
    return list(reversed(rows))
