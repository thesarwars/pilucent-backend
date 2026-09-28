"""Re-type accounts whose detail type does not sit beneath their account type.

`audit_account_integrity` reports these; this repairs the ones that can be
repaired mechanically. On production it found 131, and they are not a mystery:
they are the seed templates' own wrong pairs, materialised in every tenant
onboarded before those templates were corrected. `Depreciation` typed under
`Expense` when it belongs under `Other Expenses`, `Notes Payable` under
`Other Current Liabilities` when it belongs under `Long Term Liabilities`, and
so on -- the same 63 pairs the seed validator now refuses.

    python manage.py repair_account_pairs
    python manage.py repair_account_pairs --company "Balanzify LTD"
    python manage.py repair_account_pairs --apply

The account type is corrected to the one that actually parents the detail type,
because the detail type is the more specific statement of intent: somebody chose
"Depreciation", and there is exactly one account type that owns it.

Three tiers, and only the first is repaired:

**Safe.** The correct account type has the same root kind, so the account keeps
its side of the statements and only its grouping changes. Nearly all of them.

**Changes kind -- reported, never applied.** The correct account type roots to a
different kind, so repairing would move the account across the statements. On
production this is `Treasury Stock` typed under `Long Term Liabilities`: equity
filed as a liability. Real, but which way to resolve it is a judgement about what
the account is actually for, and a script should not decide that.

**Has journal lines -- reported, never applied.** Reclassifying a posted account
restates every period it appears in, which is exactly what the model's guard
refuses. Those need a dated correcting entry, not an edit.
"""

from collections import Counter

from django.core.management.base import BaseCommand

from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    detail_type_is_under,
    root_kind_of as _root_of,
)

from companyio.models import Company


class Command(BaseCommand):
    help = "Re-type accounts whose detail type sits under a different account type."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--apply", action="store_true", help="Write. Without it, dry run."
        )
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        companies = Company.objects.all().order_by("id")
        if options["company"]:
            needle = options["company"]
            companies = (
                companies.filter(id=needle)
                if str(needle).isdigit()
                else companies.filter(name__icontains=needle)
            )
        if not companies.exists():
            self.stderr.write(self.style.ERROR("No company matches."))
            return

        safe, changes_kind, has_history, unresolvable = [], [], [], []

        candidates = (
            ChartOfAccount.objects.filter(company__in=companies)
            .exclude(status=ChartOfAccountStatusChoices.REMOVED)
            .filter(account_type__isnull=False, detail_type__isnull=False)
            .select_related("company", "account_type", "detail_type")
        )

        for account in candidates:
            if detail_type_is_under(account.account_type, account.detail_type):
                continue

            correct = account.detail_type.parent
            if correct is None:
                unresolvable.append((account, None))
                continue

            if account.journalentryconnector_set.exists():
                has_history.append((account, correct))
            elif _root_of(correct) != _root_of(account.account_type):
                changes_kind.append((account, correct))
            else:
                safe.append((account, correct))

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Account pair repair -- {companies.count()} company(ies)"
            )
        )
        self.stdout.write(f"  safe to re-type          : {len(safe)}")
        self.stdout.write(f"  would change kind        : {len(changes_kind)}")
        self.stdout.write(f"  has journal lines        : {len(has_history)}")
        self.stdout.write(f"  detail type has no parent: {len(unresolvable)}")
        self.stdout.write("")

        moves = Counter(
            f"{a.account_type.title!r} -> {c.title!r}" for a, c in safe
        )
        for move, count in moves.most_common(options["limit"]):
            self.stdout.write(f"    {count:>4}x  {move}")
        if len(moves) > options["limit"]:
            self.stdout.write(f"    ... {len(moves) - options['limit']} more shapes")
        self.stdout.write("")

        self._list("Would change kind -- resolve by hand", changes_kind, options)
        self._list("Has journal lines -- needs a dated correction", has_history, options)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("Dry run -- nothing changed. Re-run with --apply.")
            )
            return

        repaired = 0
        for account, correct in safe:
            # Re-checked here, against the value BEFORE the assignment. Silently
            # moving an account to the other side of the statements is the one
            # outcome this must never produce, and the tiering that prevents it
            # is worth confirming at the point of the write rather than trusting
            # a list built earlier.
            was = _root_of(account.account_type)
            now = _root_of(correct)
            if was != now:
                self.stdout.write(
                    self.style.ERROR(
                        f"  refusing id={account.id}: {was} -> {now} changes kind"
                    )
                )
                continue
            account.account_type = correct
            account.save(update_fields=["account_type", "updated_at"])
            repaired += 1

        self.stdout.write(self.style.SUCCESS(f"\nRe-typed {repaired} account(s)."))
        if changes_kind or has_history:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(changes_kind) + len(has_history)} left for a human."
                )
            )

    def _list(self, title, rows, options):
        if not rows:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        for account, correct in rows[: options["limit"]]:
            lines = account.journalentryconnector_set.count()
            self.stdout.write(
                f"  {account.company.name[:20]:<22} id={account.id:<6} "
                f"{account.title[:24]:<26} lines={lines:<4} "
                f"{account.account_type.title!r} -> {correct.title!r} "
                f"({_root_of(account.account_type)} -> {_root_of(correct)})"
            )
        if len(rows) > options["limit"]:
            self.stdout.write(f"  ... {len(rows) - options['limit']} more")
        self.stdout.write("")
