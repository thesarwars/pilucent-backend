"""Find, classify and (later) repair journal entries whose debits differ from
their credits.

Production held **297 unbalanced entries of 1,541** when the nine writers that
produced them were fixed on 2026-08-12, and a fleet imbalance of 1,541,988.352.
Thirteen of sixty companies fail `A = L + E + NI` by exactly their own ledger's
debit-credit difference: the statements do not disagree with the ledger, the
ledger disagrees with itself.

Fixing the writers stopped the number growing -- seven entries created after the
deploy, across five document kinds, none unbalanced -- but nothing repairs
history by itself. That is what this command is for.

**Report mode is the whole of this first version.** It writes nothing. Deciding
what to do about an entry is a judgement that wants a human looking at a list,
not a heuristic running unattended over a production ledger, and the list is
worth having before anyone commits to a repair strategy.

## Why the census understates the problem

`debits != credits` finds only entries whose *journal* is wrong. It cannot see
the other class this work turned up: a leg written correctly while the account's
stored `opening_balance` moved by something else. The expense importer did that
for months -- it moved the bulk inventory balance by the whole document net of
tax while its connectors moved by each line -- and the journal was impeccable
throughout. That class is what puts company 165's A/R at 4,752,073 stored
against 2,352,078 posted, and no query in this command finds it. Use
`audit_ledger` for that half.

## Repair strategies, in order of preference

**Reverse and repost.** Where the source document survives and its module has a
reposting path, the strongest repair is to unwind what was posted and post it
again through the now-correct code. The entry that results is the entry a
freshly entered document would produce, which is the property we actually want.
`sale_posting.reverse_sale_postings` + `post_sale_document` is the model, and
`salary_process_journal_entry.unwind_existing_payroll_posting` is the payroll
equivalent.

**Correcting entry.** Where the document is gone or no repost path exists, book
the difference to a clearly labelled suspense account, dated and tagged, so an
accountant disposes of it deliberately rather than finding it years later.

**Leave it and say so.** Where the missing leg's counterparty cannot be
inferred, inventing one is worse than a measured, disclosed hole. A sale whose
product's income account was deleted has an inferable *amount* and an
uninferable *account*.

Nothing here mutates an existing `JournalEntryConnector`. Repair is additive.
"""

import csv
import sys
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from journalio.models import JournalEntry


TOLERANCE = Decimal("0.01")

# Every source-document FK on JournalEntry, and whether that module has a path
# that could repost the document through the corrected writers.
#
# `repost` is a claim about the module, not about the row -- whether the row is
# actually repostable also needs its document to still exist, which is what the
# report checks per entry.
SOURCE_FIELDS = [
    ("sale", "salesio.Sale", True),
    ("credit_note", "creditnoteio.CreditNote", False),
    ("purchase", "purchaseio.Purchase", False),
    ("expense", "purchaseio.Expense", False),
    ("payroll_salary", "payrollio.PayrollSalaryProcess", True),
    ("bank_deposit", "transactionio.BankDeposit", False),
    ("sale_payment_receive", "salesio.SalePaymentReceive", False),
    ("purchase_payment", "purchaseio.PurchasePayment", False),
    ("pay_bill", "purchaseio.PayBill", False),
    ("stock_adjustment", "stockio.StockAdjustment", False),
    ("bank_reconciliation", "transactionio.BankReconciliation", False),
    ("tax_payment", "payrollio.TaxCenterPayMethod", False),
    ("sales_tax", "salesio.SalesTax", False),
    ("product", "productio.Product", False),
]

# What the fixed writer for each kind now does about the leg that used to go
# missing. Carried here so the report says WHY an entry is short rather than
# only that it is, and so whoever reads it can sanity-check the diagnosis
# against the entry's actual legs.
DIAGNOSIS = {
    "SALE": (
        "revenue recognised from consumed FIFO stock rather than from the "
        "invoice, so an out-of-stock or service line credited nothing (2c4054c2)"
    ),
    "SALE_RECEPT": (
        "declared header tax exceeded what the tax-flagged lines accounted for, "
        "and the shortfall was logged and discarded (98dfc0d1, 624929e9)"
    ),
    "CREDIT_NOTE": (
        "header tax never reached the ledger, and/or the revenue reversal was "
        "skipped for a product with no income account (fb21a01e, 28faf2e5)"
    ),
    "PAYROLL_SALARY_PROCESS": (
        "tax withheld from the employee reached no liability account -- "
        "unmapped MEDICARE_ADDITIONAL, a null work location, a second state, "
        "or a renamed account (042505de)"
    ),
    "REFUND_RECEIPT": (
        "inclusive refund reversed revenue gross and debited the tax back as "
        "well, removing it twice (91a711db)"
    ),
    "BANK_DEPOSIT": (
        "both legs posted on the same side because the rule engine hard-coded "
        "the action instead of resolving it from the side (e7f2f8de)"
    ),
    "CHART_OF_ACCOUNT": (
        "opening balance stored with no Opening Balance Equity offset, or the "
        "same bank-rule leg-direction fault (e7f2f8de, gaps #3/#4)"
    ),
    "EXPENSE": (
        "funding credit sized from an ex-tax total while the tax was debited on "
        "top (19139eeb)"
    ),
    "PURCHASE": (
        "non-stock line skipped its cost debit along with the inventory block "
        "(4ab99db3)"
    ),
}


