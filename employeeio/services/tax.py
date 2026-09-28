"""Income tax projection (doc §7.5).

A slab walk that returns its own numbered trace, so the figure can be argued
with. It computes forward from income; it never back-solves tax from
`gross - net - pf` (§1.6).

The critical defect of §2.5: thresholds are keyed off taxpayer *flags*, not the
category string. Passing the category alone once assessed everybody on the
GENERAL threshold. `flags_for_category` is the one place a category becomes
flags, and `threshold_rule` is the one place flags become a threshold.

Rounding points (common.money): the exemption, the slab-tax total, the rebate,
the non-resident flat tax and the per-period deduction are each rounded to the
taka where the trace says so. Band amounts inside the walk are not.
"""

from dataclasses import dataclass, field
from datetime import date

from common import clock
from common.money import ZERO, apply_rate, money_str, round_to_taka, to_decimal
from rulebookio.book import rule_book
from rulebookio.choices import ConfidenceChoices

from ..choices import ClassificationChoices, GenderChoices, TaxpayerCategoryChoices, VehicleChoices
from .salary import structure_in_force

CONFIDENCE_ORDER = [
    ConfidenceChoices.DRAFTED,
    ConfidenceChoices.DISPUTED,
    ConfidenceChoices.CORROBORATED,
    ConfidenceChoices.VERIFIED,
    ConfidenceChoices.LIVE,
]
SENIOR_AGE = 65
INCOME_YEAR_START_MONTH = 7  # the income year runs July to June
PERIODS_PER_YEAR = 12


@dataclass(frozen=True)
class TaxpayerFlags:
    woman: bool = False
    disabled: bool = False
    third_gender: bool = False
    # The age the category asserts (65 for SENIOR_CITIZEN_65_PLUS), not the age
    # from the date of birth: the dob only feeds `suggest_category`, which is
    # never auto-applied.
    age: int | None = None
    gazetted_freedom_fighter: bool = False
    non_resident: bool = False

    def as_dict(self):
        return {
            "woman": self.woman,
            "disabled": self.disabled,
            "thirdGender": self.third_gender,
            "age": self.age,
            "gazettedFreedomFighter": self.gazetted_freedom_fighter,
            "nonResident": self.non_resident,
        }


def flags_for_category(category):
    """The one translation from taxpayer category to engine flags."""
    C = TaxpayerCategoryChoices
    return {
        C.GENERAL: TaxpayerFlags(),
        C.FEMALE: TaxpayerFlags(woman=True),
        C.SENIOR_CITIZEN_65_PLUS: TaxpayerFlags(age=SENIOR_AGE),
        C.PERSON_WITH_DISABILITY: TaxpayerFlags(disabled=True),
        C.THIRD_GENDER: TaxpayerFlags(third_gender=True),
        C.WAR_WOUNDED_FREEDOM_FIGHTER: TaxpayerFlags(gazetted_freedom_fighter=True),
        C.NON_RESIDENT_FOREIGN: TaxpayerFlags(non_resident=True),
    }[category]


def threshold_rule(flags, book):
    """The tax-free threshold the flags entitle the taxpayer to.

    Where more than one flag applies, the law gives the higher threshold.
    """
    C = TaxpayerCategoryChoices
    applicable = [C.GENERAL]
    if flags.woman:
        applicable.append(C.FEMALE)
    if flags.age is not None and flags.age >= SENIOR_AGE:
        applicable.append(C.SENIOR_CITIZEN_65_PLUS)
    if flags.disabled:
        applicable.append(C.PERSON_WITH_DISABILITY)
    if flags.third_gender:
        applicable.append(C.THIRD_GENDER)
    if flags.gazetted_freedom_fighter:
        applicable.append(C.WAR_WOUNDED_FREEDOM_FIGHTER)
    rules = [book.tax.get(f"taxFreeThresholds.{c}") for c in applicable]
    return max(rules, key=lambda rv: rv.decimal)


