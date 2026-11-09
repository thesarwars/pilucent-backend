"""One document from one stored run line: the figures, the numbered tax working
and the compliance findings. Nothing here recomputes pay: the slip and the run
are one computation because the slip reads what the run stored (§1.4, §1.5)."""

import hashlib
import json
from decimal import Decimal

from common.money import ZERO, money_str, to_decimal
from common.words import amount_in_words, format_money, to_bangla_numerals
from employeeio.services.salary import floor_checks
from rulebookio.book import RuleBookError, RuleSetView

FOUR = Decimal("0.0001")
BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"
# §4.3, only for a line computed before the projection recorded what it read.
FALLBACK_RULES = ("slabs", "employmentExemptionFraction", "employmentExemptionCeiling", "minimumTax")
PERQUISITE_WARN_PCT = Decimal(80)


class PinnedBook:
    """The rule sets the run pinned, in the shape `floor_checks` reads."""

    def __init__(self, run):
        self.tax = RuleSetView(run.tax_card)
        self.labour = RuleSetView(run.rule_set)


def amount(x):
    return to_decimal(x if x is not None else 0)


def _taka(x):
    return format_money(x, places=0)


def _taka_bn(x):
    return format_money(x, "bn", places=0)


def _sum(rows):
    return sum((amount(r["amount"]) for r in rows), ZERO)


# ---------------------------------------------------------------- the working
LABELS_BN = {
    "employmentIncome": "চাকরি থেকে মোট আয়", "exemption": "চাকরির আয়ে অব্যাহতি", "taxable": "করযোগ্য আয়",
    "threshold": "করমুক্ত সীমা", "slabTax": "ধাপ অনুযায়ী কর", "rebate": "বিনিয়োগ রেয়াত", "afterRebate": "রেয়াতের পর কর",
    "minimum": "ন্যূনতম কর", "liability": "বার্ষিক করদায়", "ytdDeducted": "এ পর্যন্ত কর্তিত",
    "remaining": "অবশিষ্ট দায়", "periodDeduction": "এই মাসের কর",
}
LABELS = {
    "employmentIncome": "Total income from employment", "exemption": "Employment exemption",
    "taxable": "Taxable income", "threshold": "Tax-free threshold", "slabTax": "Tax on the slabs",
    "rebate": "Investment rebate", "afterRebate": "Tax after rebate", "minimum": "Minimum tax",
    "liability": "Annual liability", "ytdDeducted": "Deducted to date", "remaining": "Left to withhold",
    "periodDeduction": "This period",
}


def derivation(d):
    """§4.4, from the projection the run stored. A stage number appears once
    (a result within it is `isResult`), and a stage that did not apply leaves
    a gap: 7 without minimum tax, 9 with nothing deducted yet."""
    if not d or not d.get("available"):
        return []
    steps = []

    def add(stage, key, value, basis, result=False):
        row = {"stage": stage, "key": key, "label": LABELS[key], "labelBn": LABELS_BN[key],
               "amount": money_str(amount(value)), "basis": basis or ""}
        if result:
            row["isResult"] = True
        steps.append(row)

    def fig(stage, key, result=False):
        add(stage, key, d[key]["value"], d[key]["basis"], result)

    fig(1, "employmentIncome")
    if "exemption" in d:  # a non-resident is taxed flat: 2 to 7 do not apply
        fig(2, "exemption")
        fig(2, "taxable", result=True)
        fig(3, "threshold")
        fig(4, "slabTax")
        fig(5, "rebate")
        fig(6, "afterRebate")
        if amount(d["liability"]["value"]) > amount(d["afterRebate"]["value"]):
            add(7, "minimum", d["liability"]["value"], d["liability"]["basis"])
    fig(8, "liability")
    ytd = amount(d["ytdDeducted"]["value"])
    if ytd > 0:
        fig(9, "ytdDeducted")
    left = max(ZERO, amount(d["liability"]["value"]) - ytd)
    add(10, "remaining", left, f"Spread over {d['remainingPeriods']['value']} remaining period(s)")
    fig(10, "periodDeduction", result=True)
    return steps


# ------------------------------------------------------------------- the bases
class Flags:
    """Each line's bases from the component version it pins, cached for a run."""

    def __init__(self, company):
        self.company, self.seen = company, {}

    def of(self, code, version):
        from paylibio.services.library import flags_of

        key = (code, version)
        if key not in self.seen:
            self.seen[key] = flags_of(self.company, code, version)
        return self.seen[key]


