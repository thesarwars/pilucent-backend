"""Classify accounts whose stored balance disagrees with their own journal.

`audit_ledger --only drift` found **32 accounts across 3 companies** on production
on 2026-08-31, net -1,066,671.85. It reports the total; it does not say what any
of it is made of, and nothing in the repo repairs it. `repair_unbalanced_entries`
fixes a different defect -- entries whose debits differ from their credits -- and
its own docstring names this as the half it cannot see:

    "a leg written correctly while the account's stored `opening_balance` moved
     by something else ... no query in this command finds it."

This is that query.

## Dry run is the default. `--apply` writes, and only under two gates.

`--apply` requires `--company`, and that selector must be a numeric id or the
whole name -- a partial name is refused. It shipped accepting a substring, and
on 2026-09-02 `--company X` matched **Halo A-x-is** and repaired twelve accounts
on a company nobody had named. The repair was correct and the company was a
legitimate target, which is luck rather than design.

`--apply` touches REPAIRABLE and SIGN_INVERTED. `--include-control` adds
CONTROL_TYPED. `--only` narrows whatever is in scope and never widens it, and
UNBACKED is reachable by no flag at all.

**Why an overwrite rather than a dated adjusting entry**, which is what the five
document-delete fixes shipped this month all chose: `opening_balance` is a
**cache** of the journal, not an independent fact. The journal is the source of
truth and already holds the right figure -- no money moved, no transaction
happened, and there is nothing to date an entry to. Posting one would invent an
accounting event to explain a stale cache. That argument holds only where the
journal is the whole story, which is exactly what the two excluded buckets are
not.

The write goes through `.save()` rather than `update_opening_balance`, because
`ChartOfAccount` is registered with auditlog and `apply_balance_delta` moves the
column with a queryset `.update()` that bypasses signals. The balance writer the
rest of the codebase uses is audit-blind, and a repair is precisely the write
that has to be recoverable.

## The basis question, and why it is settled

The codebase holds two defensible definitions of the journal total, and until
2026-09-02 nobody knew whether they disagreed on real data:

* **Every leg** (`account_balance_as_of`, and what `audit_ledger` measures).
  `update_opening_balance` -- the function that maintains the stored column --
  takes an account, an operation and an amount. It never sees the entry, let
  alone its status. So the stored figure is *by construction* the sum of every
  leg ever written, and this is the only basis on which a repair is not itself
  an unjournaled balance move.
* **Published legs only.** What the Bank Register shows
  (`views/chart_of_accounts.py:506`) and what reconciliation will offer to tick
  (`candidate_connectors`). The register's own docstring puts it plainly: "a
  draft is not on the books."

This command reports every account under **both**, and the production run on
2026-09-02 answered it: **no account anywhere carries a leg on a DRAFT, REMOVED
or UN_PUBLISHED entry**, so the two definitions agree everywhere and a repair
can use either. `account_balance_as_of` is used, being the canonical primitive.

The measurement is taken over every account rather than over the drifting ones,
which was not true of the first version and mattered: an account whose all-legs
total already agrees can still be basis-dependent, and it is the commonest way
to be. A soft-deleted entry whose balance was never backed out leaves the stored
column and the all-legs total agreeing, and both wrong by the deleted entry.

## What it will not repair

* **UNBACKED** -- a stored balance with no journal lines at all. `Import - Wages`
  holds -4,000,000 this way. Recomputing sets it to zero and four million of
  imported cost stops existing. No flag reaches it. The accounting-correct
  remedy is a dated adjusting entry to Opening Balance Equity.
* **CONTROL_TYPED** -- a control account (`system_key` set) carrying drift, held
  back by default and repairable with `--include-control`. The bucket is a proxy:
  `system_key` says "control account", not "a human entered this figure", and the
  tool cannot tell the two apart. See `OPTIONAL_BUCKETS` for the test that
  distinguishes them, which is an equity check to re-run rather than a fact to
  assume.

**SIGN_INVERTED** is called out separately too, but for the opposite reason: it
is the most repairable class there is. `stored == -journal` to the penny means
every posting to that account moved the stored figure the wrong way and nothing
else ever touched it -- the signature of a writer that has since been fixed, of
which `_post_side` in the payroll journal helper is the documented example. It
still wants a human's eye before a bulk rewrite, because on an expense account
the mis-sided half may be the leg rather than the balance.
"""

