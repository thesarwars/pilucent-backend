"""The compliance engine (doc §3).

Two lists with different consequences. A **block** keeps the person out of a
payroll run. A **risk** leaves the record incomplete and the run proceeds.
They are never both reported as "blocks payroll" -- doing so flagged every
record and told nobody anything.

Every finding carries a route `{tab, field}` so the client can open the tab and
focus the input; `field` is None only where the UI's route is the tab itself
(the salary structure wizard, the Actions menu). `key` is stable for the client
and for translation; `label` and `fix` are the English defaults.
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from common import clock
from rulebookio.book import rule_book

from ..choices import PaymentMethodChoices
from .predicates import LiabilityUndetermined, has_tax_liability
from .salary import structure_in_force
from .tax import income_year_start
from .validation import mobile_valid, nid_valid

TABS = ("personal", "employment", "salary", "statutory", "tax", "payment", "history", "documents")
SHARE_TOTAL = Decimal("100")
SHARE_TOLERANCE = Decimal("0.001")


def plural(n, one, many):
    """The one place a count meets its noun, so a pill cannot read "1 items"
    beside a summary reading "1 item"."""
    return f"{n} {one if n == 1 else many}"


def share_str(value):
    text = format(Decimal(value).normalize(), "f")
    return text


@dataclass
class Finding:
    key: str
    label: str
    fix: str
    tab: str
    field: str | None


@dataclass
class ComplianceResult:
    blocks: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    tab_states: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "blocks": [asdict(f) for f in self.blocks],
            "risks": [asdict(f) for f in self.risks],
            "tabStates": self.tab_states,
            "summary": {
                "blockCount": len(self.blocks),
                "riskCount": len(self.risks),
                "blocks": plural(len(self.blocks), "hard block", "hard blocks"),
                "risks": plural(len(self.risks), "risk", "risks"),
            },
        }


def evaluate(employee, as_of=None, book=None):
    as_of = as_of or clock.today()
    book = book or rule_book(as_of)
    blocks, risks = [], []

    def block(*args):
        blocks.append(Finding(*args))

    def risk(*args):
        risks.append(Finding(*args))

    pay = employee.payment
    tax_profile = employee.tax_profile
    structure = structure_in_force(employee, as_of)
    cash_reason = (pay.cash_reason or "").strip()

    # ---- hard blocks (§3.1)
    if structure is None:
        block("salary.none", "No salary structure assigned",
              "Payroll cannot run until a structure is assigned.", "salary", None)
    if employee.confirmation and employee.confirmation > as_of:
        block("employment.confirmationFuture", "Confirmation date is in the future",
              "A record confirmed ahead of time cannot be paid as permanent. Correct the date on the Employment tab.",
              "employment", "f-confirmation")
    if employee.settlement_outstanding:
        kind = (employee.separation_type or "separation type not recorded").lower()
        block("salary.settlementOutstanding",
              f"Separated {employee.separated_on.isoformat()} ({kind}) — final settlement outstanding",
              "Run the final settlement before this record leaves the payroll.", "salary", None)
    if pay.method == PaymentMethodChoices.MFS and not mobile_valid(pay.wallet_number):
        block("payment.walletMissing", "Mobile wallet number missing",
              "Add an 11-digit wallet number starting 01.", "payment", "f-wallet")
    if pay.method == PaymentMethodChoices.CASH and not cash_reason:
        block("payment.cashReasonMissing", "Cash payment reason not recorded",
              "Record why this employee is paid outside banking channels.", "payment", "f-cashreason")

    # One predicate, shared with the roster. Unknown is never read as nil.
    liable, undetermined = False, None
    if not tax_profile.etin:
        try:
            liable = has_tax_liability(employee, as_of=as_of, book=book)
        except LiabilityUndetermined as exc:
            undetermined = str(exc)
    if not tax_profile.etin and liable:
        block("tax.etinRequired", "No e-TIN with tax to withhold",
              "Projected liability is above zero, so TDS cannot be lawfully deposited without an e-TIN.",
              "tax", "f-etin")
    if undetermined:
        block("tax.liabilityUndetermined", "No e-TIN, and tax liability cannot be determined",
              f"The rule book has no answer for this date ({undetermined}) Add the e-TIN or publish the rule set.",
              "tax", "f-etin")

    # ---- risks (§3.2)
    if pay.method == PaymentMethodChoices.CASH and cash_reason:
        risk("payment.cash", "Paid in cash",
             "Lawful under the Labour Act, but salary paid outside a banking channel is disallowed to the "
             "employer as a deduction (Income Tax Act 2023, s.55).", "payment", "f-cashreason")
    if pay.method == PaymentMethodChoices.BANK_TRANSFER and not pay.account_number:
        risk("payment.noAccount", "No bank account on file",
             "The disbursement instruction cannot be built until the account number is added on the Payment tab.",
             "payment", "f-accnum")
    if not employee.appointment_letter:
        risk("employment.noAppointmentLetter", "Appointment letter not issued",
             "Generate or upload the letter on the Employment tab.", "employment", "f-appointment")
    if not nid_valid(employee.nid):
        risk("personal.nid", "National ID missing or malformed",
             "NID must be 10, 13 or 17 digits. Needed for the service book, not for a payroll run.",
             "personal", "f-nid")
    nominees = list(employee.nominees.all())
    if not nominees:
        risk("personal.noNominee", "No nominee on file",
             "Required before provident fund or gratuity is paid out.", "personal", "f-nominee")
    else:
        total = sum((n.share for n in nominees), Decimal("0"))
        if abs(total - SHARE_TOTAL) > SHARE_TOLERANCE:
            risk("personal.nomineeShares", "Nominee shares do not total 100%",
                 f"Currently {share_str(total)}%. Adjust the shares before any payout.", "personal", "f-nominee")
    if not tax_profile.etin and not liable and not undetermined:
        risk("tax.noEtin", "No e-TIN on file",
             "Not required while projected liability is nil, but required as soon as it is not.", "tax", "f-etin")
    year_start = income_year_start(as_of)
    if not tax_profile.prior_employer and employee.doj and year_start < employee.doj <= as_of:
        risk("tax.priorEmployer", "Prior-employer income not declared",
             "This employee joined mid-year. Without it the projection under-deducts.", "tax", "f-prior")
    if not employee.name_bn:
        risk("personal.nameBn", "Bangla name missing",
             "Bangla payslips and the leave register will show the English name.", "personal", "f-nameBn")
    if not employee.photo:
        risk("personal.photo", "Photograph missing",
             "Used on the ID card and the service book.", "personal", "f-photo")
    # Document generation is not built yet, so no service book has been generated.
    risk("employment.serviceBook", "Service book not generated",
         "Generate it from the Actions menu.", "employment", None)

    return ComplianceResult(
        blocks=blocks,
        risks=risks,
        tab_states=tab_states(employee, blocks, structure),
    )


def tab_states(employee, blocks, structure):
    """§3.4: complete | partial | empty | blocked. `blocked` wins."""
    blocked_tabs = {f.tab for f in blocks}
    base = {
        "personal": "complete" if nid_valid(employee.nid) and employee.name_bn and employee.father_name else "partial",
        "employment": "complete" if employee.appointment_letter else "partial",
        "salary": "complete" if structure is not None else "empty",
        "statutory": "complete",
        "tax": "partial",
        "payment": "complete",
        "history": "complete",
        "documents": "partial",
    }
    return {tab: "blocked" if tab in blocked_tabs else state for tab, state in base.items()}
