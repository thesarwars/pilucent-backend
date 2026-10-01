"""Salary structures (doc §5, §6.2): templates, assignment, revision.

A structure is effective-dated. A revision **closes** the structure in force
(`effective_to`, `superseded_by`) and adds a new one; it never overwrites, so
any period already paid on the old one stays reproducible.

Rounding points (common.money): each template component is rounded to the
taka where its rule says so, and the balancing component absorbs the
residual, so the parts always sum to gross exactly. Arrears are rounded to the
paisa per period.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from common import clock
from common.money import ZERO, money_str, round_to_paisa, round_to_taka, to_decimal
from common.words import both_words, format_money, group_south_asian
from rulebookio.book import UnknownRule, rule_book

from ..choices import (
    ArrearsRunChoices,
    ProrationDivisorChoices,
    RevisionMethodChoices,
    RevisionTypeChoices,
    SalaryComponentChoices,
    SalaryTemplateChoices,
    TrackedFieldChoices,
)
from ..models import Employee, EmployeeFieldHistory, EmployeeSalaryComponent, EmployeeSalaryStructure
from .periods import next_unprocessed_period, period_label, reopened_periods
from .validation import validate_reason

# Company policy, not statute (the profile screen's `salRules`): a warning,
# never a block.
INCREMENT_WARN_PCT = Decimal("25")
BASIC_SHARE_WARN_PCT = Decimal("50")
ROUNDING_STEPS = (0, 100, 500, 1000)
# A monthly figure past this is a typing error, and well inside the money
# column (Decimal(19, 3)).
MAX_AMOUNT = Decimal("1000000000")
HUNDRED = Decimal("100")
_ONE_DP = Decimal("0.1")

C = SalaryComponentChoices
T = SalaryTemplateChoices
M = RevisionMethodChoices


def structure_in_force(employee, on=None):
    on = on or clock.today()
    return (
        EmployeeSalaryStructure.objects.filter(employee=employee)
        .in_force_on(on)
        .prefetch_related("components")
        .order_by("-effective_from")
        .first()
    )


def latest_structure(employee):
    return (
        EmployeeSalaryStructure.objects.filter(employee=employee)
        .prefetch_related("components")
        .order_by("-effective_from")
        .first()
    )


# ----------------------------------------------------------------- templates


GROSS_DOWN, BASIC_UP = "GROSS_DOWN", "BASIC_UP"
TEMPLATES = {
    T.STD: {"mode": GROSS_DOWN, "amount": "gross",
            "rule": "Basic 60% of gross · House rent 50% of basic · Medical 7% · Conveyance 3%"},
    T.CLASSIC: {"mode": GROSS_DOWN, "amount": "gross",
                "rule": "Basic = gross ÷ 1.5 · House rent 50% of basic"},
    T.RMG: {"mode": BASIC_UP, "amount": "basic",
            "rule": "Basic from the gazetted grade wage · gazetted allowances on top"},
}
# The template percentages (company policy). Basic is the balancing component
# in gross-down mode: it absorbs whatever the rounded parts leave.
STD_BASIC, STD_HRA_OF_BASIC, STD_MED, STD_CONV = Decimal("0.6"), Decimal("0.5"), Decimal("0.07"), Decimal("0.03")
CLASSIC_DIVISOR, CLASSIC_HRA_OF_BASIC = Decimal("1.5"), Decimal("0.5")


def templates_out():
    return [{"id": t.value, "name": t.label, "mode": TEMPLATES[t]["mode"], "amountMeans": TEMPLATES[t]["amount"],
             "rule": TEMPLATES[t]["rule"]} for t in T]


@dataclass
class Built:
    template: str
    components: list  # [(code, amount)] in display order
    rules: list = field(default_factory=list)  # RuleValues a statutory template rests on

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


def grade_floor_rules(grade, book):
    """(basic floor, total floor, grade label) for the grade, or the default
    floor when no grade is recorded."""
    basic = book.labour.get("gradeWageFloors")
    total = book.labour.get("gradeTotalWageFloors")
    if grade and grade in basic.value and grade in total.value:
        return (to_decimal(basic.value[grade]), basic), (to_decimal(total.value[grade]), total), grade
    return ((book.labour.decimal("gradeWageFloorDefault"), book.labour.get("gradeWageFloorDefault")),
            (book.labour.decimal("gradeTotalWageFloorDefault"), book.labour.get("gradeTotalWageFloorDefault")),
            "no grade recorded — the default floor")


def build(template, amount, book, grade=""):
    """The components a template gives for `amount` (gross for a gross-down
    template, basic for RMG). RMG with no amount starts from the grade's
    gazetted basic -- raised, where the grade's gazetted total needs it, to
    the lowest basic whose structure clears both floors. (The drafted G1/G2
    totals do not reconcile with their basics under the gazetted allowances;
    whichever series is wrong, the default must not fall below either.)"""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown salary template {template!r}.")
    if template == T.RMG:
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
            return Built(template, parts(basic), [allowances, floor_rule, total_rule])
        return Built(template, parts(round_to_taka(amount)), [allowances])
    gross = round_to_taka(amount)
    if template == T.STD:
        hra = round_to_taka(round_to_taka(gross * STD_BASIC) * STD_HRA_OF_BASIC)
        med, conv = round_to_taka(gross * STD_MED), round_to_taka(gross * STD_CONV)
        return Built(template, [(C.BASIC, gross - hra - med - conv), (C.HRA, hra), (C.MED, med), (C.CONV, conv)])
    hra = round_to_taka(round_to_taka(gross / CLASSIC_DIVISOR) * CLASSIC_HRA_OF_BASIC)
    return Built(template, [(C.BASIC, gross - hra), (C.HRA, hra)])


def template_input(structure):
    """What a template was given to build `structure`: gross, or basic for RMG."""
    if structure.template == T.RMG:
        return structure.basic
    return structure.gross


# --------------------------------------------------------- effective percent


def percent_of(amount, whole):
    """Back-solved from the amounts on file, to one decimal (§5.1): a document
    says 58.6% of gross when that is what is in force, never the template's 60%."""
    if not whole:
        return None
    return str((to_decimal(amount) * HUNDRED / to_decimal(whole)).quantize(_ONE_DP, rounding=ROUND_HALF_UP))