class Command(BaseCommand):
    help = "Report journal entries whose debits and credits disagree."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", type=int, default=None,
            help="Restrict to one company id.",
        )
        parser.add_argument(
            "--kind", default=None,
            help="Restrict to one JournalEntry kind, e.g. SALE.",
        )
        parser.add_argument(
            "--csv", default=None,
            help="Write the per-entry rows to this path instead of stdout.",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Stop after N unbalanced entries (0 = no limit).",
        )

    # -- the scan ----------------------------------------------------------

    def unbalanced(self, options):
        """Yield `(entry, debit, credit, diff)` for every entry that is short.

        Deliberately a per-entry aggregate rather than one clever query: the
        set is small (297 of 1,541), it runs once, and being able to read it
        matters more here than the round trips. Production RDS is capped at 79
        connections, so this stays single-threaded on purpose.
        """
        queryset = JournalEntry.objects.exclude(status="REMOVED")
        if options["company"]:
            queryset = queryset.filter(company_id=options["company"])
        if options["kind"]:
            queryset = queryset.filter(kind=options["kind"])

        found = 0
        for entry in queryset.select_related("company").iterator(chunk_size=200):
            totals = entry.journalentryconnector_set.aggregate(
                d=Sum("debit"), c=Sum("credit")
            )
            debit = Decimal(totals["d"] or 0)
            credit = Decimal(totals["c"] or 0)
            diff = debit - credit
            if abs(diff) <= TOLERANCE:
                continue
            yield entry, debit, credit, diff
            found += 1
            if options["limit"] and found >= options["limit"]:
                return

    def source_of(self, entry):
        """`(field, label, document_survives, repost_path_exists)`.

        `JournalEntry`'s source FKs are all CASCADE, so a surviving row means
        the document survives -- but the FK can also simply be null, which is
        its own finding: an entry with no source cannot be reposted from
        anything and can only ever take a correcting entry.
        """
        for field, model_label, has_repost in SOURCE_FIELDS:
            if getattr(entry, f"{field}_id", None):
                return field, model_label, True, has_repost
        return None, None, False, False

    def classify(self, entry, diff, survives, has_repost):
        """The action this entry can take, and whether a human must decide.

        Three outcomes, and the middle one is the honest answer for most of
        this list rather than a cop-out: the amount is known, the account it
        belongs to is not, and guessing at it would put a number somewhere no
        one can defend.
        """
        if not survives:
            return "CORRECTING_ENTRY", "no source document -- nothing to repost from"
        if has_repost:
            return "REVERSE_AND_REPOST", "source survives and its module can repost"
        return (
            "CORRECTING_ENTRY",
            "source survives but its module has no repost path",
        )

    # -- output ------------------------------------------------------------

    def handle(self, *args, **options):
        rows = []
        by_kind = defaultdict(lambda: [0, Decimal("0")])
        by_action = defaultdict(int)
        total_diff = Decimal("0")

        for entry, debit, credit, diff in self.unbalanced(options):
            field, model_label, survives, has_repost = self.source_of(entry)
            action, why = self.classify(entry, diff, survives, has_repost)

            kind = entry.kind or "(none)"
            by_kind[kind][0] += 1
            by_kind[kind][1] += abs(diff)
            by_action[action] += 1
            total_diff += diff

            rows.append({
                "entry_id": entry.pk,
                "entry_number": entry.entry_number or "",
                "kind": kind,
                "company_id": entry.company_id,
                "date": entry.date.isoformat() if entry.date else "",
                "debit": debit,
                "credit": credit,
                "difference": diff,
                "source_field": field or "",
                "source_model": model_label or "",
                "proposed_action": action,
                "why": why,
                "known_cause": DIAGNOSIS.get(kind, "not one of the nine kinds fixed on 2026-08-12"),
            })

        self.write_summary(rows, by_kind, by_action, total_diff)

        if options["csv"]:
            self.write_csv(rows, options["csv"])
        elif rows:
            self.stdout.write("")
            self.stdout.write("Re-run with --csv <path> for the per-entry rows.")

        return None

    def write_summary(self, rows, by_kind, by_action, total_diff):
        out = self.stdout
        out.write("")
        out.write(self.style.MIGRATE_HEADING("Unbalanced journal entries"))
        out.write("")

        if not rows:
            out.write(self.style.SUCCESS(
                "  None. Every entry in scope has debits equal to its credits."
            ))
            return

        out.write(f"  entries: {len(rows)}")
        out.write(f"  net debit-credit across them: {total_diff:,.3f}")
        out.write("")
        out.write(f"  {'kind':<26} | {'count':>5} | {'absolute imbalance':>20}")
        out.write(f"  {'-' * 26}-+-{'-' * 5}-+-{'-' * 20}")
        for kind, (count, amount) in sorted(by_kind.items(), key=lambda kv: -kv[1][0]):
            out.write(f"  {kind:<26} | {count:>5} | {amount:>20,.3f}")

        out.write("")
        out.write("  proposed actions")
        for action, count in sorted(by_action.items(), key=lambda kv: -kv[1]):
            out.write(f"    {action:<22} {count:>5}")

        out.write("")
        out.write(self.style.WARNING(
            "  Nothing was written. This command has no --apply yet: what to do\n"
            "  with each of these is a judgement to make against the list, not a\n"
            "  heuristic to run unattended over a production ledger."
        ))
        out.write(self.style.WARNING(
            "  This census also cannot see entries whose journal is correct while\n"
            "  the account's stored opening_balance moved by something else. Use\n"
            "  `audit_ledger` for that half."
        ))

    def write_csv(self, rows, path):
        if not rows:
            return
        handle = sys.stdout if path == "-" else open(path, "w", newline="")
        try:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        finally:
            if handle is not sys.stdout:
                handle.close()
                self.stdout.write(f"\n  wrote {len(rows)} rows to {path}")
