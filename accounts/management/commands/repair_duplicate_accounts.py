"""Retire duplicate chart-of-account titles so the unique index can be added.

The partial unique index on `(company, UPPER(title))` cannot be created while any
company holds two live accounts with the same title -- `AddConstraint` validates
against live data, so one duplicate fails the migration for everyone.

`audit_duplicate_accounts` reports the blocking groups. This repairs them.

WHAT IT DOES, AND WHAT IT REFUSES TO DO
---------------------------------------

Within each blocking group it keeps one row and soft-retires the rest by setting
`status = REMOVED`. **Nothing is ever hard-deleted**, so every row remains
recoverable and `JournalEntryConnector.account` (PROTECT) is never challenged.

**A group where more than one row carries journal lines is left alone**, reported,
and counted as unresolved. Choosing which of two transacted accounts survives is
a bookkeeping decision about where history belongs -- it needs a human, and
guessing would silently move somebody's ledger.

WHICH ROW SURVIVES
------------------

In priority order:

1. the row carrying journal lines, if exactly one does -- history decides
2. the row with a `system_key`, which is the control account the posting engine
   resolves by key
3. the row with `is_fixed=True`, seeded rather than user-made
4. the oldest by id -- deterministic, and it is the one `get_chart_of_account`
   already resolves to, since that helper builds its dict over `-created_at` and
   the last write wins

Dry run by default. `--apply` is required to write, and it prints the same plan
first either way, so the two runs can be compared.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Upper

from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company


class Command(BaseCommand):
    help = "Retire duplicate account titles so the unique index can be added."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without it, nothing is modified.",
        )
        parser.add_argument(
            "--company",
            help="Limit to one company, by id or name fragment.",
        )

    def survivor(self, rows):
        """Which row keeps the title. See the module docstring."""
        with_history = [r for r in rows if r.journalentryconnector_set.exists()]
        if len(with_history) > 1:
            return None, with_history
        if len(with_history) == 1:
            return with_history[0], []

        keyed = [r for r in rows if r.system_key]
        if keyed:
            return sorted(keyed, key=lambda r: r.id)[0], []

        fixed = [r for r in rows if r.is_fixed]
        if fixed:
            return sorted(fixed, key=lambda r: r.id)[0], []

        return sorted(rows, key=lambda r: r.id)[0], []

    def handle(self, *args, **options):
        companies = Company.objects.all()
        needle = options.get("company")
        if needle:
            companies = (
                companies.filter(id=needle)
                if str(needle).isdigit()
                else companies.filter(name__icontains=needle)
            )
            if not companies.exists():
                self.stderr.write(self.style.ERROR("No company matches."))
                return

        # The same shape the index will enforce, and the same shape
        # `audit_duplicate_accounts` reports: UPPER(title), blanks carved out,
        # REMOVED excluded. Measuring anything else would repair the wrong rows.
        live = (
            ChartOfAccount.objects.filter(company__in=companies)
            .exclude(status=ChartOfAccountStatusChoices.REMOVED)
            .exclude(title__isnull=True)
            .exclude(title__exact="")
        )
        groups = (
            live.annotate(key=Upper("title"))
            .values("company_id", "key")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("company_id", "key")
        )

        names = {c.id: c.name for c in companies}
        planned = []
        blocked = []
        by_reason = defaultdict(int)

        for group in groups:
            rows = list(
                live.filter(
                    company_id=group["company_id"], title__iexact=group["key"]
                ).order_by("id")
            )
            keep, contested = self.survivor(rows)
            if keep is None:
                blocked.append((group, rows, contested))
                continue
            retire = [r for r in rows if r.pk != keep.pk]
            planned.append((group, keep, retire))
            by_reason[
                "has journal lines"
                if keep.journalentryconnector_set.exists()
                else "has a system_key"
                if keep.system_key
                else "is_fixed"
                if keep.is_fixed
                else "oldest"
            ] += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Duplicate account repair -- {groups.count()} blocking group(s)"
            )
        )

        for group, keep, retire in planned:
            company = names.get(group["company_id"], group["company_id"])
            self.stdout.write(f"\n  {company!r}: {group['key']!r}")
            self.stdout.write(
                f"      KEEP    id={keep.id} code={keep.code} "
                f"key={keep.system_key or '-'} fixed={keep.is_fixed} "
                f"lines={keep.journalentryconnector_set.count()}"
            )
            for row in retire:
                self.stdout.write(
                    f"      RETIRE  id={row.id} code={row.code} "
                    f"key={row.system_key or '-'} fixed={row.is_fixed} "
                    f"lines={row.journalentryconnector_set.count()}"
                )

        if blocked:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(blocked)} group(s) LEFT ALONE -- more than one row "
                    "carries journal lines. Which of two transacted accounts "
                    "survives is a bookkeeping decision, not a rule."
                )
            )
            for group, rows, contested in blocked:
                company = names.get(group["company_id"], group["company_id"])
                self.stdout.write(f"\n  {company!r}: {group['key']!r}")
                for row in contested:
                    self.stdout.write(
                        f"      id={row.id} code={row.code} "
                        f"lines={row.journalentryconnector_set.count()}"
                    )

        to_retire = sum(len(r) for _g, _k, r in planned)
        self.stdout.write("")
        self.stdout.write(
            f"  resolvable groups : {len(planned)}\n"
            f"  rows to retire    : {to_retire}\n"
            f"  left alone        : {len(blocked)}"
        )
        if by_reason:
            self.stdout.write(
                "  survivor chosen by: "
                + ", ".join(f"{k} x{v}" for k, v in sorted(by_reason.items()))
            )

        if not options["apply"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN -- nothing written. Re-run with --apply to make these "
                    "changes."
                )
            )
            return

        if not to_retire:
            self.stdout.write(self.style.SUCCESS("\nNothing to do."))
            return

        with transaction.atomic():
            retired = 0
            for _group, _keep, retire in planned:
                for row in retire:
                    row.status = ChartOfAccountStatusChoices.REMOVED
                    row.save(update_fields=["status", "updated_at"])
                    retired += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Retired {retired} row(s). Nothing was deleted.")
        )
        if blocked:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(blocked)} group(s) still block the index and need a "
                    "decision per group."
                )
            )