import csv
import io

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from common.django_rest.helpers.ledger_balances import account_balance_as_of

from accounts.choices import ChartOfAccountKindChoices as Kind
from accounts.models import ChartOfAccount

from companyio.models import Company

from journalio.choices import JournalEntryStatusChoices
from journalio.models import JournalEntryConnector


ZERO = Decimal("0.00")

# The same threshold `audit_ledger` uses, so the two commands agree on what
# counts as drift rather than reporting different populations of the same defect.
TOLERANCE = Decimal("0.005")

# Assets and expenses increase on the debit side; everything else on the credit
# side. Identical to `ledger_balances.to_natural`, restated here only because
# this command aggregates in SQL over many accounts at once rather than calling
# the per-account helper 3,000 times.
DEBIT_NATURAL = (Kind.ASSETS, Kind.EXPENSES)

BUCKETS = ("REPAIRABLE", "SIGN_INVERTED", "CONTROL_TYPED", "UNBACKED")

# What `--apply` writes by default. `--only` narrows this and never widens it.
WRITABLE_BUCKETS = ("REPAIRABLE", "SIGN_INVERTED")

# What `--include-control` adds. Held back by default because the tool cannot
# tell a control account carrying a figure somebody typed from one that has
# simply drifted -- it buckets on `system_key`, which says "control account",
# not "a human entered this".
#
# The production equation audit on 2026-09-02 settled it for the accounts that
# were on the books then, and the argument is worth keeping because it is the
# test to re-apply rather than a fact to trust. Creating an account with a typed
# opening balance posts a PAIRED entry -- the account and Opening Balance Equity
# (`serializers/chart_of_accounts.py:300-334`). At both drifting companies
# equity agreed to the penny between the stored column and the journal, so no
# stored-only equity counterpart existed anywhere. A genuinely typed A/R of
# 2,399,995 would have created one. It had not, so the figure did not come from
# that path and was drift like any other.
#
# Check equity agrees before using this flag. Where it does not, a typed balance
# may be real and recomputing would erase somebody's decision.
OPTIONAL_BUCKETS = ("CONTROL_TYPED",)

# Nothing widens this one. An account with no journal lines recomputes to zero,
# and `Import - Wages` holds -4,000,000 that way: four million of imported cost
# whose only record is the column a recompute would clear. It wants a dated
# adjusting entry to Opening Balance Equity -- an accounting act with a date and
# an author, not a column overwrite.
NEVER_WRITABLE = ("UNBACKED",)


def _money(value):
    return f"{Decimal(value or 0):>18,.2f}"