def bases(line, flags):
    """(wages base, PF base, annual perquisites in the s.55 ceiling), from the
    earnings the run paid and the flags their structure pinned."""
    versions = {c.code: c.component_version for c in line.structure.components.all()} if line.structure_id else {}
    wages = pf = perq = ZERO
    for e in line.earnings_json or []:
        if e["code"] == "OT":
            wages += amount(e["amount"])  # overtime is wages (s.2(45))
            continue
        f = flags.of(e["code"], versions.get(e["code"]))
        if f["in_wages_base"]:
            wages += amount(e["amount"])
        if f["in_pf_base"]:
            pf += amount(e["amount"])
        if f["in_perquisite_ceiling"]:
            perq += amount(e["monthly"]) * 12
    return wages, pf, perq


def notional_perquisites(d):
    """A year's vehicle and accommodation: taxable, never wages."""
    if not d or not d.get("available"):
        return ZERO
    return amount(d["perquisites"]["value"])


# ----------------------------------------------------------------- compliance
def _finding(severity, code, message, citation, *, bn=None, consequence=None):
    return {"severity": severity, "code": code, "message": message, "message_bn": bn, "citation": citation,
            "consequence": consequence}


def unverified_rules(line, book):
    """§4.3. The rules this computation actually read, as the run's pinned sets
    state them today: a signed-off rule clears the gate on regeneration."""
    d = line.tax_derivation_json or {}
    names = list(d.get("rulesRead") or [f"tax.{book.tax.version}.{p}" for p in FALLBACK_RULES])
    if line.ot_amount and line.ot_amount > 0:
        names.append(f"labour.{book.labour.version}.overtimeMultiplier")
    out = []
    for name in dict.fromkeys(names):
        view = next((v for v in (book.tax, book.labour) if name.startswith(f"{v.family.lower()}.{v.version}.")), None)
        try:
            rv = view.get(name.split(f"{view.version}.", 1)[1]) if view else None
        except RuleBookError:
            rv = None
        if rv is None:
            out.append(f"{name} (missing)")
        elif not rv.production_safe:
            out.append(f"{name} ({rv.confidence.lower()})")
    return out


