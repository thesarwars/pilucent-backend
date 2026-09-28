"""Validate the per-industry chart-of-account seed templates.

Nothing asserted that these 20 templates were internally consistent, and they
are not: roughly 30% of their rows reference an `account_type` / `detail_type`
pair that does not exist in the category tree. `create_chart_of_accounts`
(`companyio/django_rest/helpers/signal_helpers.py`) fails **silently** on every
one of them:

    account_type = Category.objects.filter(title=item["account_type_title"]).first()
    if account_type:                         # unknown type -> row SKIPPED entirely
        ChartOfAccount.objects.create(
            detail_type=Category.objects.filter(
                title=item["detail_type_title"]
            ).first(),                       # not found -> NULL, no error
            ...

So an unknown account type means the account is never created, and an unknown
detail type means it is created untyped. `detail_type` is not decoration -- the
payroll reports and the balance-sheet payroll carve-out filter on it -- so an
untyped account silently drops out of those reports.

This command turns that invisible damage into a list. It reads the seed modules
and the category tree only; it touches no database rows and is safe anywhere.

    python manage.py validate_chart_of_account_seeds
    python manage.py validate_chart_of_account_seeds --industry ECOMMERCE
    python manage.py validate_chart_of_account_seeds --only taxonomy
    python manage.py validate_chart_of_account_seeds --strict     # exit 1 on failure

`--strict` is for CI and is usable today: every check currently fails, and those
counts are recorded as a baseline, so the build stays green on known debt and
fails the moment a seed edit makes anything worse. Lower the baseline as each
fix lands -- the goal is to delete it.

Checks
------
1. `account_type_title` resolves in the category tree.
2. `detail_type_title` is a **child of that account type**.
3. `code` is unique within an industry.
4. `title` is unique within an industry.
5. The control-account spine is present in every industry.
6. `code` sits in the range for its kind.

All six currently fail -- see BASELINE below. Each reports "as expected" while at
or below its recorded count and complains only when it grows.
"""

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from categoryio.management.commands.data.chart_of_accounts import categories
from companyio.django_rest.helpers.chart_of_accounts import chart_of_accounts


# The titles the posting code resolves through get_chart_of_account(). Derived
# from every literal passed to it, with the number of call sites that depend on
# each -- a company missing any of these cannot post the corresponding document.
CONTROL_ACCOUNTS = [
    "Inventory Asset",
    "Accounts Payable (A/P)",
    "Sales Tax Payable",
    "Accounts Receivable (A/R)",
    "Undeposited Funds",
    "Opening Balance Equity",
    "Cost of Goods Sold (COGS)",
    "Other Miscellaneous Expense",
    "Service",
    "Sales of Product Income",
    # Added for the discount and shipping legs -- a sale that charges either has
    # nowhere to post the credit without them.
    "Sales Discounts",
    "Shipping Income",
]

# Seed templates follow this convention so the charts we ship are coherent.
# It binds SEED DATA ONLY -- a user may number their own accounts however they
# like, and there is deliberately no constraint or API validation on that.
# The bands a seeded account's code may fall in, per kind.
#
# Revised 2026-08-06. The original single band per kind put INCOMES at
# 4000-4999 only, which flagged 35 rows -- every one of them an "Other Income"
# account numbered in the 7000s. That is not a data error: numbering
# non-operating income and expense together in the 7000s is the ordinary
# convention, and the templates follow it consistently. The convention was
# adjusted to admit it rather than renumbering correct data to match a rule that
# was too narrow.
#
# So the 7000s are the non-operating band, shared by Other Income and Other
# Expenses. That makes 7xxx ambiguous between two kinds, which is the price of
# matching how these charts are actually written -- and the account type, not
# the code, is what the software reads.
#
# This deviates from BLZ-FIN-COA-SPEC-001 §7.2, which splits non-operating into
# 8000-8499 (Other Income) and 8500-8999 (Other Expense). The deviation is
# deliberate and is recorded in that specification at **§7.7.2**, along with the
# reasoning above and what a migration back to §7.2 would involve. Spec §7.7.1
# records the companion decision not to build §7.4-§7.6 at all -- the account
# number is never read to make a decision, so the bands bind seed coherence
# only. If you change this table, update §7.7.2 with it.
CODE_RANGES = {
    "ASSETS": [(1000, 1999)],
    "LIABILITIES": [(2000, 2999)],
    "EQUITIES": [(3000, 3999)],
    # operating revenue; non-operating income
    "INCOMES": [(4000, 4999), (7000, 7999)],
    # COGS 5000s, operating expense 6000s, non-operating 7000s
    "EXPENSES": [(5000, 7999)],
}

