"""Permanently delete companies, ledger and all.

This is the destructive counterpart to `purge_users`, and the CLI half of what
`CompanyAdmin` does when you delete from the Django admin. Both go through
`companyio.deletion.purge_companies`; see that module for why a company cannot
be deleted by an ordinary cascade and what the teardown order protects.

**Soft-remove is usually what you want.** Setting `status = REMOVED` takes a
company out of the workspace switcher, the console totals and every tenant-facing
list, keeps the books, and can be undone. That is what the superadmin API does.
Use this only for test signups and junk fixtures whose accounting was never real.

USAGE
-----

Identifiers are auto-detected. A full uid, the 8-character uid prefix the admin
shows in its UID column, or a numeric id::

    ./manage.py purge_companies e5bd604a 15ad08f2
    ./manage.py purge_companies 7e260f80-1234-... 42
    ./manage.py purge_companies --file junk_companies.txt

Dry run by default. It prints each company with what it holds -- including the
number of journal legs that would be destroyed -- and `--apply` prints the same
table before writing, so the two runs can be compared.

`--keep-with-books` skips any company holding journal entries, which is the safe
way to sweep a long list: the throwaway signups go, anything that has actually
been transacting is left for you to look at.
"""

import uuid
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.models import ChartOfAccount

from companyio.deletion import count_ledger_legs, purge_companies
from companyio.models import Company, CompanyUser

from customerio.models import Customer

from employeeio.models import Employee

from journalio.models import JournalEntry

from purchaseio.models import Purchase

from salesio.models import Sale

from supplierio.models import Supplier


HOLDINGS = (
    ("journals", JournalEntry),
    ("accounts", ChartOfAccount),
    ("sales", Sale),
    ("purchases", Purchase),
    ("customers", Customer),
    ("suppliers", Supplier),
    ("employees", Employee),
    ("members", CompanyUser),
)

UID_PREFIX_LENGTH = 8