def components_out(components, gross):
    return [{
        "code": code,
        "name": C(code).label,
        "amount": money_str(amount),
        "percentOfGross": percent_of(amount, gross),
        "basis": f"{percent_of(amount, gross)}% of gross" if gross else None,
    } for code, amount in components]


def structure_out(structure):
    if structure is None:
        return None
    components = [(c.code, c.amount) for c in structure.components.all()]
    gross = sum((a for _, a in components), ZERO)
    known = structure.template in TEMPLATES
    return {
        "uid": str(structure.uid),
        "effectiveFrom": structure.effective_from.isoformat(),
        "effectiveTo": structure.effective_to.isoformat() if structure.effective_to else None,
        "template": structure.template,
        "templateName": T(structure.template).label if known else structure.template,
        "gross": money_str(gross),
        "grossInWords": both_words(gross),
        "basicPercentOfGross": percent_of(sum((a for c, a in components if c == C.BASIC), ZERO), gross),
        "components": components_out(components, gross),
        "revisionType": structure.revision_type or None,
        "method": structure.method or None,
        "reason": structure.reason,
        "reopenedPeriods": structure.reopened_periods,
        "arrears": money_str(structure.arrears),
        "arrearsRun": structure.arrears_run or None,
        "supersededBy": str(structure.superseded_by.uid) if structure.superseded_by_id else None,
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
    structure can clear one and fail the other. Proration is not underpayment,
    so nothing prorated is ever passed in here."""
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


def _save(employee, built, effective_from, *, reason, user, consequence, arrears_run,
          revision_type="", method="", closes=None, history_reason, from_value):
    structure = EmployeeSalaryStructure.objects.create(
        employee=employee, effective_from=effective_from, template=built.template, reason=reason,
        created_by=user, revision_type=revision_type, method=method,
        reopened_periods=consequence["reopenedPeriods"], arrears=consequence["total"],
        arrears_run=arrears_run if consequence["reopenedCount"] else "",
    )
    EmployeeSalaryComponent.objects.bulk_create([
        EmployeeSalaryComponent(structure=structure, code=code, amount=amount, position=position)
        for position, (code, amount) in enumerate(built.components)
    ])
    if closes is not None:
        closes.effective_to = effective_from - timedelta(days=1)
        closes.superseded_by = structure
        closes.save(update_fields=["effective_to", "superseded_by", "updated_at"])
    EmployeeFieldHistory.objects.create(
        employee=employee, field=TrackedFieldChoices.SALARY, date=effective_from,
        from_value=from_value, to_value=_history_value(built.gross, built.basic),
        by=user, by_name=_actor(user), reason=history_reason,
    )
    return structure


def _outcome(built, effective_from, checks, warnings, consequence, *, saved=None, backdated=False, preview=False):
    return {
        "preview": preview,
        "saved": saved is not None,
        "effectiveFrom": effective_from.isoformat(),
        "backdated": backdated,
        "template": built.template,
        "gross": money_str(built.gross),
        "grossInWords": both_words(built.gross),
        "components": components_out(built.components, built.gross),
        "floors": checks,
        "warnings": warnings,
        "consequence": public(consequence),
        "structure": structure_out(saved) if saved is not None else None,
    }


def floor_book(effective_from):
    """The rules a new structure is checked against: those in force on a day
    it will actually be paid. A structure opened in the past is still in force
    today, so today's floors apply to it -- and a joining date from before the
    rule book's first set must not make it unassignable."""
    return rule_book(max(effective_from, clock.today()))


def _floors_or_refuse(employee, built, book, consequence):
    checks = floor_checks(employee.grade, built.basic, built.gross, book)
    failed = [c["message"] for c in checks if not c["passed"]]
    if failed:
        raise SalaryRefused({"amount": failed}, {**public(consequence), "floors": checks})
    return checks


# ---------------------------------------------------------------- assignment


def assign(employee, *, template, amount=None, effective_from=None, arrears_run=None, user=None, preview=False):
    """The first structure. `effective_from` defaults to the date of joining."""
    if latest_structure(employee) is not None:
        raise SalaryRefused({"salary": ["This employee already has a salary structure. Revise it instead."]},
                            status=409)
    effective_from = effective_from or employee.doj
    if effective_from is None:
        raise SalaryRefused({"effective_from": ["An effective date is required: no date of joining is on file."]})
    if employee.doj and effective_from < employee.doj:
        raise SalaryRefused({"effective_from": [
            f"A structure cannot take effect before the date of joining ({employee.doj.isoformat()})."]})
    if employee.separated_on and effective_from > employee.separated_on:
        raise SalaryRefused({"effective_from": [f"The employee separated on {employee.separated_on.isoformat()}."]})
    if amount is None and template != T.RMG:
        raise SalaryRefused({"amount": ["A gross amount is required for this template."]})
    if amount is not None and checked_amount(amount, "amount") <= 0:
        raise SalaryRefused({"amount": ["The amount must be above zero."]})
    book = floor_book(effective_from)
    built = build(template, amount, book, employee.grade)
    consequence = arrears_for(employee, effective_from, built.gross, ZERO, book)
    checks = _floors_or_refuse(employee, built, book, consequence)
    warnings = warnings_for(built)
    if preview:
        return _outcome(built, effective_from, checks, warnings, consequence, preview=True)
    with transaction.atomic():
        # Two first assignments racing: the second waits here, then finds the first.
        Employee.objects.select_for_update().filter(pk=employee.pk).first()
        if latest_structure(employee) is not None:
            raise SalaryRefused({"salary": ["A structure was assigned meanwhile. Reload and revise it."]}, status=409)
        saved = _save(
            employee, built, effective_from, reason="", user=user, consequence=consequence,
            arrears_run=arrears_run or ArrearsRunChoices.NEXT_RUN, from_value="—",
            history_reason=f"Assigned on the {T(template).label} template",
        )
    return _outcome(built, effective_from, checks, warnings, consequence, saved=saved)


# ------------------------------------------------------------------ revision


def revision_default(employee, current, today=None):
    """The start of the next unprocessed period (§5.2) -- never the joining
    date, which silently offered a nine-year backdate -- and after the
    structure being replaced."""
    default = next_unprocessed_period(employee.company, today)
    if current is not None and default <= current.effective_from:
        default = current.effective_from + timedelta(days=1)
    return default


def checked_amount(value, field="value"):
    """A finite decimal within reason, or a refusal naming the field."""
    try:
        amount = to_decimal(value)
    except (TypeError, ValueError):
        raise SalaryRefused({field: ["Send a decimal string, e.g. \"22000\" or \"8.5\"."]}) from None
    if not amount.is_finite() or abs(amount) >= MAX_AMOUNT:
        raise SalaryRefused({field: [f"Must be a finite amount below {group_south_asian(MAX_AMOUNT)}."]})
    return amount


def _revised_amount(method, value, current, template):
    """The new template input (gross, or basic for RMG)."""
    means = TEMPLATES[template]["amount"]
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
            raise SalaryRefused({"method": ["The RMG template is built up from basic: revise it with NEW_BASIC."]})
        return v
    if method == M.NEW_BASIC:
        if means != "basic":
            raise SalaryRefused({"method": ["NEW_BASIC applies to a basic-up (RMG) structure; use NEW_GROSS."]})
        return v
    raise SalaryRefused({"method": [f"Unknown revision method {method!r}."]})


def revise(employee, *, method, value=None, effective_from=None, reason="", template=None, rounding=0,
           revision_type=None, arrears_run=None, user=None, preview=False):
    current = latest_structure(employee)
    if current is None:
        raise SalaryRefused({"salary": ["No salary structure to revise. Assign one first."]}, status=409)
    if current.effective_to is not None:
        raise SalaryRefused({"salary": [
            f"The latest structure closed on {current.effective_to.isoformat()}; there is nothing in force to revise."
        ]}, status=409)
    today = clock.today()
    effective_from = effective_from or revision_default(employee, current, today)
    if effective_from <= current.effective_from:
        raise SalaryRefused({"effective_from": [
            f"A revision must take effect after the structure it replaces, in force from "
            f"{current.effective_from.isoformat()}."]})
    if employee.separated_on and effective_from > employee.separated_on:
        raise SalaryRefused({"effective_from": [
            f"The employee separated on {employee.separated_on.isoformat()}."]})
    if rounding not in ROUNDING_STEPS:
        raise SalaryRefused({"rounding": [f"Rounding must be one of {', '.join(map(str, ROUNDING_STEPS))}."]})

    if method == M.CHANGE_TEMPLATE:
        template = template or (str(value) if value in TEMPLATES else None)
        if template is None:
            raise SalaryRefused({"template": ["Name the template to change to."]})
        if template == current.template:
            raise SalaryRefused({"template": ["The structure is already on this template."]})
        value = None if value in TEMPLATES else value
    template = template or current.template
    if template not in TEMPLATES:
        raise SalaryRefused({"template": [
            "The structure in force was not built from a template; name the template to rebuild it on."]})
    amount = _revised_amount(method, value, current, template)
    if rounding:
        amount = (amount / rounding).quantize(Decimal(1), rounding=ROUND_HALF_UP) * rounding
    if amount <= 0:
        raise SalaryRefused({"value": ["The revised amount must be above zero."]})
    checked_amount(amount)

    book = floor_book(effective_from)
    built = build(template, amount, book, employee.grade)
    if built.same_as(current) and template == current.template:
        raise SalaryRefused({"value": ["The revised structure is the same as the one in force."]})
    old_gross = current.gross
    consequence = arrears_for(employee, effective_from, built.gross, old_gross, book)
    checks = _floors_or_refuse(employee, built, book, consequence)
    warnings = warnings_for(built, old_gross)
    next_open = next_unprocessed_period(employee.company, today)
    backdated = effective_from < next_open
    if backdated:
        warnings.append({"key": "salary.backdated", "message": (
            f"Backdated before {period_label(next_open)}, the next unprocessed period: "
            f"{consequence['reopenedCount']} processed period(s) reopen and {format_money(consequence['total'], places=2)}"
            " of arrears are queued.")})
        try:
            reason = validate_reason(reason)
        except ValidationError as exc:
            raise SalaryRefused(
                {"reason": [f"A backdated revision needs a stated reason. {' '.join(exc.messages)}"]},
                {**public(consequence), "floors": checks, "warnings": warnings},
            ) from None
    reason = (reason or "").strip()
    if preview:
        return _outcome(built, effective_from, checks, warnings, consequence, backdated=backdated, preview=True)
    label = RevisionTypeChoices(revision_type).label if revision_type else M(method).label
    with transaction.atomic():
        locked = EmployeeSalaryStructure.objects.select_for_update().get(pk=current.pk)
        if locked.effective_to is not None:
            raise SalaryRefused({"salary": ["The structure was revised meanwhile. Reload and try again."]}, status=409)
        saved = _save(
            employee, built, effective_from, reason=reason, user=user, consequence=consequence,
            arrears_run=arrears_run or ArrearsRunChoices.NEXT_RUN, revision_type=revision_type or "",
            method=method, closes=locked, history_reason=reason or label,
            from_value=_history_value(old_gross, current.basic),
        )
    return _outcome(built, effective_from, checks, warnings, consequence, saved=saved, backdated=backdated)


def history(employee):
    """Every structure, newest first, including superseded ones (§5.2)."""
    structures = (EmployeeSalaryStructure.objects.filter(employee=employee)
                  .select_related("superseded_by").prefetch_related("components").order_by("-effective_from"))
    return [structure_out(s) for s in structures]