# Known debt, measured on 2026-08-05. EVERY check currently fails -- that is the
# point of writing this command before fixing anything. Recording the counts here
# means `--strict` is usable in CI *today*: the build stays green on the debt we
# already know about, and fails the moment a seed edit makes anything worse.
#
# That is the whole purpose of this command. Seed defects are DATA, not logic --
# no code review catches them and every existing test passes regardless.
#
# **Lower each number as remediation lands. The goal is to delete this dict.**
#
# code_range note: the audit doc cites 56. That figure is not reproducible under
# any single rule -- counting against the literal bands gives 246, and counting
# only codes landing in another kind's band gives 54. 60 is what the convention
# adopted on 2026-08-05 actually yields (EXPENSES spans 5000-7999, absorbing COGS).
BASELINE = {
    # taxonomy: CLEARED 2026-08-06, 486 -> 0 across two passes. First the 14 rows
    # whose account_type did not exist at all, so the account was never created;
    # then the remaining 472, which were 86 distinct bad pairs -- mostly near-miss
    # names ("Professional Fees" for "Legal & Professional Fees") plus 51 rows
    # whose detail type was real but sat under a different account type.
    #
    # No tolerance from here. Every seeded account now resolves both halves of
    # its classification, and seeding enforces the parent relationship, so a
    # regression means new rows were added without checking them against the
    # tree -- which is the exact failure this command exists to prevent.
    "taxonomy": 0,
    # 48 -> 47 on 2026-08-06: renumbering the renamed Sales Discounts account in
    # business_services_consulting incidentally resolved a pre-existing 4060
    # collision with "Licensing Revenue".
    # codes: CLEARED 2026-08-06, 47 -> 0. The COGS renumbering took 18 of them;
    # hardware_electronics -- two charts concatenated -- took another 18; the
    # rest were distinct accounts that happened to share a code and were moved
    # to the next free slot in their own band.
    "codes": 0,
    # titles: CLEARED 2026-08-06, 5 -> 0. Two were byte-identical rows listed
    # twice. Three were genuinely different accounts sharing one name, the worst
    # being restaurant_hotel's "Property Taxes", which existed as both the
    # expense paid and the liability owed.
    "titles": 0,
    # spine: CLEARED 2026-08-05. Every industry now ships all ten control
    # accounts -- food_beverage was the last, and it had none of them. Any
    # regression here means a template lost a control account, which stops that
    # industry posting entirely, so this one has no tolerance.
    "spine": 0,
    # code_range: CLEARED 2026-08-06. 60 -> 41 by renumbering COGS out of the
    # asset band, then 41 -> 6 by widening the convention to admit the 7000s for
    # non-operating income (see CODE_RANGES), then 6 -> 0 by renumbering the
    # genuine strays food_beverage had parked in the 8000s and 9000s.
    "code_range": 0,
    # Added 2026-08-06 and clean from the start, having found and fixed the one
    # row that failed it. No tolerance.
    "kind_matches_type": 0,
}

CHECKS = ("taxonomy", "codes", "titles", "spine", "code_range", "kind_matches_type")


def build_tree():
    """(kind by account_type, detail types by account_type) from the seed tree."""
    kind_of = {}
    children = defaultdict(set)
    for root in categories:
        for account_type in root.get("options", []) or []:
            kind_of[account_type["title"]] = root["title"]
            for detail in account_type.get("options", []) or []:
                children[account_type["title"]].add(detail["title"])
    return kind_of, children


def industries():
    """(industry name, rows) per seeded company kind."""
    for block in chart_of_accounts:
        yield str(block["kind"]), block["chart_of_accounts"]