class Command(BaseCommand):
    help = (
        "Classify accounts whose stored balance disagrees with their journal. "
        "Reports only; writes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default=None,
            help="Restrict to one company: numeric id, or a name substring.",
        )
        parser.add_argument(
            "--csv", default=None,
            help="Write the per-account rows to this path ('-' for stdout).",
        )
        parser.add_argument(
            "--limit", type=int, default=25,
            help="Rows printed per bucket (default 25). Does not affect --csv.",
        )
        parser.add_argument(
            "--only", default=None, choices=BUCKETS,
            help="Print one bucket only.",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help=(
                "Write the recomputed balance. Requires --company. Only touches "
                f"{' and '.join(WRITABLE_BUCKETS)}."
            ),
        )
        parser.add_argument(
            "--include-control", action="store_true",
            help=(
                f"Also repair {' and '.join(OPTIONAL_BUCKETS)}. Check first that "
                "`audit_ledger --only equation` shows equity agreeing between "
                f"the stored and journal columns. Never repairs "
                f"{' or '.join(NEVER_WRITABLE)}."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options.get("apply")
        if apply_changes and not options.get("company"):
            # Blast-radius control, not ceremony. Without a selector this walks
            # every company on the installation, and the census shows the
            # drifting accounts include three different companies' bank
            # accounts. One company at a time is a reviewable change.
            raise CommandError(
                "--apply requires --company. Repair one company at a time so "
                "the change can be reviewed against that company's books."
            )

        companies = self._companies(
            options.get("company"), exact_only=bool(apply_changes)
        )
        if not companies:
            self.stderr.write("No matching company.")
            return

        only = options.get("only")
        limit = options["limit"]
        rows = []
        basis_rows = []

        for company in companies:
            found, basis_dependent = self._classify(company)
            basis_rows.extend(basis_dependent)
            if not found:
                continue
            rows.extend(found)
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"\n=== {company.name} (id {company.id})")
            )
            self._report(found, only, limit)
            if apply_changes:
                self.stdout.write(self.style.WARNING(
                    f"\n  --apply is about to write to {company.name!r} "
                    f"(id {company.id})."
                ))
                self._apply(
                    company, found, only,
                    include_control=options.get("include_control"),
                )

        self._fleet_summary(rows, basis_rows)
        if not apply_changes and any(
            row["bucket"] in WRITABLE_BUCKETS for row in rows
        ):
            self.stdout.write(self.style.WARNING(
                "\n  Nothing was written. Re-run with --company <name> --apply to "
                "repair\n  the REPAIRABLE and SIGN_INVERTED accounts above."
            ))

        path = options.get("csv")
        if path:
            self.write_csv(rows, path)

    # -- scan ---------------------------------------------------------------

    def _companies(self, selector, *, exact_only=False):
        """Resolve `--company`. Exact for a write, substring only for a read.

        This shipped as "numeric is an id, anything else is a name substring",
        with a comment congratulating itself for avoiding the uid-prefix trap
        `purge_companies` fell into (`da6f827b`). It had a worse one. A
        substring is matched with `icontains`, so `--company X` selected **Halo
        Axis** -- and on 2026-09-02 it did exactly that against production with
        `--apply`, repairing twelve accounts on a company nobody had named. The
        repair was correct and the company was a legitimate target, which is
        luck, not design.

        So a write now demands an unambiguous selector: an id, or the whole
        name. Reading still accepts a substring, because getting the wrong
        company's census on screen costs nothing and is obvious when it happens.
        Either way an ambiguous match is an error rather than a silent pick of
        the lowest id.
        """
        if not selector:
            return list(Company.objects.all().order_by("id"))

        selector = str(selector)
        if selector.isdigit():
            return list(Company.objects.filter(id=int(selector)))

        exact = list(Company.objects.filter(name__iexact=selector).order_by("id"))
        if exact:
            if len(exact) > 1:
                raise CommandError(
                    f"{len(exact)} companies are named {selector!r}. "
                    "Use the numeric id instead."
                )
            return exact

        if exact_only:
            raise CommandError(
                f"No company is named exactly {selector!r}. --apply will not "
                "accept a partial name: pass the full name or the numeric id. "
                "Run without --apply to find it."
            )

        loose = list(Company.objects.filter(name__icontains=selector).order_by("id"))
        if len(loose) > 1:
            names = ", ".join(f"{c.name!r} (id {c.id})" for c in loose[:10])
            raise CommandError(
                f"{selector!r} matches {len(loose)} companies: {names}. "
                "Be more specific, or use the numeric id."
            )
        return loose

    def _totals(self, company, published_only=False):
        """`{account_id: (natural_total, leg_count)}` for one company.

        Scoped by `account__company` rather than by `journal__company`. The two
        differ: the manual journal-entry PATCH path could reparent a leg to an
        entry of another company, so a leg can sit on this company's account
        under another company's entry. It is in the stored figure either way,
        and the stored figure is what this command is comparing against.
        """
        queryset = JournalEntryConnector.objects.filter(account__company=company)
        if published_only:
            queryset = queryset.filter(
                journal__status=JournalEntryStatusChoices.PUBLISHED
            )

        totals = {}
        for row in (
            queryset.values("account_id", "account__kind").annotate(
                debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
                credit=Coalesce(
                    Sum("credit"), Value(ZERO), output_field=DecimalField()
                ),
                legs=Count("id"),
            )
        ):
            debit = Decimal(row["debit"])
            credit = Decimal(row["credit"])
            natural = (
                debit - credit
                if row["account__kind"] in DEBIT_NATURAL
                else credit - debit
            )
            totals[row["account_id"]] = (natural, row["legs"])
        return totals

    def _classify(self, company):
        """Returns `(drifting_rows, basis_dependent_rows)`.

        The second list is deliberately NOT a subset of the first. An account
        carrying legs on a DRAFT or REMOVED entry whose balance was never backed
        out *agrees* with the all-legs total -- the leg is still counted and the
        balance still holds it -- so it does not drift and would be filtered out
        before anything looked at its basis. That is exactly the account the
        basis question is about, so it is collected on its own pass over every
        account rather than out of the drift results.
        """
        every_leg = self._totals(company)
        published = self._totals(company, published_only=True)

        found = []
        basis_dependent = []
        accounts = ChartOfAccount.objects.get_status_all().filter(company=company)
        for account in accounts:
            stored = Decimal(account.opening_balance or 0)
            derived, legs = every_leg.get(account.id, (ZERO, 0))
            published_derived, _ = published.get(account.id, (ZERO, 0))
            drift = stored - derived

            if legs and derived != published_derived:
                basis_dependent.append(
                    {
                        "company": company.name,
                        "account": account.title or "",
                        "kind": account.kind,
                        "stored": stored,
                        "derived_all_legs": derived,
                        "derived_published": published_derived,
                        "status_gap": derived - published_derived,
                        "drifts": abs(drift) > TOLERANCE,
                    }
                )

            if legs == 0:
                if stored == ZERO:
                    continue
                bucket = "UNBACKED"
            elif abs(drift) <= TOLERANCE:
                continue
            elif derived != ZERO and abs(stored + derived) <= TOLERANCE:
                # stored == -derived to the penny: every posting moved the
                # stored figure the wrong way and nothing else ever touched it.
                bucket = "SIGN_INVERTED"
            elif account.system_key:
                bucket = "CONTROL_TYPED"
            else:
                bucket = "REPAIRABLE"

            found.append(
                {
                    "company": company.name,
                    "company_id": company.id,
                    "account_id": account.id,
                    "account_uid": str(account.uid),
                    "account": account.title or "",
                    "kind": account.kind,
                    "system_key": account.system_key or "",
                    "bucket": bucket,
                    "legs": legs,
                    "stored": stored,
                    "derived_all_legs": derived,
                    "derived_published": published_derived,
                    "drift": drift,
                    # How much of `derived` comes from entries the Bank Register
                    # does not show. Zero on almost every account; where it is
                    # not, this is the account that decides which basis a repair
                    # should use, because the two definitions genuinely differ.
                    "status_gap": derived - published_derived,
                    "drift_vs_published": stored - published_derived,
                }
            )

        found.sort(key=lambda row: abs(row["drift"]), reverse=True)
        basis_dependent.sort(key=lambda row: abs(row["status_gap"]), reverse=True)
        return found, basis_dependent

    # -- output -------------------------------------------------------------

    def _report(self, rows, only, limit):
        for bucket in BUCKETS:
            if only and bucket != only:
                continue
            in_bucket = [row for row in rows if row["bucket"] == bucket]
            if not in_bucket:
                continue

            net = sum((row["drift"] for row in in_bucket), ZERO)
            self.stdout.write(f"\n  {bucket}: {len(in_bucket)}   net drift {_money(net)}")
            self.stdout.write(
                f"    {'account':<32}{'kind':<12}{'stored':>18}"
                f"{'journal':>18}{'drift':>18}{'not published':>18}"
            )
            for row in in_bucket[:limit]:
                self.stdout.write(
                    f"    {row['account'][:30]:<32}{row['kind']:<12}"
                    f"{_money(row['stored'])}{_money(row['derived_all_legs'])}"
                    f"{_money(row['drift'])}{_money(row['status_gap'])}"
                )
            if len(in_bucket) > limit:
                self.stdout.write(f"    … {len(in_bucket) - limit} more (raise --limit)")

            self.stdout.write(self.style.WARNING(f"    {self._advice(bucket)}"))

    def _advice(self, bucket):
        return {
            "REPAIRABLE": (
                "recomputable from the ledger once the basis question is settled"
            ),
            "SIGN_INVERTED": (
                "stored == -journal to the penny: a writer that has since been "
                "fixed. Most repairable class, but check which half is wrong"
            ),
            "CONTROL_TYPED": (
                "a control account carrying a figure a human entered. Recomputing "
                "erases a decision -- wants a dated adjusting entry instead"
            ),
            "UNBACKED": (
                "NEVER recompute: no journal lines, so recompute means zero. "
                "Import artefacts live here"
            ),
        }[bucket]

    def _fleet_summary(self, rows, basis_rows):
        if not rows:
            self.stdout.write(self.style.SUCCESS("\nNo drift found."))
            self._basis_summary(basis_rows)
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== fleet"))
        for bucket in BUCKETS:
            in_bucket = [row for row in rows if row["bucket"] == bucket]
            if in_bucket:
                net = sum((row["drift"] for row in in_bucket), ZERO)
                self.stdout.write(
                    f"  {bucket:<16}{len(in_bucket):>5} accounts   net {_money(net)}"
                )
        self.stdout.write(
            f"  {'TOTAL':<16}{len(rows):>5} accounts   "
            f"net {_money(sum((row['drift'] for row in rows), ZERO))}"
        )

        self._basis_summary(basis_rows)

    def _basis_summary(self, basis_rows):
        """The measurement the basis question turns on.

        Counted over EVERY account, not just the drifting ones -- see
        `_classify`. An account that agrees on the all-legs basis can still be
        basis-dependent, and it is the commonest way to be: a soft-deleted
        journal entry whose balance was never backed out leaves the stored
        column and the all-legs total in perfect agreement, and both wrong by
        the deleted entry.
        """
        self.stdout.write(
            "\n  Accounts whose journal total depends on the basis chosen: "
            f"{len(basis_rows)}"
        )
        if not basis_rows:
            self.stdout.write(
                "    None -- no account anywhere carries a leg on a DRAFT, REMOVED\n"
                "    or UN_PUBLISHED entry, so the two definitions agree and a\n"
                "    repair can use either."
            )
            return

        drifting = sum(1 for row in basis_rows if row["drifts"])
        self.stdout.write(self.style.WARNING(
            "    These carry legs on DRAFT, REMOVED or UN_PUBLISHED entries.\n"
            "    The stored column counts them (`update_opening_balance` cannot\n"
            "    see an entry's status); the Bank Register does not.\n"
            f"    {drifting} of them also drift; the rest agree with the stored\n"
            "    column precisely BECAUSE the deleted entry was never backed out."
        ))
        self.stdout.write(
            f"    {'account':<32}{'kind':<12}{'all legs':>18}"
            f"{'published':>18}{'gap':>18}"
        )
        for row in basis_rows[:25]:
            self.stdout.write(
                f"    {row['account'][:30]:<32}{row['kind']:<12}"
                f"{_money(row['derived_all_legs'])}"
                f"{_money(row['derived_published'])}{_money(row['status_gap'])}"
            )
        if len(basis_rows) > 25:
            self.stdout.write(f"    … {len(basis_rows) - 25} more")

    def _writable(self, include_control):
        buckets = tuple(WRITABLE_BUCKETS)
        if include_control:
            buckets += tuple(OPTIONAL_BUCKETS)
        # Belt and braces: whatever the flags say, the never-writable set is
        # never in here. A future flag that forgets this would silently zero an
        # import artefact.
        return tuple(b for b in buckets if b not in NEVER_WRITABLE)

    def _apply(self, company, rows, only, *, include_control=False):
        """Set the stored balance to what the ledger says. One company, atomic.

        Why an overwrite rather than a dated adjusting entry, which is what the
        five delete paths shipped this month all chose: `opening_balance` is a
        **cache** of the journal, not an independent fact. The journal is the
        source of truth and it already says the right figure -- no money moved,
        no transaction happened, and there is nothing to date an entry to.
        Posting one would invent an accounting event to explain a stale cache.
        That reasoning holds only for the two writable buckets; where the stored
        figure might carry something the journal does not, this refuses.

        Written with `.save()` rather than through `update_opening_balance`.
        `ChartOfAccount` is registered with auditlog (`accounts/admin.py`), and
        `apply_balance_delta` moves the column with a queryset `.update()`, which
        bypasses signals -- so the balance writer the rest of the codebase uses is
        audit-blind. A repair is exactly the write that must be recoverable
        afterwards.
        """
        writable = self._writable(include_control)
        targets = [
            row
            for row in rows
            if row["bucket"] in writable
            and (only is None or row["bucket"] == only)
        ]
        if not targets:
            return

        repaired, overtaken = [], []
        with transaction.atomic():
            for row in targets:
                account = ChartOfAccount.objects.select_for_update().get(
                    pk=row["account_id"]
                )
                stored = Decimal(account.opening_balance or 0)
                # Re-derived under the lock rather than trusted from the scan.
                # A posting between the two moves the stored column and the
                # journal together and leaves the drift intact, but an admin
                # edit or a second run of this command does not -- and writing
                # the scanned figure would silently undo either.
                fresh = Decimal(account_balance_as_of(account))
                if abs(stored - fresh) <= TOLERANCE:
                    overtaken.append((account, stored))
                    continue

                account.opening_balance = fresh
                account.save(update_fields=["opening_balance", "updated_at"])
                repaired.append((account, stored, fresh))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n  --apply: {len(repaired)} account(s) repaired"
        ))
        for account, before, after in repaired:
            self.stdout.write(
                f"    {str(account.title)[:30]:<32}"
                f"{_money(before)} ->{_money(after)}"
            )
        if repaired:
            moved = sum((after - before for _, before, after in repaired), ZERO)
            self.stdout.write(f"    net moved {_money(moved)}")
            self.stdout.write(self.style.SUCCESS(
                "    auditlog holds the before/after for each of these."
            ))
        if overtaken:
            self.stdout.write(self.style.WARNING(
                f"    {len(overtaken)} already agreed by the time the lock was "
                "taken and were left alone."
            ))

    def write_csv(self, rows, path):
        """`-` goes to this command's own stdout, not to `sys.stdout`.

        `repair_unbalanced_entries` writes straight to `sys.stdout`, which
        escapes Django's `OutputWrapper` -- so the rows cannot be captured by
        `call_command(stdout=...)` or redirected by a caller. Buffering and
        handing the text to `self.stdout` keeps the same output on a terminal
        and makes it testable.
        """
        if not rows:
            return
        if path == "-":
            buffer = io.StringIO()
            self._dump(rows, buffer)
            self.stdout.write(buffer.getvalue())
            return
        with open(path, "w", newline="") as handle:
            self._dump(rows, handle)
        self.stdout.write(f"\n  wrote {len(rows)} rows to {path}")

    @staticmethod
    def _dump(rows, handle):
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
