"""Hard-delete users and everything that hangs off them.

WHY THIS EXISTS
---------------

Deleting a user from the Django admin raises `IntegrityError` at COMMIT:

    update or delete on table "employeeio_employee" violates foreign key
    constraint "payrollio_payrollsal_employee_id_35b6c426_fk_employeei"

The purge takes the user's `Employee` rows with it. (`Employee.user` is
`SET_NULL` in the BD model -- an employee is the company's statutory record and
outlives a deleted login in ordinary use -- so this command collects a purged
user's employees explicitly; see `handle`.) But
`PayrollSalaryProcess.employee` is `on_delete=DO_NOTHING`, so Django's collector
skips those rows entirely -- it does not delete them, null them, or even see
them. `db_constraint` still defaults to True, so Postgres enforces the FK that
Django ignored, and the violation lands at COMMIT.

Rather than change `on_delete` across the schema -- which would alter how the
running application behaves for every ordinary delete -- this command flips
`DO_NOTHING` foreign keys to `CASCADE` **for the duration of its own run only**,
in memory, and restores them in a `finally`. Nothing is migrated and no other
code path is affected. The database is untouched; only the collector's view of
the graph changes while it walks.

`PROTECT` and `RESTRICT` are never touched, so every existing delete guard still
fires -- including the one that keeps a company delete from taking the ledger
with it. Two ledger FKs are additionally held back; see `LEDGER_GUARDED`.

WHAT IT DELETES
---------------

Everything Django's own `Collector` reaches from the named users once those
`DO_NOTHING` edges are traversable, plus the users' `Employee` rows. That is the
full transitive closure: `CompanyUser` membership, `Employee` and its CASCADE
children (nominees, statutory, tax and payment profiles, investments, field
history, salary structures), payroll
runs, attendance, chat, notifications. The ~39 `SET_NULL` referrers to
`Employee` and ~15 to `User` are nulled rather than deleted, exactly as the
schema asks; the report counts them separately so nothing is a surprise.

Companies are deliberately NOT deleted by default. `Company` has no foreign key
to `User` -- the link is the `CompanyUser` join table -- so a company is a shared
tenant, not a user's private property. It is also the CASCADE root for 77
models. Deleting one user must never take a workspace out from under its other
members.

For junk and test accounts the leftover company is usually the point, though: a
throwaway signup seeds a whole chart of accounts. `--with-orphan-companies`
additionally deletes companies that the purge would leave with **zero**
remaining members. It is opt-in, it is loud, and it is the single most
destructive thing here.

It also refuses on any company that has posted a ledger. `JournalEntryConnector.
account` is PROTECT, and PROTECT raises even when the protecting rows sit inside
the same cascade -- deliberately, per journalio/models.py:161. So a company with
real bookkeeping stops the purge with a `ProtectedError` naming the rows. That is
the guard working, not a failure: those books need a human decision, not a flag.

USAGE
-----

Identifiers are auto-detected -- anything with `@` is an email, anything
parseable as a UUID is a `uid`, digits are a primary key::

    ./manage.py purge_users a@b.com 03df53fa-b2b6-4f98-8ff0-4f9bf9f673d5 355
    ./manage.py purge_users --file junk_accounts.txt
    ./manage.py purge_users --file junk_accounts.txt --apply

Dry run by default. `--apply` is required to write, and both runs print the same
plan first so they can be compared.
"""

import uuid
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import (
    Collector,
    ProtectedError,
    RestrictedError,
)

from common.deletion import LEDGER_GUARDED, do_nothing_as_cascade  # noqa: F401

from accounts.models import User

from companyio.models import Company, CompanyUser
from employeeio.models import Employee


