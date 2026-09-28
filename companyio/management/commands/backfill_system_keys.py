"""Stamp `system_key` on the control accounts of companies created before it existed.

New companies get their keys at seed time. Companies onboarded earlier have none,
so they still resolve their control accounts through the title fallback in
`get_chart_of_account()` -- which works, but leaves them one rename away from the
bug the key exists to prevent.

This is that backfill. It is deliberately a command with a dry run rather than a
data migration: it touches every existing tenant's chart of accounts, and the
`--create-missing` half creates rows, which is not something that should happen
silently during a deploy.

    python manage.py backfill_system_keys                        # dry run
    python manage.py backfill_system_keys --company "Halo Axis"
    python manage.py backfill_system_keys --apply                # stamp keys
    python manage.py backfill_system_keys --apply --create-missing

Two distinct problems, handled separately on purpose:

* **Un-keyed** -- the account exists under its canonical title and just needs the
  key. Safe, idempotent, no new rows. This is the common case.
* **Absent** -- the company has no account for that key at all. Every
  `food_beverage` tenant is in this state for all ten, because that template
  shipped none of them until it was fixed. `--create-missing` creates them from
  the company's own industry template, so the account carries the right type and
  code rather than something invented here.

Companies whose control account is duplicated are reported and skipped -- picking
one arbitrarily is how the wrong account ends up in the ledger.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.choices import (
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount

from categoryio.models import Category

from common.django_rest.helpers.chart_of_account_helpers import (
    LEGACY_TITLES,
    ON_DEMAND_KEYS,
    SYSTEM_KEY_TO_TITLE,
)

from companyio.django_rest.helpers.chart_of_accounts import chart_of_accounts
from companyio.models import Company


class Command(BaseCommand):
    help = "Backfill ChartOfAccount.system_key on companies created before it existed."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--apply", action="store_true", help="Write. Without it, dry run."
        )
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Also create control accounts the company does not have at all.",
        )
        parser.add_argument(
            "--merge-legacy",
            action="store_true",
            help=(
                "Repair companies that ended up with BOTH a legacy-named account "
                "and a freshly created canonical one."
            ),
        )
        parser.add_argument("--limit", type=int, default=30, help="Rows shown per list.")

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

        template_by_kind = {
            str(block["kind"]): block["chart_of_accounts"]
            for block in chart_of_accounts
        }

        if options["merge_legacy"]:
            self.merge_legacy(companies, options["apply"], options["limit"])
            return

        stamped = []
        unprotected = []
        absent = []
        conflicted = []
        already = 0

        for company in companies:
            live = ChartOfAccount.objects.filter(company=company).exclude(
                status=ChartOfAccountStatusChoices.REMOVED
            )
            keyed = set(
                live.filter(system_key__isnull=False).values_list(
                    "system_key", flat=True
                )
            )
            for key in Key.values:
                if key in ON_DEMAND_KEYS:
                    # Created the first time the thing that needs it happens,
                    # never seeded, so there is no account here to stamp and its
                    # absence is not a finding. Skipped rather than reported so
                    # the summary keeps meaning "accounts that should exist and
                    # do not".
                    continue
                if key in keyed:
                    already += 1
                    # Keyed but unguarded is a state onboarding never produces --
                    # it sets both together -- so these are accounts that were
                    # keyed by an earlier run of this command, before it also
                    # set the flag. Collected rather than skipped: the resolver
                    # already treats them as control accounts, so leaving them
                    # editable is the hole C2 closed everywhere else.
                    unprotected.extend(
                        live.filter(system_key=key, is_fixed=False)
                    )
                    continue
                title = SYSTEM_KEY_TO_TITLE[key]
                # Also match names the account shipped under before the
                # canonical title existed, so an existing account is renamed and
                # keyed rather than left beside a freshly created duplicate.
                candidate_titles = [title, *LEGACY_TITLES.get(key, [])]
                matches = list(
                    live.filter(title__in=candidate_titles, system_key__isnull=True)
                )
                if len(matches) == 1:
                    stamped.append((company, matches[0], key))
                elif len(matches) > 1:
                    conflicted.append((company, title, key, len(matches)))
                else:
                    absent.append((company, key, title))

        self.report(
            companies.count(), already, stamped, absent, conflicted, options["limit"]
        )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run -- nothing changed. Re-run with --apply to write."
                )
            )
            return

        renamed = 0
        protected = 0
        with transaction.atomic():
            for _company, account, key in stamped:
                canonical = SYSTEM_KEY_TO_TITLE[key]
                fields = ["system_key", "updated_at"]
                if account.title != canonical:
                    # Matched under a legacy name -- adopt the canonical title so
                    # the chart shows one name for one concept.
                    account.title = canonical
                    fields.append("title")
                    renamed += 1
                if not account.is_fixed:
                    # A key without the flag is only half a control account. The
                    # resolver would find it, but the serializer and the DELETE
                    # view both gate on `is_fixed`, so it stayed renameable,
                    # retypeable and deletable -- which is what C2 exists to
                    # prevent. Onboarding sets both together; only accounts that
                    # predate their key arrive here with one and not the other.
                    account.is_fixed = True
                    fields.append("is_fixed")
                    protected += 1
                account.system_key = key
                account.save(update_fields=fields)

            for account in unprotected:
                account.is_fixed = True
                account.save(update_fields=["is_fixed", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"\nStamped {len(stamped)} account(s)"
                + (f", {renamed} renamed from a legacy title" if renamed else "")
                + (f", {protected} marked is_fixed" if protected else "")
                + "."
            )
        )
        if unprotected:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Guarded {len(unprotected)} account(s) that were already "
                    f"keyed but not is_fixed."
            )
        )

        if absent and options["create_missing"]:
            created = self.create_missing(absent, template_by_kind)
            self.stdout.write(
                self.style.SUCCESS(f"Created {created} missing control account(s).")
            )
        elif absent:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(absent)} control account(s) absent -- re-run with "
                    "--create-missing to create them from each company's template."
                )
            )

        self.verify(companies)

    # -- legacy merge ------------------------------------------------------

    def merge_legacy(self, companies, apply, limit):
        """Collapse a legacy-named account and its canonical twin into one.

        An earlier run of this command matched only on the canonical title, so a
        company that already had e.g. "Discounts Given" was reported as missing
        `SALES_DISCOUNTS` and had a brand new "Sales Discounts" created beside
        it. Two accounts for one concept is exactly what the rename was meant to
        avoid: whichever one the user picks, half their discounts land on the
        other.

        The keyed twin was created by that run and therefore has no journal
        lines. Where that holds, it is removed and the original is renamed and
        keyed, so any history stays on the account that already had it. Where
        BOTH carry journal lines the pair is reported and skipped -- merging
        real balances is not something a repair script should decide.
        """
        pairs, conflicts = [], []
        for company in companies:
            live = ChartOfAccount.objects.filter(company=company).exclude(
                status=ChartOfAccountStatusChoices.REMOVED
            )
            for key, legacy_titles in LEGACY_TITLES.items():
                canonical = live.filter(system_key=key).first()
                legacy = live.filter(
                    title__in=legacy_titles, system_key__isnull=True
                ).first()
                if not canonical or not legacy:
                    continue
                if canonical.journalentryconnector_set.exists():
                    conflicts.append((company, key, canonical, legacy))
                else:
                    pairs.append((company, key, canonical, legacy))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Legacy account merge"))
        self.stdout.write(f"  mergeable pairs      : {len(pairs)}")
        self.stdout.write(f"  conflicts (skipped)  : {len(conflicts)}")
        self.stdout.write("")

        for company, key, canonical, legacy in pairs[:limit]:
            lines = legacy.journalentryconnector_set.count()
            self.stdout.write(
                f"  {company.name[:26]:<28} {key:<18} keep {legacy.title!r} "
                f"({lines} journal lines), drop the empty {canonical.title!r}"
            )
        if len(pairs) > limit:
            self.stdout.write(f"  ... {len(pairs) - limit} more")

        for company, key, canonical, legacy in conflicts:
            self.stdout.write(
                self.style.ERROR(
                    f"  {company.name[:26]:<28} {key:<18} BOTH have journal lines "
                    f"-- {legacy.title!r} and {canonical.title!r}. Resolve by hand."
                )
            )

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run -- nothing changed. Re-run with --apply to merge."
                )
            )
            return

        merged = 0
        for company, key, canonical, legacy in pairs:
            title = canonical.title
            with transaction.atomic():
                # Safe: checked above that it carries no ledger history, and the
                # PROTECT on JournalEntryConnector.account would refuse anyway.
                canonical.delete()
                legacy.title = title
                legacy.system_key = key
                legacy.save(update_fields=["title", "system_key", "updated_at"])
            merged += 1

        self.stdout.write(
            self.style.SUCCESS(f"\nMerged {merged} pair(s).")
        )
        if conflicts:
            self.stdout.write(
                self.style.WARNING(f"{len(conflicts)} left for manual resolution.")
            )

    # -- creation ----------------------------------------------------------

    def create_missing(self, absent, template_by_kind):
        """Create absent control accounts from each company's industry template.

        Delegates to the same helper onboarding uses, so the repair and the
        seed path cannot drift apart -- a company healed here ends up identical
        to one onboarded today.
        """
        from companyio.django_rest.helpers.signal_helpers import (
            create_control_account,
        )

        created = 0
        for company, key, title in absent:
            with transaction.atomic():
                account = create_control_account(company, key)
            if account is None:
                # create_control_account has already logged why.
                self.stdout.write(
                    self.style.ERROR(
                        f"  could not create {title!r} for {company.name} "
                        f"[{company.kind}] -- see the log"
                    )
                )
                continue
            created += 1
        return created

    # -- output ------------------------------------------------------------

    def report(self, company_count, already, stamped, absent, conflicted, limit):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("system_key backfill"))
        self.stdout.write(f"  companies              : {company_count}")
        self.stdout.write(f"  already keyed          : {already}")
        self.stdout.write(f"  to stamp               : {len(stamped)}")
        self.stdout.write(f"  absent (need creating) : {len(absent)}")
        self.stdout.write(f"  ambiguous (skipped)    : {len(conflicted)}")
        self.stdout.write("")

        if stamped:
            self.stdout.write(self.style.MIGRATE_HEADING("Would stamp"))
            for company, account, key in stamped[:limit]:
                self.stdout.write(
                    f"  {company.name[:28]:<30} {key:<24} {account.title}"
                )
            if len(stamped) > limit:
                self.stdout.write(f"  ... {len(stamped) - limit} more")
            self.stdout.write("")

        if absent:
            self.stdout.write(
                self.style.MIGRATE_HEADING("Absent -- company has no such account")
            )
            by_company = {}
            for company, key, _title in absent:
                by_company.setdefault(company, []).append(key)
            for company, keys in list(by_company.items())[:limit]:
                self.stdout.write(
                    f"  {company.name[:28]:<30} [{company.kind}] missing "
                    f"{len(keys)}: {', '.join(keys)}"
                )
            if len(by_company) > limit:
                self.stdout.write(f"  ... {len(by_company) - limit} more companies")
            self.stdout.write("")

        if conflicted:
            self.stdout.write(
                self.style.ERROR("Ambiguous -- more than one account has this title")
            )
            for company, title, key, count in conflicted[:limit]:
                self.stdout.write(
                    f"  {company.name[:28]:<30} {key:<24} {title!r} x{count}"
                )
            self.stdout.write(
                "  Skipped. Resolve the duplicates first -- picking one "
                "arbitrarily is how the wrong account ends up in the ledger."
            )
            self.stdout.write("")

    def verify(self, companies):
        """Report which companies still cannot post."""
        from common.django_rest.helpers.chart_of_account_helpers import (
            missing_system_keys,
        )

        broken = [(c, missing_system_keys(c)) for c in companies]
        broken = [(c, missing) for c, missing in broken if missing]
        self.stdout.write("")
        if not broken:
            self.stdout.write(
                self.style.SUCCESS("Every company now resolves all 10 control accounts.")
            )
            return
        self.stdout.write(
            self.style.WARNING(f"{len(broken)} company(ies) still incomplete:")
        )
        for company, missing in broken[:30]:
            self.stdout.write(
                f"  {company.name[:28]:<30} [{company.kind}] missing {len(missing)}"
            )