def completed_years(born, on):
    if born is None:
        return None
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def suggest_category(employee, on=None):
    """§2.5: a suggestion with one-click accept, never applied automatically --
    disability and freedom-fighter status are not derivable from gender or age."""
    age = completed_years(employee.dob, on or clock.today())
    if age is not None and age >= SENIOR_AGE:
        return TaxpayerCategoryChoices.SENIOR_CITIZEN_65_PLUS
    if employee.gender == GenderChoices.FEMALE:
        return TaxpayerCategoryChoices.FEMALE
    if employee.gender == GenderChoices.THIRD_GENDER:
        return TaxpayerCategoryChoices.THIRD_GENDER
    return TaxpayerCategoryChoices.GENERAL


def income_year_start(on):
    year = on.year if on.month >= INCOME_YEAR_START_MONTH else on.year - 1
    return date(year, INCOME_YEAR_START_MONTH, 1)


def periods_elapsed(on):
    """Whole months of the income year completed before `on`'s month."""
    start = income_year_start(on)
    return (on.year - start.year) * 12 + on.month - start.month


def lowest_confidence(rules):
    return min((rv.confidence for rv in rules), key=CONFIDENCE_ORDER.index)


@dataclass
class Figure:
    """One step of the projection. `rules` are the statutory values this step
    applies (its citation); `inputs` are the earlier figures it is computed
    from. Confidence runs through both: a liability computed from a
    CORROBORATED bonus count is CORROBORATED, whatever its own step cites."""

    value: object
    basis: str
    rules: list = field(default_factory=list)
    inputs: list = field(default_factory=list)

    @property
    def lineage(self):
        seen = {}
        for rv in self.rules + [rv for f in self.inputs for rv in f.lineage]:
            seen.setdefault(rv.rule, rv)
        return list(seen.values())

    @property
    def confidence(self):
        # A figure resting on no statutory value at all (the salary on file)
        # is as good as its inputs: it does not lower anything.
        lineage = self.lineage
        return lowest_confidence(lineage) if lineage else ConfidenceChoices.LIVE

    @property
    def citation(self):
        cites = [rv.citation for rv in self.rules if rv.citation]
        return " · ".join(dict.fromkeys(cites)) or None

    def as_dict(self, money=True):
        return {
            "value": money_str(self.value) if money else self.value,
            "basis": self.basis,
            "citation": self.citation,
            "confidence": self.confidence,
        }


@dataclass
class TaxProjection:
    available: bool
    as_of: date
    reason: str = ""
    rule_set: str = ""
    category: str = ""
    flags: TaxpayerFlags | None = None
    figures: dict = field(default_factory=dict)
    slab_walk: list = field(default_factory=list)
    trace: list = field(default_factory=list)

    @property
    def liability(self):
        return self.figures["liability"].value if self.available else None

    @property
    def rules(self):
        return [rv for f in self.figures.values() for rv in f.rules]

    @property
    def confidence(self):
        return lowest_confidence(self.rules) if self.rules else None

    def as_dict(self):
        if not self.available:
            return {"available": False, "asOf": self.as_of.isoformat(), "reason": self.reason}
        counts = {"periodsElapsed", "remainingPeriods"}
        return {
            "available": True,
            "asOf": self.as_of.isoformat(),
            "ruleSet": self.rule_set,
            "category": self.category,
            "flags": self.flags.as_dict(),
            "confidence": self.confidence,
            "productionSafe": all(rv.production_safe for rv in self.rules),
            **{key: fig.as_dict(money=key not in counts) for key, fig in self.figures.items()},
            "slabWalk": self.slab_walk,
            "trace": self.trace,
        }