class Command(BaseCommand):
    help = "Hard-delete users and every row that hangs off them."

    def add_arguments(self, parser):
        parser.add_argument(
            "identifiers",
            nargs="*",
            help="Emails, uids, or numeric ids. Mixed freely; each is auto-detected.",
        )
        parser.add_argument(
            "--file",
            help="Read identifiers from a file, one per line. Blank lines and #comments ignored.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the deletions. Without it, nothing is modified.",
        )
        parser.add_argument(
            "--with-orphan-companies",
            action="store_true",
            help=(
                "Also delete companies left with zero members by this purge. "
                "Company cascades to 77 models -- this destroys their entire books."
            ),
        )

    # -- identifier handling ------------------------------------------------

    def parse_identifiers(self, tokens):
        emails, uids, ids, unparseable = [], [], [], []
        for raw in tokens:
            token = raw.strip()
            if not token or token.startswith("#"):
                continue
            if "@" in token:
                emails.append(token)
                continue
            try:
                uids.append(uuid.UUID(token))
                continue
            except ValueError:
                pass
            if token.isdigit():
                ids.append(int(token))
            else:
                unparseable.append(token)
        return emails, uids, ids, unparseable

    def resolve_users(self, emails, uids, ids):
        lookup = Q(pk__in=[])
        if emails:
            lookup |= Q(email__in=emails)
        if uids:
            lookup |= Q(uid__in=uids)
        if ids:
            lookup |= Q(id__in=ids)
        return User.objects.filter(lookup)

    def report_unmatched(self, users, emails, uids, ids):
        found_emails = {e.lower() for e in users.values_list("email", flat=True)}
        found_uids = set(users.values_list("uid", flat=True))
        found_ids = set(users.values_list("id", flat=True))
        missing = (
            [e for e in emails if e.lower() not in found_emails]
            + [str(u) for u in uids if u not in found_uids]
            + [str(i) for i in ids if i not in found_ids]
        )
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"  {len(missing)} identifier(s) matched no user: "
                    + ", ".join(missing[:10])
                    + (" ..." if len(missing) > 10 else "")
                )
            )

    # -- planning -----------------------------------------------------------

    def build_plan(self, collector):
        """Per-model counts of rows deleted, and of rows merely nulled."""
        deletes = defaultdict(int)
        for model, instances in collector.data.items():
            deletes[model._meta.label] += len(instances)
        for queryset in collector.fast_deletes:
            count = queryset.count()
            if count:
                deletes[queryset.model._meta.label] += count

        # A row that is nulled and then deleted in the same run is a delete,
        # not a null -- count it once. That happens to a purged user's Employee
        # (Employee.user is SET_NULL, and the command also collects the
        # employee), and to rows the employee cascade removes on the fast-delete
        # path while one of their FKs to the user is SET_NULL (field history).
        # Only models that actually have a nulled field need their doomed pks.
        nulled = {field.model._meta.concrete_model for field, _ in collector.field_updates}
        doomed_by_model = defaultdict(set)
        for model, instances in collector.data.items():
            if model._meta.concrete_model in nulled:
                doomed_by_model[model._meta.concrete_model].update(obj.pk for obj in instances)
        for queryset in collector.fast_deletes:
            if queryset.model._meta.concrete_model in nulled:
                doomed_by_model[queryset.model._meta.concrete_model].update(
                    queryset.values_list("pk", flat=True)
                )

        nulls = defaultdict(int)
        for (field, value), querysets in collector.field_updates.items():
            doomed = doomed_by_model.get(field.model._meta.concrete_model, set())
            for queryset in querysets:
                count = (
                    sum(1 for obj in queryset if obj.pk not in doomed)
                    if isinstance(queryset, list)
                    else queryset.exclude(pk__in=doomed).count()
                )
                if count:
                    label = f"{field.model._meta.label}.{field.name}"
                    nulls[label] += count
        return deletes, nulls

    def orphaned_companies(self, users):
        """Companies whose only remaining members are the users being purged."""
        touched = set(
            CompanyUser.objects.filter(user__in=users).values_list(
                "company_id", flat=True
            )
        )
        if not touched:
            return Company.objects.none()
        surviving = set(
            CompanyUser.objects.filter(company_id__in=touched)
            .exclude(user__in=users)
            .values_list("company_id", flat=True)
        )
        return Company.objects.filter(id__in=touched - surviving)

    def print_table(self, title, rows, style):
        if not rows:
            return
        self.stdout.write("")
        self.stdout.write(style(title))
        width = max(len(label) for label in rows)
        for label, count in sorted(rows.items(), key=lambda kv: (-kv[1], kv[0])):
            self.stdout.write(f"  {label.ljust(width)}  {count:>7,}")
        self.stdout.write(f"  {'TOTAL'.ljust(width)}  {sum(rows.values()):>7,}")

    # -- entry point --------------------------------------------------------

    def handle(self, *args, **options):
        tokens = list(options["identifiers"])
        if options["file"]:
            try:
                with open(options["file"]) as handle:
                    tokens.extend(handle.read().splitlines())
            except OSError as exc:
                raise CommandError(f"Cannot read --file: {exc}")

        if not tokens:
            raise CommandError(
                "Give at least one email, uid, or id -- as arguments or via --file."
            )

        emails, uids, ids, unparseable = self.parse_identifiers(tokens)
        if unparseable:
            raise CommandError(
                "Not an email, uid, or id: " + ", ".join(unparseable[:10])
            )

        users = self.resolve_users(emails, uids, ids)
        if not users.exists():
            raise CommandError("No users matched. Nothing to do.")

        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Users targeted: {users.count()}")
        )
        for user in users.order_by("id")[:50]:
            self.stdout.write(f"  [{user.id}] {user.email}  {user.uid}")
        if users.count() > 50:
            self.stdout.write(f"  ... and {users.count() - 50} more")
        self.report_unmatched(users, emails, uids, ids)

        doomed_companies = list(self.orphaned_companies(users))

        with do_nothing_as_cascade() as (patched, skipped):
            self.stdout.write("")
            self.stdout.write(
                f"Traversing {len(patched)} DO_NOTHING foreign key(s) as CASCADE "
                f"for this run only."
            )
            if skipped:
                names = ", ".join(
                    f"{f.model._meta.label}.{f.name}" for f in skipped
                )
                self.stdout.write(
                    f"  Left alone to protect the ledger: {names}"
                )

            collector = Collector(using="default", origin=users)
            try:
                # One `collect()` per model -- it keys the batch off objs[0] and
                # a mixed list makes the related-object filter raise ValueError.
                # Both calls accumulate into the same collector.
                collector.collect(list(users))
                # A purged user's employee records go with them, as the US
                # cascade did; the BD model keeps them on an ordinary delete.
                employees = list(Employee.objects.filter(user__in=users))
                if employees:
                    collector.collect(employees)
                if options["with_orphan_companies"] and doomed_companies:
                    collector.collect(doomed_companies)
            except ProtectedError as exc:
                raise CommandError(
                    "Blocked by a PROTECT foreign key -- "
                    f"{len(exc.protected_objects)} row(s), e.g. "
                    f"{list(exc.protected_objects)[:3]}"
                )
            except RestrictedError as exc:
                raise CommandError(
                    "Blocked by a RESTRICT foreign key -- "
                    f"{len(exc.restricted_objects)} row(s), e.g. "
                    f"{list(exc.restricted_objects)[:3]}"
                )

            deletes, nulls = self.build_plan(collector)

            self.print_table("ROWS TO DELETE", deletes, self.style.ERROR)
            self.print_table("REFERENCES TO NULL (SET_NULL)", nulls, self.style.WARNING)

            if doomed_companies:
                self.stdout.write("")
                verb = (
                    "WILL BE DELETED"
                    if options["with_orphan_companies"]
                    else "will be left with zero members"
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"COMPANIES THAT {verb} ({len(doomed_companies)})"
                    )
                )
                for company in doomed_companies[:50]:
                    self.stdout.write(f"  [{company.id}] {company.name}")
                if len(doomed_companies) > 50:
                    self.stdout.write(f"  ... and {len(doomed_companies) - 50} more")
                if not options["with_orphan_companies"]:
                    self.stdout.write(
                        "  Their books stay intact but nobody can log in to them. "
                        "Run `audit_orphan_companies` to review, or pass "
                        "--with-orphan-companies to delete them here."
                    )

            if not options["apply"]:
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        "Dry run -- nothing written. Re-run with --apply."
                    )
                )
                return

            with transaction.atomic():
                deleted_total, per_model = collector.delete()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_total:,} row(s) across {len(per_model)} model(s)."
            )
        )