class Command(BaseCommand):
    help = "Permanently delete companies and their ledgers. Irreversible."

    def add_arguments(self, parser):
        parser.add_argument(
            "identifiers",
            nargs="*",
            help=(
                "Company uids, 8-character uid prefixes (as shown in the admin "
                "UID column), or numeric ids. Mixed freely."
            ),
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
            "--keep-with-books",
            action="store_true",
            help="Skip any company holding journal entries instead of destroying them.",
        )

    # -- identifier handling ------------------------------------------------

    def parse_identifiers(self, tokens):
        """Split tokens into uids, uid prefixes and ids -- refusing the overlap.

        An 8-character all-digit token is a valid company id *and* a valid uid
        prefix, and this used to test `isdigit()` first, so it silently became
        an id. Roughly one uid in forty starts with eight digits, so an operator
        copying a prefix out of the admin had about a 2% chance of naming a
        different company -- and this command has an `--apply` mode that
        destroys what it names. The same collision is why
        `tests_purge_companies` flaked.

        Ambiguity cannot be resolved from the token, so it is refused rather
        than guessed: `id:123` and `uid:1234abcd` say which was meant. An
        explicit prefix also lets a short numeric id be given unambiguously.
        """
        uids, prefixes, ids, unparseable = [], [], [], []
        ambiguous = []
        for raw in tokens:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for token in line.replace(",", " ").split():
                explicit, _, value = token.partition(":")
                if value and explicit.lower() in ("id", "uid"):
                    if explicit.lower() == "id":
                        if value.isdigit():
                            ids.append(int(value))
                        else:
                            unparseable.append(token)
                    elif self._is_uid_prefix(value):
                        prefixes.append(value.lower())
                    else:
                        try:
                            uids.append(uuid.UUID(value))
                        except ValueError:
                            unparseable.append(token)
                    continue

                try:
                    uids.append(uuid.UUID(token))
                    continue
                except ValueError:
                    pass

                looks_like_id = token.isdigit()
                looks_like_prefix = self._is_uid_prefix(token)
                if looks_like_id and looks_like_prefix:
                    ambiguous.append(token)
                elif looks_like_id:
                    ids.append(int(token))
                elif looks_like_prefix:
                    prefixes.append(token.lower())
                else:
                    unparseable.append(token)

        if ambiguous:
            raise CommandError(
                "Ambiguous identifier(s): "
                + ", ".join(ambiguous[:10])
                + ". Each is both a valid company id and a valid uid prefix. "
                "Say which you mean: id:<n> or uid:<prefix>."
            )
        return uids, prefixes, ids, unparseable

    @staticmethod
    def _is_uid_prefix(token):
        return len(token) == UID_PREFIX_LENGTH and all(
            c in "0123456789abcdefABCDEF" for c in token
        )

    def resolve_companies(self, uids, prefixes, ids):
        lookup = Q(pk__in=[])
        if uids:
            lookup |= Q(uid__in=uids)
        if ids:
            lookup |= Q(id__in=ids)
        for prefix in prefixes:
            lookup |= Q(uid__startswith=prefix)
        return Company.objects.filter(lookup)

    def holdings_for(self, company):
        counts = {
            name: model.objects.filter(company=company).count()
            for name, model in HOLDINGS
        }
        counts["legs"] = count_ledger_legs([company])
        return counts

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
                "Give at least one uid, uid prefix, or id -- as arguments or via --file."
            )

        uids, prefixes, ids, unparseable = self.parse_identifiers(tokens)
        if unparseable:
            raise CommandError(
                "Not a uid, 8-character uid prefix, or id: "
                + ", ".join(unparseable[:10])
            )

        companies = self.resolve_companies(uids, prefixes, ids)
        if not companies.exists():
            raise CommandError("No companies matched. Nothing to do.")

        rows = [(c, self.holdings_for(c)) for c in companies.order_by("id")]

        skipped = []
        if options["keep_with_books"]:
            keep = [r for r in rows if r[1]["journals"]]
            rows = [r for r in rows if not r[1]["journals"]]
            skipped = keep

        self.print_table(rows)

        if skipped:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"SKIPPED, still holding books ({len(skipped)}) -- --keep-with-books"
                )
            )
            for company, holdings in skipped:
                self.stdout.write(
                    f"  [{company.id}] {str(company.uid)[:UID_PREFIX_LENGTH]} "
                    f"{company.name}  ({holdings['journals']} journals, "
                    f"{holdings['legs']} legs)"
                )

        if not rows:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Nothing left to delete."))
            return

        total_legs = sum(h["legs"] for _, h in rows)
        if total_legs:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    f"{total_legs:,} journal leg(s) will be destroyed. This is "
                    "irreversible and cannot be reconstructed. Soft-remove "
                    "(status=REMOVED) keeps the books and hides the company "
                    "everywhere in the product."
                )
            )

        if not options["apply"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS("Dry run -- nothing written. Re-run with --apply.")
            )
            return

        total, per_model = purge_companies([c for c, _ in rows])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {total:,} row(s) across {len(per_model)} model(s)."
            )
        )

    def print_table(self, rows):
        if not rows:
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Companies to delete: {len(rows)}")
        )
        self.stdout.write("")

        headers = ["id", "uid", "name", "legs"] + [n for n, _ in HOLDINGS]
        widths = [6, UID_PREFIX_LENGTH, 28, 8] + [max(6, len(n)) for n, _ in HOLDINGS]
        widths[2] = max(widths[2], min(40, max(len(c.name or "") for c, _ in rows)))

        def line(values):
            return "  ".join(
                str(v).ljust(w)[:w] if i < 3 else str(v).rjust(w)
                for i, (v, w) in enumerate(zip(values, widths))
            )

        self.stdout.write(line(headers))
        self.stdout.write("  ".join("-" * w for w in widths))

        totals = defaultdict(int)
        for company, holdings in rows:
            for key, value in holdings.items():
                totals[key] += value
            self.stdout.write(
                line(
                    [
                        company.id,
                        str(company.uid)[:UID_PREFIX_LENGTH],
                        company.name or "-",
                        holdings["legs"],
                    ]
                    + [holdings[n] for n, _ in HOLDINGS]
                )
            )

        self.stdout.write("  ".join("-" * w for w in widths))
        self.stdout.write(
            line(["", "", "TOTAL", totals["legs"]] + [totals[n] for n, _ in HOLDINGS])
        )
