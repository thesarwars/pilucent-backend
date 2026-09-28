"""Check live chart-of-account rows for the faults the API can no longer create.

`validate_chart_of_account_seeds` does this for the 20 shipped templates and is
now clean on every check. This is the same idea pointed at tenant data, which no
command covered: the guards added over the last few days stop these being
*created*, but say nothing about rows that already exist.

    python manage.py audit_account_integrity
    python manage.py audit_account_integrity --company "Halo Axis"
    python manage.py audit_account_integrity --only parent

Three checks, each closing a hole that was open until recently:

**parent** -- an account whose parent belongs to a different company. The
`parent_uid` queryset was global, so any tenant could name any account in the
database as a parent. Scoped since `4153beef`; existing rows were never swept.

**pair** -- a `detail_type` that does not sit beneath its `account_type`. The
pair decides where an account lands on the statements, so a mismatch files it in
the wrong place. Checked as DESCENDANT rather than child: the CSV importer's
template legitimately produces grandchildren, and flagging those would bury the
real ones.

**kind** -- a stored `kind` that disagrees with what the account type implies, or
that is not one of the five at all. An account like this appears on no statement
and raises on the first automatic posting. The CSV importer could mint them until
`ce470e86`; a production run found two, both `kind='OTHER EXPENSES'` -- a value
that does not exist, since all five kinds are roots.

"What the account type implies" means the ROOT it descends from, walked all the
way up. This check used to stop at the parent, which is right only for a depth-1
account type. The taxonomy is three deep, so an account typed against
`Interest Paid` (`Expenses -> Other Expenses -> Interest Paid`) resolved to
`OTHER EXPENSES` and was reported as disagreeing with its perfectly correct
`EXPENSES`. Production carried one such false positive, and it sat in the list of
accounts "needing a decision" -- where the decision was to leave it alone.

Report-only. Every fault here has more than one defensible repair -- reparent or
detach, retype or reclassify -- and which is right depends on what the tenant
has been using the account for. The output gives the journal-line count for
exactly that reason.
"""

from django.core.management.base import BaseCommand

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    detail_type_is_under,
    root_kind_of,
)

from companyio.models import Company

CHECKS = ("parent", "pair", "kind")


class Command(BaseCommand):
    help = "Report chart-of-account rows that are internally inconsistent."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--only", choices=CHECKS, help="Run a single check."
        )
        parser.add_argument("--limit", type=int, default=25)

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

        accounts = (
            ChartOfAccount.objects.filter(company__in=companies)
            .exclude(status=ChartOfAccountStatusChoices.REMOVED)
            .select_related("company", "parent", "account_type", "detail_type")
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Chart-of-account integrity -- {companies.count()} company(ies), "
                f"{accounts.count()} live accounts"
            )
        )
        self.stdout.write("")

        only = options["only"]
        found = 0
        if only in (None, "parent"):
            found += self.check_parent(accounts, options["limit"])
        if only in (None, "pair"):
            found += self.check_pair(accounts, options["limit"])
        if only in (None, "kind"):
            found += self.check_kind(accounts, options["limit"])

        self.stdout.write("")
        if not found:
            self.stdout.write(
                self.style.SUCCESS("No inconsistent accounts found.")
            )
            return
        self.stdout.write(
            self.style.WARNING(
                f"{found} account(s) need a decision. The `lines` count is what "
                "decides how freely each can be changed: a row with none can be "
                "corrected outright, one with history needs the correction "
                "journaled rather than edited."
            )
        )

    def _report(self, title, offenders, describe, limit):
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        if not offenders:
            self.stdout.write(self.style.SUCCESS("  none"))
            self.stdout.write("")
            return 0
        for account in offenders[:limit]:
            lines = account.journalentryconnector_set.count()
            self.stdout.write(
                f"  {account.company.name[:20]:<22} id={account.id:<6} "
                f"{account.title[:26]:<28} lines={lines:<4} {describe(account)}"
            )
        if len(offenders) > limit:
            self.stdout.write(f"  ... {len(offenders) - limit} more")
        self.stdout.write("")
        return len(offenders)

    def check_parent(self, accounts, limit):
        offenders = [
            account
            for account in accounts.filter(parent__isnull=False)
            if account.parent.company_id != account.company_id
        ]
        return self._report(
            "1. Parent belongs to another company",
            offenders,
            lambda a: f"parent {a.parent.title!r} is in {a.parent.company.name!r}",
            limit,
        )

    def check_pair(self, accounts, limit):
        offenders = [
            account
            for account in accounts.filter(
                account_type__isnull=False, detail_type__isnull=False
            )
            if not detail_type_is_under(account.account_type, account.detail_type)
        ]
        return self._report(
            "2. Detail type does not sit beneath its account type",
            offenders,
            lambda a: (
                f"{a.detail_type.title!r} is not under {a.account_type.title!r}"
            ),
            limit,
        )

    def check_kind(self, accounts, limit):
        offenders = []
        for account in accounts:
            declared = account.kind
            if declared not in ChartOfAccountKindChoices.values:
                offenders.append(account)
                continue
            root = root_kind_of(account.account_type)
            if root and root != declared:
                offenders.append(account)
        return self._report(
            "3. Stored kind disagrees with the account type",
            offenders,
            lambda a: (
                f"kind={a.kind!r} but type {getattr(a.account_type, 'title', None)!r}"
            ),
            limit,
        )