def _perquisite_monthly(tax_profile, book):
    rules, amount, parts = [], ZERO, []
    if tax_profile.vehicle == VehicleChoices.UPTO_2500:
        rv = book.tax.get("perquisiteVehicleUpTo2500cc")
        rules.append(rv)
        amount += rv.decimal
        parts.append("company vehicle up to 2500cc")
    elif tax_profile.vehicle == VehicleChoices.ABOVE_2500:
        rv = book.tax.get("perquisiteVehicleAbove2500cc")
        rules.append(rv)
        amount += rv.decimal
        parts.append("company vehicle above 2500cc")
    if tax_profile.accommodation and tax_profile.accommodation_value:
        amount += to_decimal(tax_profile.accommodation_value)
        parts.append("rent-free accommodation")
    return amount, rules, " + ".join(parts) or "none"


def project(employee, as_of=None, book=None, ytd_deducted=ZERO):
    """Project the income-year liability and this period's deduction."""
    as_of = as_of or clock.today()
    structure = structure_in_force(employee, as_of)
    if structure is None:
        return TaxProjection(
            available=False, as_of=as_of,
            reason=f"No salary structure is in force on {as_of.isoformat()}.",
        )
    book = book or rule_book(as_of)
    tax_profile = employee.tax_profile
    flags = flags_for_category(tax_profile.category)
    figures, trace = {}, []

    def step(key, label, figure):
        figures[key] = figure
        trace.append({"n": len(trace) + 1, "step": label, "key": key, **figure.as_dict(
            money=key not in {"periodsElapsed", "remainingPeriods"})})
        return figure.value

    monthly_gross = structure.gross
    basic = structure.basic
    annual_salary = step("annualSalary", "Annual salary", Figure(
        monthly_gross * 12, f"Monthly gross {money_str(monthly_gross)} × 12"))

    if employee.classification == ClassificationChoices.WORKER:
        per_year = book.labour.get("festivalBonusesPerYear")
        bonuses = step("bonuses", "Festival bonuses", Figure(
            basic * per_year.decimal,
            f"Basic {money_str(basic)} × {per_year.value} festival bonuses, fully taxable",
            [per_year, book.tax.get("festivalBonusTaxable")]))
    else:
        bonuses = step("bonuses", "Festival bonuses", Figure(
            ZERO, "Not a worker: no statutory festival bonus is projected"))

    perq_monthly, perq_rules, perq_basis = _perquisite_monthly(tax_profile, book)
    perquisites = step("perquisites", "Perquisites", Figure(
        perq_monthly * 12, f"{money_str(perq_monthly)} a month ({perq_basis}) × 12", perq_rules))

    income = step("employmentIncome", "Employment income", Figure(
        annual_salary + bonuses + perquisites, "Annual salary + festival bonuses + perquisites",
        inputs=[figures["annualSalary"], figures["bonuses"], figures["perquisites"]]))

    if flags.non_resident:
        rate = book.tax.get("nonResidentForeignFlatRate")
        category_rule = book.tax.get(f"taxFreeThresholds.{TaxpayerCategoryChoices.NON_RESIDENT_FOREIGN}")
        liability = step("liability", "Annual liability", Figure(
            round_to_taka(income * rate.decimal),
            f"Non-resident foreign: flat {rate.value} on employment income, rounded to the taka; "
            "the slab walk, exemption, rebate and minimum tax do not apply",
            [rate, category_rule], [figures["employmentIncome"]]))
    else:
        fraction = book.tax.get("employmentExemptionFraction")
        ceiling = book.tax.get("employmentExemptionCeiling")
        exemption = step("exemption", "Employment exemption", Figure(
            min(round_to_taka(apply_rate(income, fraction.value)), ceiling.decimal),
            f"Lower of {fraction.value} of employment income (rounded to the taka) or {money_str(ceiling.decimal)}",
            [fraction, ceiling], [figures["employmentIncome"]]))
        taxable = step("taxable", "Taxable income", Figure(
            max(ZERO, income - exemption), "Employment income − exemption, not below zero",
            inputs=[figures["employmentIncome"], figures["exemption"]]))

        base_rule = threshold_rule(flags, book)
        addition = book.tax.get("disabledChildAddition")
        children = tax_profile.disabled_children
        threshold_rules = [base_rule] + ([addition] if children else [])
        threshold = step("threshold", "Tax-free threshold", Figure(
            base_rule.decimal + children * addition.decimal,
            f"{base_rule.rule.rsplit('.', 1)[-1]} threshold {money_str(base_rule.decimal)}"
            + (f" + {children} disabled child(ren) × {money_str(addition.decimal)}" if children else ""),
            threshold_rules))

        slabs = book.tax.get("slabs")
        remaining, walked, band_total = max(ZERO, taxable - threshold), [], ZERO
        for n, band in enumerate(slabs.value, 1):
            if remaining <= 0:
                break
            width = remaining if band["width"] is None else min(remaining, to_decimal(band["width"]))
            rate = to_decimal(band["rate"])
            amount = width * rate
            band_total += amount
            walked.append({"band": n, "income": money_str(width), "rate": band["rate"], "tax": money_str(amount)})
            remaining -= width
        slab_tax = step("slabTax", "Slab tax", Figure(
            round_to_taka(band_total),
            f"Slab walk over taxable income above the threshold, {len(walked)} band(s), total rounded to the taka",
            [slabs], [figures["taxable"], figures["threshold"]]))

        rate_inv = book.tax.get("rebateRateOnInvestment")
        rate_taxable = book.tax.get("rebateRateOnTaxableIncome")
        rebate_cap = book.tax.get("rebateCeiling")
        invested = sum((i.amount for i in employee.investments.all() if i.proof), ZERO)
        rebate = step("rebate", "Investment rebate", Figure(
            round_to_taka(min(invested * rate_inv.decimal, taxable * rate_taxable.decimal, rebate_cap.decimal)),
            f"Lowest of {rate_inv.value} × evidenced investment {money_str(invested)}, "
            f"{rate_taxable.value} × taxable income, or {money_str(rebate_cap.decimal)}; rounded to the taka",
            [rate_inv, rate_taxable, rebate_cap], [figures["taxable"]]))
        after_rebate = step("afterRebate", "Tax after rebate", Figure(
            max(ZERO, slab_tax - rebate), "Slab tax − rebate, not below zero",
            inputs=[figures["slabTax"], figures["rebate"]]))

        minimum = book.tax.get("minimumTax")
        min_applies = taxable > threshold and after_rebate < minimum.decimal
        liability = step("liability", "Annual liability", Figure(
            minimum.decimal if min_applies else after_rebate,
            "Minimum tax applies: taxable income is above the threshold and tax after rebate is below the floor"
            if min_applies else "Tax after rebate",
            [minimum] if min_applies else [], [figures["afterRebate"], figures["taxable"], figures["threshold"]]))

    ytd = step("ytdDeducted", "Deducted to date", Figure(
        to_decimal(ytd_deducted), "Tax deducted so far this income year"))
    elapsed = periods_elapsed(as_of)
    step("periodsElapsed", "Periods elapsed", Figure(
        elapsed, f"Whole months since {income_year_start(as_of).isoformat()} (the income year runs July to June)"))
    remaining_periods = max(1, PERIODS_PER_YEAR - elapsed)
    step("remainingPeriods", "Remaining periods", Figure(
        remaining_periods, f"{PERIODS_PER_YEAR} − periods elapsed, at least 1"))
    step("periodDeduction", "This period", Figure(
        max(ZERO, round_to_taka((liability - ytd) / remaining_periods)),
        "(Annual liability − deducted to date) ÷ remaining periods, rounded to the taka, not below zero",
        inputs=[figures["liability"]]))

    return TaxProjection(
        available=True,
        as_of=as_of,
        rule_set=book.tax.version,
        category=tax_profile.category,
        flags=flags,
        figures=figures,
        slab_walk=walked if not flags.non_resident else [],
        trace=trace,
    )
