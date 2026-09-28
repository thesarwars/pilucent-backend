"""Report companies that no longer have a single member.

WHY THESE EXIST
---------------

`Company` has no foreign key to `User`. The link is the `CompanyUser` join
table, which makes a company a shared tenant rather than any one user's
property -- correct, and the reason deleting a user never deletes a company.

The side effect is that deleting the *last* member of a company leaves the
company behind. Nothing is orphaned in the referential sense: every row still
points at a live company and the books are internally consistent. But there is
no longer anybody who can log in to them. Repeated over a few hundred throwaway
signups -- each of which seeds a full chart of accounts -- that is most of the
junk in the database.

Django cannot express this as a cascade. The cardinality is many-to-many, so
there is no `on_delete` to hang the behaviour on, and there should not be:
`Company` is the CASCADE root for 77 models, so an automatic sweep would let one
member's account deletion wipe a live tenant's entire accounting.

WHAT THIS DOES
--------------

Reports. Nothing else -- there is no `--apply`, by design. It lists every
company with zero active members, alongside how much bookkeeping each one is
holding, so the ones that are genuinely disposable can be told apart from the
ones that lost their last admin by accident.

A company holding journal entries is flagged. Those cannot be hard-deleted
anyway -- `JournalEntryConnector.account` is PROTECT and raises even from inside
a cascade -- and they are the ones most likely to be a real tenant in trouble
rather than a test artifact.

To act on the result: soft-remove with `CompanyStatusChoices.REMOVED`, which is
reversible, or pass the owning users to `purge_users --with-orphan-companies`.

USAGE
-----

    ./manage.py audit_orphan_companies
    ./manage.py audit_orphan_companies --include-removed
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from accounts.choices import UserStatusChoices
from accounts.models import ChartOfAccount

from companyio.choices import CompanyStatusChoices
from companyio.models import Company

from customerio.models import Customer

from employeeio.models import Employee

from journalio.models import JournalEntry

from purchaseio.models import Purchase

from salesio.models import Sale

from supplierio.models import Supplier


# Counted per orphan company, in report order. Journal entries come first
# because they are the signal that a company is real bookkeeping rather than a
# test artifact.
HOLDINGS = (
    ("journals", JournalEntry),
    ("accounts", ChartOfAccount),
    ("sales", Sale),
    ("purchases", Purchase),
    ("customers", Customer),
    ("suppliers", Supplier),
    ("employees", Employee),
)


class Command(BaseCommand):
    help = "List companies left with zero members, and what each one holds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-removed",
            action="store_true",
            help="Also list companies already soft-removed. Off by default.",
        )
        parser.add_argument(
            "--min-journals",
            type=int,
            default=0,
            help="Only show companies holding at least this many journal entries.",
        )

    def handle(self, *args, **options):
        companies = Company.objects.all()
        if not options["include_removed"]:
            companies = companies.exclude(status=CompanyStatusChoices.REMOVED)

        # A member counts only if their user row is still live. A company whose
        # every CompanyUser points at a REMOVED user is just as unreachable as
        # one with no rows at all.
        orphans = (
            companies.annotate(
                live_members=Count(
                    "companyuser",
                    filter=~Q(companyuser__user__status=UserStatusChoices.REMOVED),
                    distinct=True,
                )
            )
            .filter(live_members=0)
            .order_by("id")
        )

        rows = []
        for company in orphans:
            holdings = {
                name: model.objects.filter(company=company).count()
                for name, model in HOLDINGS
            }
            if holdings["journals"] < options["min_journals"]:
                continue
            rows.append((company, holdings))

        if not rows:
            self.stdout.write(self.style.SUCCESS("No memberless companies found."))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Memberless companies: {len(rows)}")
        )
        self.stdout.write("")

        headers = ["id", "name", "status"] + [name for name, _ in HOLDINGS]
        widths = [max(6, len(h)) for h in headers]
        widths[1] = max(
            widths[1], min(40, max(len(c.name or "") for c, _ in rows))
        )

        def line(values):
            return "  ".join(
                str(v).ljust(w)[:w] if i < 3 else str(v).rjust(w)
                for i, (v, w) in enumerate(zip(values, widths))
            )

        self.stdout.write(line(headers))
        self.stdout.write("  ".join("-" * w for w in widths))

        totals = {name: 0 for name, _ in HOLDINGS}
        with_books = 0
        for company, holdings in rows:
            if holdings["journals"]:
                with_books += 1
            for name in totals:
                totals[name] += holdings[name]
            self.stdout.write(
                line(
                    [company.id, company.name or "-", company.status]
                    + [holdings[name] for name, _ in HOLDINGS]
                )
            )

        self.stdout.write("  ".join("-" * w for w in widths))
        self.stdout.write(line(["", "TOTAL", ""] + [totals[n] for n, _ in HOLDINGS]))
        self.stdout.write("")

        if with_books:
            self.stdout.write(
                self.style.WARNING(
                    f"{with_books} of these hold journal entries. Those are posted "
                    "books -- a hard delete raises ProtectedError, and a company "
                    "that has been transacting is more likely to have lost its "
                    "last admin by accident than to be a test signup. Review each "
                    "one before touching it."
                )
            )
        disposable = len(rows) - with_books
        if disposable:
            self.stdout.write(
                f"{disposable} hold no journal entries and are safe candidates for "
                "removal. Report only -- this command never writes."
            )