def compliance_for(line, employee, book, *, wages_base, annual_perquisites, total_deductions, ceiling):
    """§4.2. Floors compare the monthly RATE the run stored, so a part month
    is never reported as underpaid, and proration never masks a low rate."""
    found = []
    earnings = line.earnings_json or []
    if employee.classification == "WORKER":
        basic = next((amount(e["monthly"]) for e in earnings if e["code"] == "BASIC"), ZERO)
        full_gross = sum((amount(e["monthly"]) for e in earnings if e["monthly"] is not None), ZERO)
        for c in floor_checks(employee.grade, basic, full_gross, book):
            if c["passed"]:
                continue
            if c["kind"] == "basic":
                found.append(_finding(
                    BLOCK, "MIN_WAGE_BASIC", c["message"], "Bangladesh Labour Act 2006, s.289(1)",
                    bn=f"মূল বেতন {_taka_bn(basic)} গ্রেডের গেজেটভুক্ত ন্যূনতম {_taka_bn(amount(c['floor']))}-এর কম। "
                       "ন্যূনতম মজুরি না দিলে ৫০,০০০ থেকে ১,০০,০০০ টাকা জরিমানা ও এক বছর পর্যন্ত কারাদণ্ড হতে পারে।",
                    consequence="This slip cannot be issued until the rate clears the floor."))
            else:
                found.append(_finding(
                    BLOCK, "MIN_WAGE_TOTAL", c["message"], c["citation"] or "Minimum Wages Board gazette",
                    bn=f"মোট মজুরি {_taka_bn(full_gross)} গ্রেডের গেজেটভুক্ত মোট মজুরি {_taka_bn(amount(c['floor']))}-এর কম।",
                    consequence="This slip cannot be issued until the rate clears the floor."))

    rules = unverified_rules(line, book)
    if rules:
        found.append(_finding(
            BLOCK, "UNVERIFIED_RULE",
            f"Depends on {len(rules)} statutory value(s) not signed off against the Bangla gazette: "
            f"{', '.join(rules)}. Display and simulation only.",
            "Rule book confidence gate",
            bn=f"{to_bangla_numerals(len(rules))}টি বিধিবদ্ধ মান বাংলা গেজেটের সঙ্গে যাচাই করা হয়নি: {', '.join(rules)}। "
               "শুধু প্রদর্শন ও অনুকরণের জন্য।",
            consequence="This slip cannot be issued until the rule is verified."))

    if ceiling is not None and total_deductions > ceiling:
        found.append(_finding(
            BLOCK, "DEDUCTION_CEILING",
            f"Deductions of {_taka(total_deductions)} exceed the ceiling of {_taka(ceiling)} on wages of "
            f"{_taka(wages_base)}.",
            "Bangladesh Labour Act 2006, s.125",
            bn=f"কর্তন {_taka_bn(total_deductions)}, {_taka_bn(wages_base)} মজুরির ওপর সীমা {_taka_bn(ceiling)} অতিক্রম করেছে।",
            consequence="This slip cannot be issued until the deductions are within the ceiling."))
    for d in line.deductions_json or []:
        if d.get("deferred"):
            found.append(_finding(WARN, "DEDUCTION_DEFERRED", f"{d['label']} was deferred. {d['note']}",
                                  d.get("citation") or "Bangladesh Labour Act 2006, s.125",
                                  bn=f"{d['bn']} স্থগিত করা হয়েছে; পরের মাসে সমন্বয় হবে।",
                                  consequence="It is carried to the next period."))

    rv = book.tax.get("perquisiteCeilingPerEmployee")
    if rv.value is not None and annual_perquisites > 0:
        limit = rv.decimal
        pct = (annual_perquisites * 100 / limit).quantize(Decimal("0.1"))
        citation = "Income Tax Act 2023, s.55"
        if annual_perquisites > limit:
            found.append(_finding(
                WARN, "PERQUISITE_BREACH",
                f"Perquisites of {_taka(annual_perquisites)} exceed the {_taka(limit)} ceiling by "
                f"{_taka(annual_perquisites - limit)}, disallowed to the employer.", citation,
                bn=f"সুবিধাদি {_taka_bn(annual_perquisites)}, {_taka_bn(limit)} সীমা অতিক্রম করেছে; অতিরিক্ত অংশ নিয়োগকর্তার "
                   "খরচ হিসেবে অননুমোদিত।",
                consequence="The excess is disallowed to the employer; the employee's tax is unaffected."))
        elif pct >= PERQUISITE_WARN_PCT:
            found.append(_finding(
                WARN, "PERQUISITE_80PCT",
                f"Perquisites of {_taka(annual_perquisites)} are {pct}% of the {_taka(limit)} ceiling. The excess "
                "is disallowed to the employer; the employee's tax is unaffected.", citation,
                bn=f"সুবিধাদি {_taka_bn(annual_perquisites)}, {_taka_bn(limit)} সীমার {to_bangla_numerals(pct)}%। অতিরিক্ত অংশ "
                   "নিয়োগকর্তার খরচ হিসেবে অননুমোদিত; কর্মীর করে প্রভাব নেই।",
                consequence="Raised at 80% rather than at breach: by then the year's packages are committed."))

    if line.payment_method == "CASH":
        found.append(_finding(
            WARN, "CASH_PAYMENT", "Lawful under the Labour Act, but salary outside a banking channel is disallowed "
                                  "to the employer.", "Income Tax Act 2023, s.55",
            bn="শ্রম আইনে বৈধ, তবে ব্যাংকিং মাধ্যমের বাইরে দেওয়া বেতন নিয়োগকর্তার খরচ হিসেবে অননুমোদিত।",
            consequence="The salary is disallowed to the employer."))
    if not getattr(employee.tax_profile, "etin", ""):
        found.append(_finding(WARN, "NO_ETIN", "No e-TIN on file.", "Income Tax Act 2023",
                              bn="ই-টিআইএন নথিভুক্ত নেই।"))
    if line.proration_factor is not None and line.proration_factor < 1:
        why = ("joined in the period" if line.join_date_in_period else
               "left in the period" if line.leave_date_in_period else "days lost in the period")
        found.append(_finding(
            INFO, "PRORATED", f"Paid for {line.payable_days} of {line.calendar_days} days — {why}.", "—",
            bn=f"{to_bangla_numerals(line.calendar_days)} দিনের মধ্যে {to_bangla_numerals(line.payable_days)} দিনের মজুরি।"))
    return found


# ------------------------------------------------------------------ the hashes
def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def document_hash(doc):
    """§4.6."""
    payload = {"earnings": doc.earnings_json, "deductions": doc.deductions_json, "derivation": doc.derivation_json,
               "facts": doc.facts_json, "employer": doc.employer_json, "netPay": money_str(doc.net_pay),
               "netInWords": doc.net_in_words, "ruleSet": str(doc.rule_set.uid), "taxCard": str(doc.tax_card.uid),
               "engineVersion": doc.engine_version}
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def register_hash(docs):
    rows = sorted(f"{d.document_no}:{d.document_hash}" for d in docs)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def words(net):
    return amount_in_words(net, "en"), amount_in_words(net, "bn")
