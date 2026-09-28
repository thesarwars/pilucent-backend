"""Report chart-of-account rows that would block a uniqueness constraint.

`(company, title)` and `(company, code)` should each identify one live account.
The API now refuses to create or rename one onto another, but nothing stops rows
that already exist -- and a partial unique index cannot be added while any
duplicate remains: `AddConstraint` validates against live data and the migration
fails outright.

So this is the pre-flight. Run it against production, resolve what it lists, then
add the constraint.

    python manage.py audit_duplicate_accounts
    python manage.py audit_duplicate_accounts --company "Halo Axis"
    python manage.py audit_duplicate_accounts --kind code

Report-only by design. Merging two accounts is not a decision a script should
take: one of them usually carries journal history and the other does not, and
which to keep depends on which the tenant has been using. The output names the
line counts precisely so that call can be made per pair.

REMOVED accounts are excluded, matching the constraint that will follow -- a
soft-deleted account must not block its own replacement.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import Upper

from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company


class Command(BaseCommand):
    help = "Report duplicate account titles/codes that block a unique index."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--kind",
            choices=["title", "code", "both"],
            default="both",
            help="Which uniqueness to audit.",
        )
        parser.add_argument("--limit", type=int, default=40)

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

        fields = (
            ["title", "code"] if options["kind"] == "both" else [options["kind"]]
        )
        blocked = defaultdict(list)

        for field in fields:
            base = ChartOfAccount.objects.filter(company__in=companies).exclude(
                status=ChartOfAccountStatusChoices.REMOVED
            )

            if field == "title":
                # Group on UPPER(title), and drop blanks -- because that is the
                # index this is the pre-flight FOR.
                #
                # It used to group on the raw title, case-sensitively, and count
                # blanks. Both directions were wrong, and one of them silently:
                #
                #   * A company holding "Health Insurance" beside "health
                #     insurance" was reported CLEAN, and `AddConstraint` would
                #     still have failed on deploy. That is the exact pair the gap
                #     report cites as the reason for the index, via payroll's
                #     `title__iexact` lookup -- so the audit was blind to its own
                #     motivating case.
                #   * Blank titles were reported as blockers the index would not
                #     block, inflating the cleanup.
                #
                # An audit that does not measure what the constraint enforces
                # cannot tell you when it is safe to add it.
                base = base.exclude(title__isnull=True).exclude(title__exact="")
                grouped = (
                    base.annotate(_key=Upper("title"))
                    .values("company_id", "_key")
                    .annotate(n=Count("id"))
                    .filter(n__gt=1)
                    .order_by("company_id", "_key")
                )
                for row in grouped:
                    blocked[field].append(
                        (row["company_id"], row["_key"], row["n"])
                    )
                continue

            grouped = (
                base.values("company_id", field)
                .annotate(n=Count("id"))
                .filter(n__gt=1)
                .order_by("company_id", field)
            )
            for row in grouped:
                blocked[field].append((row["company_id"], row[field], row["n"]))

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Duplicate account audit -- {companies.count()} company(ies)"
            )
        )
        for field in fields:
            self.stdout.write(f"  duplicate {field:<6}: {len(blocked[field])} group(s)")
        self.stdout.write("")

        names = {c.id: c.name for c in companies}
        total_rows = 0

        for field in fields:
            if not blocked[field]:
                self.stdout.write(
                    self.style.SUCCESS(f"No duplicate {field}s. Safe to constrain.")
                )
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"Duplicate {field}s"))
            for company_id, value, count in blocked[field][: options["limit"]]:
                lookup = (
                    {"title__iexact": value}
                    if field == "title"
                    else {field: value}
                )
                rows = (
                    ChartOfAccount.objects.filter(company_id=company_id, **lookup)
                    .exclude(status=ChartOfAccountStatusChoices.REMOVED)
                    .order_by("id")
                )
                total_rows += count
                self.stdout.write(
                    f"\n  {names.get(company_id, company_id)!r}: "
                    f"{field}={value!r} x{count}"
                )
                for account in rows:
                    lines = account.journalentryconnector_set.count()
                    marker = (
                        "  <- has history"
                        if lines
                        else "  <- unused, safe to remove or rename"
                    )
                    self.stdout.write(
                        f"      id={account.id} code={account.code} "
                        f"title={account.title!r} key={account.system_key or '-'} "
                        f"lines={lines}{marker}"
                    )
            if len(blocked[field]) > options["limit"]:
                self.stdout.write(
                    f"\n  ... {len(blocked[field]) - options['limit']} more groups"
                )
            self.stdout.write("")

        if total_rows:
            self.stdout.write(
                self.style.WARNING(
                    f"{total_rows} row(s) across "
                    f"{sum(len(v) for v in blocked.values())} group(s) must be "
                    "resolved before the unique index can be added.\n"
                    "Where exactly one row in a group carries journal lines, keep "
                    "that one. Where none does, keep whichever the tenant uses and "
                    "soft-delete the rest -- do not hard delete."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Clean for the constraint this checks -- it can be added:\n"
                    "  UNIQUE (company_id, UPPER(title)) "
                    "WHERE status <> 'REMOVED' AND title <> ''\n"
                    "The (company, code) half is NOT recommended -- `code` has no "
                    "consumer, blank codes persist as '' rather than NULL so they "
                    "self-collide, and renumbering a seeded is_fixed account is "
                    "one-way for the tenant. Run with `--kind code` to measure it "
                    "anyway."
                )
            )
