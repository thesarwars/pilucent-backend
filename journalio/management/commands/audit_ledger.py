"""Read-only audit of the general ledger and the balances derived from it.

Reports three defects, all of which make a balance sheet wrong in ways no
reporting change can fix:

1. **Unbalanced journal entries** -- entries whose debits do not equal their
   credits. Double-entry requires equality; where it fails, every downstream
   total inherits the error.
2. **Running-balance drift** -- accounts whose stored
   `ChartOfAccount.opening_balance` disagrees with the sum of their own journal
   lines, including accounts carrying a balance with no journal lines at all
   (typically import artefacts).
3. **The accounting equation** -- assets against liabilities + equity + net
   income, computed on both bases so the two can be compared.
4. **Subledger vs control** -- for A/R and A/P, the four numbers that must agree
   and had never been compared: the ledger, the stored control balance, the sum
   of the party balances, and the ageing total.

This command only reads. It changes nothing, so it is safe to run against
production.

    python manage.py audit_ledger
    python manage.py audit_ledger --company "Pilucent INC" --limit 40
    python manage.py audit_ledger --only equation
    python manage.py audit_ledger --only subledger
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from accounts.choices import ChartOfAccountKindChoices as Kind
from accounts.models import ChartOfAccount
from companyio.models import Company
from journalio.models import JournalEntry, JournalEntryConnector


ZERO = Decimal("0.00")
TOLERANCE = Decimal("0.005")


def _money(value):
    return f"{Decimal(value or 0):>18,.2f}"


class Command(BaseCommand):
    help = "Audit journal balance, running-balance drift and the accounting equation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help="Company name (icontains) or id. Default: every company.",
        )
        parser.add_argument(
            "--limit", type=int, default=25, help="Rows per section (default 25)."
        )
        parser.add_argument(
            "--only",
            choices=["entries", "drift", "equation", "subledger"],
            help="Run a single section.",
        )

    def handle(self, *args, **options):
        companies = self._companies(options.get("company"))
        if not companies:
            self.stderr.write("No matching company.")
            return

        only = options.get("only")
        limit = options["limit"]

        for company in companies:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {company.name} (id {company.id})"))
            if only in (None, "entries"):
                self._unbalanced_entries(company, limit)
            if only in (None, "drift"):
                self._balance_drift(company, limit)
            if only in (None, "equation"):
                self._equation(company)
            if only in (None, "subledger"):
                self._subledger(company)

    # ------------------------------------------------------------------ #

    def _companies(self, selector):
        if not selector:
            return list(Company.objects.all().order_by("id"))
        if str(selector).isdigit():
            return list(Company.objects.filter(id=int(selector)))
        return list(Company.objects.filter(name__icontains=selector).order_by("id"))

    def _unbalanced_entries(self, company, limit):
        """Journal entries whose two sides disagree."""
        rows = (
            JournalEntryConnector.objects.filter(journal__company=company)
            .values("journal_id", "journal__entry_number", "journal__kind",
                    "journal__date")
            .annotate(
                debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
                credit=Coalesce(Sum("credit"), Value(ZERO),
                                output_field=DecimalField()),
            )
        )
        bad = []
        total = ZERO
        for row in rows:
            diff = Decimal(row["debit"]) - Decimal(row["credit"])
            if abs(diff) > TOLERANCE:
                bad.append((abs(diff), row, diff))
                total += diff
        bad.sort(reverse=True, key=lambda item: item[0])

        self.stdout.write(f"\n  Unbalanced journal entries: {len(bad)}")
        if not bad:
            self.stdout.write(self.style.SUCCESS("    every entry balances"))
            return
        self.stdout.write(f"    net effect on the ledger: {_money(total)}")
        self.stdout.write(
            f"    {'entry':<22}{'kind':<14}{'date':<12}"
            f"{'debit':>18}{'credit':>18}{'diff':>18}"
        )
        for _, row, diff in bad[:limit]:
            self.stdout.write(
                f"    {str(row['journal__entry_number'])[:20]:<22}"
                f"{str(row['journal__kind'])[:12]:<14}"
                f"{str(row['journal__date']):<12}"
                f"{_money(row['debit'])}{_money(row['credit'])}{_money(diff)}"
            )
        if len(bad) > limit:
            self.stdout.write(f"    … {len(bad) - limit} more (raise --limit)")

    def _balance_drift(self, company, limit):
        """Accounts whose stored balance disagrees with their journal lines."""
        journal = {}
        rows = (
            JournalEntryConnector.objects.filter(journal__company=company)
            .values("account_id", "account__kind")
            .annotate(
                debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
                credit=Coalesce(Sum("credit"), Value(ZERO),
                                output_field=DecimalField()),
            )
        )
        for row in rows:
            debit = Decimal(row["debit"])
            credit = Decimal(row["credit"])
            # Assets and expenses increase on the debit side; the rest on credit.
            journal[row["account_id"]] = (
                debit - credit
                if row["account__kind"] in (Kind.ASSETS, Kind.EXPENSES)
                else credit - debit
            )

        drifted = []
        orphans = []
        for account in ChartOfAccount.objects.get_status_all().filter(company=company):
            stored = Decimal(account.opening_balance or 0)
            if account.id not in journal:
                if stored != ZERO:
                    orphans.append((abs(stored), account, stored))
                continue
            diff = stored - journal[account.id]
            if abs(diff) > TOLERANCE:
                drifted.append((abs(diff), account, stored, journal[account.id], diff))

        drifted.sort(reverse=True, key=lambda item: item[0])
        orphans.sort(reverse=True, key=lambda item: item[0])

        self.stdout.write(
            f"\n  Accounts whose stored balance disagrees with the journal: "
            f"{len(drifted)}"
        )
        if drifted:
            net = sum((item[4] for item in drifted), ZERO)
            self.stdout.write(f"    net drift: {_money(net)}")
            self.stdout.write(
                f"    {'account':<36}{'kind':<13}{'stored':>18}"
                f"{'journal':>18}{'drift':>18}"
            )
            for _, account, stored, derived, diff in drifted[:limit]:
                self.stdout.write(
                    f"    {str(account.title)[:34]:<36}{account.kind:<13}"
                    f"{_money(stored)}{_money(derived)}{_money(diff)}"
                )
            if len(drifted) > limit:
                self.stdout.write(f"    … {len(drifted) - limit} more")

        self.stdout.write(
            f"\n  Accounts holding a balance with NO journal lines at all: "
            f"{len(orphans)}"
        )
        if orphans:
            self.stdout.write(
                "    (these are unbacked balances -- typically import artefacts)"
            )
            for _, account, stored in orphans[:limit]:
                self.stdout.write(
                    f"    {str(account.title)[:34]:<36}{account.kind:<13}"
                    f"{_money(stored)}"
                )

    def _subledger(self, company):
        """The four A/R and A/P numbers that must agree, and never had a check.

        `SUPPLIER_GAPS.md` D10 and D13, and the customer twin. Nothing in the
        product compared a vendor subledger to the A/P control account -- every
        figure in that document came from ad-hoc queries written for it.

        **Why four columns and not two.** The subledger and the stored control
        figure are written by the same serializer lines, so they agree on most
        companies while BOTH disagree with the ledger. A two-way check between
        them reports nothing on exactly the books that are wrong. The ledger is
        the reference because it is the only one of the four derived from
        double-entry rather than maintained alongside it.

        The fourth column is the ageing total, which is what the A/P and A/R
        Aging reports actually print. Standard §7 and §11.3 require it to tie to
        the balance sheet as of the same date; drawn from a different table, it
        is a fourth number rather than a check on the other three (D13).
        """
        from accounts.choices import ChartOfAccountSystemKeyChoices as Key
        from customerio.models import Customer
        from supplierio.models import Supplier

        from weapi.django_rest.helpers.dashboard.finance import (
            open_bills_qs,
            open_invoices_qs,
        )

        cases = [
            ("A/R", Key.AR, "Accounts Receivable (A/R)",
             Customer.objects.filter(company=company), open_invoices_qs(company)),
            ("A/P", Key.AP, "Accounts Payable (A/P)",
             Supplier.objects.filter(company=company), open_bills_qs(company)),
        ]

        self.stdout.write("\n  Subledger vs control (the ledger is the reference):")
        header = (
            f"    {'':<6}{'ledger':>18}{'stored':>18}{'subledger':>18}"
            f"{'ageing':>18}"
        )
        self.stdout.write(header)

        for label, key, title, parties, documents in cases:
            account = (
                ChartOfAccount.objects.filter(company=company, system_key=key).first()
                or ChartOfAccount.objects.filter(
                    company=company, title=title
                ).first()
            )
            if account is None:
                self.stdout.write(f"    {label:<6}  no control account on this company")
                continue

            legs = JournalEntryConnector.objects.filter(
                journal__company=company, account=account
            ).aggregate(
                debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
                credit=Coalesce(Sum("credit"), Value(ZERO),
                                output_field=DecimalField()),
            )
            debit = Decimal(legs["debit"])
            credit = Decimal(legs["credit"])
            ledger = (
                debit - credit
                if account.kind in (Kind.ASSETS, Kind.EXPENSES)
                else credit - debit
            )

            stored = Decimal(account.opening_balance or 0)
            subledger = parties.aggregate(
                total=Coalesce(Sum("opening_balance"), Value(ZERO),
                               output_field=DecimalField())
            )["total"]
            ageing = documents.aggregate(
                total=Coalesce(Sum("due_total"), Value(ZERO),
                               output_field=DecimalField())
            )["total"]

            self.stdout.write(
                f"    {label:<6}{_money(ledger)}{_money(stored)}"
                f"{_money(subledger)}{_money(ageing)}"
            )

            drifts = [
                ("stored", stored - ledger),
                ("subledger", Decimal(subledger) - ledger),
                ("ageing", Decimal(ageing) - ledger),
            ]
            offenders = [
                (name, diff) for name, diff in drifts if abs(diff) > TOLERANCE
            ]
            if not offenders:
                self.stdout.write(f"    {'':<6}  ties on all four")
                continue
            for name, diff in offenders:
                self.stdout.write(
                    f"    {'':<6}  {name} is out by "
                    f"{Decimal(diff):,.2f} against the ledger"
                )

    def _equation(self, company):
        """Assets vs liabilities + equity + net income, on both bases."""
        stored_qs = (
            ChartOfAccount.objects.get_status_all()
            .filter(company=company, journalentryconnector__isnull=False)
            .distinct()
        )

        def stored(kind):
            return stored_qs.aggregate(
                v=Coalesce(Sum("opening_balance", filter=Q(kind=kind)), Value(ZERO),
                           output_field=DecimalField())
            )["v"]

        rows = (
            JournalEntryConnector.objects.filter(journal__company=company)
            .values("account__kind")
            .annotate(
                debit=Coalesce(Sum("debit"), Value(ZERO), output_field=DecimalField()),
                credit=Coalesce(Sum("credit"), Value(ZERO),
                                output_field=DecimalField()),
            )
        )
        derived = {}
        for row in rows:
            kind = row["account__kind"]
            debit = Decimal(row["debit"])
            credit = Decimal(row["credit"])
            derived[kind] = (
                debit - credit
                if kind in (Kind.ASSETS, Kind.EXPENSES)
                else credit - debit
            )

        self.stdout.write("\n  Accounting equation:")
        self.stdout.write(
            f"    {'':<14}{'stored balance':>20}{'from journal':>20}"
        )
        for label, kind in (
            ("assets", Kind.ASSETS),
            ("liabilities", Kind.LIABILITIES),
            ("equity", Kind.EQUITIES),
            ("income", Kind.INCOMES),
            ("expenses", Kind.EXPENSES),
        ):
            self.stdout.write(
                f"    {label:<14}{_money(stored(kind))}{_money(derived.get(kind, ZERO))}"
            )

        for label, get in (
            ("stored", lambda k: stored(k)),
            ("journal", lambda k: derived.get(k, ZERO)),
        ):
            net_income = get(Kind.INCOMES) - get(Kind.EXPENSES)
            gap = get(Kind.ASSETS) - (
                get(Kind.LIABILITIES) + get(Kind.EQUITIES) + net_income
            )
            style = self.style.SUCCESS if abs(gap) <= Decimal("0.01") else self.style.ERROR
            self.stdout.write(
                style(
                    f"    A - (L + E + NI) [{label}]: {_money(gap)}"
                    + ("  balances" if abs(gap) <= Decimal("0.01") else "  OUT OF BALANCE")
                )
            )