class Command(BaseCommand):
    help = "Validate the per-industry chart-of-account seed templates."

    def add_arguments(self, parser):
        parser.add_argument("--industry", help="Only this company kind (icontains).")
        parser.add_argument(
            "--only", choices=CHECKS, help="Run a single check."
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit 1 if any check fails beyond its baseline (for CI).",
        )

    def handle(self, *args, **options):
        kind_of, children = build_tree()
        wanted = options.get("industry")
        only = options.get("only")

        blocks = [
            (name, rows)
            for name, rows in industries()
            if not wanted or wanted.upper() in name.upper()
        ]
        if not blocks:
            self.stderr.write(self.style.ERROR(f"No industry matches {wanted!r}."))
            return

        total_rows = sum(len(rows) for _, rows in blocks)
        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Chart-of-account seed validation -- {len(blocks)} industries, "
                f"{total_rows} rows"
            )
        )
        self.stdout.write(
            f"  category tree: {len(kind_of)} account types, "
            f"{sum(len(v) for v in children.values())} detail types"
        )
        self.stdout.write("")

        failures = {}
        if only in (None, "taxonomy"):
            failures["taxonomy"] = self.check_taxonomy(blocks, kind_of, children)
        if only in (None, "codes"):
            failures["codes"] = self.check_duplicates(blocks, "code")
        if only in (None, "titles"):
            failures["titles"] = self.check_duplicates(blocks, "title")
        if only in (None, "spine"):
            failures["spine"] = self.check_spine(blocks)
        if only in (None, "code_range"):
            failures["code_range"] = self.check_code_ranges(blocks, kind_of)
        if only in (None, "kind_matches_type"):
            failures["kind_matches_type"] = self.check_kind_matches_type(
                blocks, kind_of
            )

        self.summarise(failures, options["strict"])

    # -- checks ------------------------------------------------------------

    def check_taxonomy(self, blocks, kind_of, children):
        """Checks 1 and 2 -- the pair must exist in the tree.

        Reported as two buckets because they need different fixes: an unknown
        account type means the row is never created at all, while an unknown or
        mis-parented detail type means the account exists but is untyped.
        """
        never_created = []
        untyped = []
        misparented = []
        known_details = {d for kids in children.values() for d in kids}

        for name, rows in blocks:
            for row in rows:
                account_type = row.get("account_type_title")
                detail_type = row.get("detail_type_title")
                if account_type not in kind_of:
                    never_created.append((name, row["title"], account_type))
                elif detail_type not in known_details:
                    untyped.append((name, row["title"], detail_type))
                elif detail_type not in children[account_type]:
                    misparented.append((name, row["title"], account_type, detail_type))

        self.section("1-2. Taxonomy (account_type / detail_type)")
        self.report(
            "account never created (unknown account_type)",
            never_created,
            lambda item: f"{item[0]}: {item[1]!r} -> account_type {item[2]!r}",
            counter=lambda item: item[2],
        )
        self.report(
            "detail_type = NULL (title exists nowhere in the tree)",
            untyped,
            lambda item: f"{item[0]}: {item[1]!r} -> detail_type {item[2]!r}",
            counter=lambda item: item[2],
        )
        self.report(
            "detail_type belongs to a different account_type",
            misparented,
            lambda item: f"{item[0]}: {item[1]!r} -> {item[2]!r} / {item[3]!r}",
            counter=lambda item: f"{item[2]} -> {item[3]}",
        )
        return len(never_created) + len(untyped) + len(misparented)

    def check_duplicates(self, blocks, field):
        """Checks 3 and 4 -- `code` / `title` unique within one industry."""
        offenders = []
        for name, rows in blocks:
            counts = Counter(row.get(field) for row in rows)
            for value, count in sorted(counts.items()):
                if count > 1:
                    offenders.append((name, value, count))

        number = "3" if field == "code" else "4"
        self.section(f"{number}. Duplicate {field}s within an industry")
        self.report(
            f"duplicate {field}",
            offenders,
            lambda item: f"{item[0]}: {item[1]!r} x{item[2]}",
        )
        return len(offenders)

    def check_spine(self, blocks):
        """Check 5 -- the control accounts the posting code resolves by title."""
        offenders = []
        for name, rows in blocks:
            present = {row.get("title") for row in rows}
            missing = [title for title in CONTROL_ACCOUNTS if title not in present]
            if missing:
                offenders.append((name, missing))

        self.section("5. Control-account spine")
        self.report(
            "industry missing control accounts",
            offenders,
            lambda item: f"{item[0]}: missing {len(item[1])} -- {', '.join(item[1])}",
            limit=25,
        )
        return sum(len(missing) for _, missing in offenders)

    def check_kind_matches_type(self, blocks, kind_of):
        """Check 7 -- the declared `kind` agrees with the account type's root.

        These are two independent fields in the seed, and nothing tied them
        together. Seeding does not read the declared one at all: it derives kind
        from `account_type.parent`, so a row declaring ASSETS while pointing at a
        liability account type is created as a LIABILITY, and the declared value
        is silently decorative.

        Found exactly one, and it was real: real_estate's "Prepaid Expenses" --
        an asset by any reading -- carried `account_type_title` of "Other Current
        Liabilities", so every real-estate tenant got it on the wrong side of the
        balance sheet. Nothing else in this command could see it, because the
        pair it formed was internally consistent; only the disagreement with the
        declared kind gave it away.
        """
        offenders = []
        for name, rows in blocks:
            for row in rows:
                declared = str(row.get("kind", "")).split(".")[-1]
                implied = kind_of.get(row.get("account_type_title"))
                if not declared or not implied:
                    continue
                if declared != implied.upper():
                    offenders.append(
                        (name, row["title"], declared, implied.upper(),
                         row.get("account_type_title"))
                    )

        self.section("7. Declared kind vs account type")
        self.report(
            "declared kind disagrees with the account type's root",
            offenders,
            lambda i: (f"{i[0]}: {i[1]!r} says {i[2]} but "
                       f"{i[4]!r} makes it {i[3]}"),
            counter=lambda i: f"{i[2]} declared, {i[3]} implied",
        )
        return len(offenders)

    def check_code_ranges(self, blocks, kind_of):
        """Check 6 -- seed codes follow the numbering convention.

        Seed templates only. User-created accounts may use any code.
        """
        offenders = []
        for name, rows in blocks:
            for row in rows:
                kind = str(row.get("kind", "")).split(".")[-1]
                bands = CODE_RANGES.get(kind)
                if not bands:
                    continue
                try:
                    code = int(row.get("code") or -1)
                except (TypeError, ValueError):
                    code = -1
                if not any(low <= code <= high for low, high in bands):
                    offenders.append((name, row["title"], row.get("code"), kind))

        self.section("6. Code ranges (seed templates only)")
        self.report(
            "code outside the range for its kind",
            offenders,
            lambda item: f"{item[0]}: {item[1]!r} code {item[2]} ({item[3]})",
            counter=lambda item: f"{item[1]} ({item[3]})",
        )
        return len(offenders)

    # -- output ------------------------------------------------------------

    def section(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def report(self, label, offenders, formatter, counter=None, limit=12):
        if not offenders:
            self.stdout.write(self.style.SUCCESS(f"  OK   {label}: none"))
            return
        self.stdout.write(self.style.ERROR(f"  FAIL {label}: {len(offenders)}"))
        if counter is not None:
            # Group by cause -- these are overwhelmingly a handful of repeated
            # near-miss spellings, and the grouping is what makes them fixable.
            grouped = Counter(counter(item) for item in offenders)
            for cause, count in grouped.most_common(limit):
                self.stdout.write(f"         {count:>4}x  {cause}")
            if len(grouped) > limit:
                self.stdout.write(f"         ... {len(grouped) - limit} more causes")
        else:
            for item in offenders[:limit]:
                self.stdout.write(f"         {formatter(item)}")
            if len(offenders) > limit:
                self.stdout.write(f"         ... {len(offenders) - limit} more")
        self.stdout.write("")

    def summarise(self, failures, strict):
        self.stdout.write("")
        self.section("Summary")
        worse_than_baseline = False
        for check, count in failures.items():
            baseline = BASELINE.get(check)
            if count == 0:
                self.stdout.write(self.style.SUCCESS(f"  {check:<12} clean"))
            elif baseline is not None and count <= baseline:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {check:<12} {count} (baseline {baseline} -- as expected, "
                        "remediation pending)"
                    )
                )
            else:
                worse_than_baseline = True
                suffix = f" (baseline {baseline} -- REGRESSED)" if baseline else ""
                self.stdout.write(self.style.ERROR(f"  {check:<12} {count}{suffix}"))

        outstanding = sum(failures.values())
        self.stdout.write("")
        if worse_than_baseline:
            self.stdout.write(
                self.style.ERROR(
                    "REGRESSION -- a seed template got worse. Fix before merging."
                )
            )
            if strict:
                raise SystemExit(1)
        elif outstanding:
            self.stdout.write(
                self.style.WARNING(
                    f"No regression. {outstanding} known defects outstanding -- "
                    "lower the baseline in this file as each fix lands."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Seed templates are clean. Delete BASELINE from this file."
                )
            )
