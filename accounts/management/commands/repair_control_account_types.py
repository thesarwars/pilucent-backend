"""Restore a control account's classification from the industry template.

A control account is not an ordinary account. `get_chart_of_account` resolves it
by `system_key`, so every document of its kind posts to whichever row carries
that key -- and if that row is classified wrongly, the posting is still correct
while the account sits in the wrong place on the statements.

Production has 62, and they are three different faults, not one.

**Sixty detail types never resolved at all.** Until `cfd16a23` the templates
asked for a detail type called `Service` for the `Service` income account, and
the category tree carries no such node -- the name is `Service/Fee Income`.
`resolve_taxonomy_category` returned None and `create_chart_of_account` built the
account anyway with a null detail type, in every tenant onboarded before that
fix. Filling these in moves nothing: `_section_of` returns on the account type
alone for INCOMES accounts, so detail type is never read on that path, and no
report serializer renders it. Verified rather than assumed, because one of these
accounts carries 503 journal lines.

**Two hold a real value that disagrees with the template.** The
`UNDEPOSITED_FUNDS` rows on `Jumatechs Ltd` and `Jumatechs` are typed
`Other Current Asset` -- a genuine sibling of `Undeposited Funds` under the same
parent, and the tree's deliberate catch-all, still used by six template rows. So
this is not a null being filled; it is one valid classification replaced by
another, and no template revision ever produced it. The balance sheet buckets
Other Current Assets on account type alone, so the change is inert there, but the
provenance is unexplained -- which is why `--snapshot` exists.

**One account type is wrong.** `Talha-organization`'s `Accounts Payable (A/P)`
carries `system_key=AP`, so every bill that company raises resolves to it, and
its `account_type` is `Expense`. This one DOES move reported numbers, in the
direction of correct: `_section_for('Expense', ...)` matches no section, so the
account is currently dropped from the balance sheet entirely and its balance is
absent from Total Liabilities. After the repair it lands in A/P and flows through.
Only `total_for_equity` is computed by `kind`; every asset and liability bucket
keys on the account type title, so "the kind is right" is not the reassurance it
looks like.

    python manage.py repair_control_account_types
    python manage.py repair_control_account_types --company "Talha-organization"
    python manage.py repair_control_account_types --apply

This is repairable without judgement, which is what separates it from the rows
`repair_account_pairs` leaves alone. All twenty industry templates classify each
control account identically -- A/P is always `Accounts Payable (A/P)` /
`Accounts Payable` -- so there is one correct answer rather than a choice.

Only touches accounts whose classification actually disagrees with the template,
and never changes `kind`: if restoring the account type would move the account to
a different root, that is a bigger question than a script should answer and it is
reported instead.

⚠️ Writes with `.update()`, bypassing the model's reclassification guard. That
guard refuses to change `account_type` on an account with journal lines, because
doing so restates the periods it appears in -- correct as a rule, and wrong here:
these accounts are already misclassified, so this is restoring the classification
rather than changing it. The distinction is why this is a separate command with
its own dry run rather than a flag on the general repair.

⚠️ The same bypass means the write is invisible afterwards. `auditlog` hooks
`pre_save`/`post_save`, which a queryset `.update()` fires neither of, and
`auto_now` is applied in `Model.save_base`, so `updated_at` does not move either.
Nothing in the database distinguishes a repaired row from one that was always
correct. `--snapshot` writes the pre-state to CSV and is the only rollback there
is; use it.
"""

import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    SYSTEM_KEY_TO_TITLE,
    resolve_taxonomy_category,
    root_kind_of as _root_of,
)

from companyio.django_rest.helpers.chart_of_accounts import chart_of_accounts

from companyio.models import Company


def canonical_pair(system_key):
    """`(account_type_title, detail_type_title)` the templates agree on, or None.

    Returns None where the templates disagree, so a key with no single answer is
    reported rather than resolved arbitrarily.
    """
    title = SYSTEM_KEY_TO_TITLE.get(system_key)
    if not title:
        return None
    pairs = {
        (row["account_type_title"], row["detail_type_title"])
        for block in chart_of_accounts
        for row in block["chart_of_accounts"]
        if row.get("title") == title
    }
    return pairs.pop() if len(pairs) == 1 else None


class Command(BaseCommand):
    help = "Restore control accounts' account/detail type from the templates."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Company name (icontains) or id.")
        parser.add_argument(
            "--apply", action="store_true", help="Write. Without it, dry run."
        )
        parser.add_argument(
            "--snapshot",
            metavar="PATH",
            help=(
                "Write every control account's current classification to CSV "
                "before touching anything. The only rollback this command has."
            ),
        )

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

        detail_only, repairable, root_change, no_answer = [], [], [], []

        controls = (
            ChartOfAccount.objects.filter(
                company__in=companies, system_key__isnull=False
            )
            .exclude(status=ChartOfAccountStatusChoices.REMOVED)
            .select_related("company", "account_type", "detail_type")
        )

        for account in controls:
            pair = canonical_pair(account.system_key)
            if pair is None:
                continue
            want_type, want_detail = pair
            current_type = account.account_type.title if account.account_type else None
            current_detail = (
                account.detail_type.title if account.detail_type else None
            )
            if (current_type, current_detail) == (want_type, want_detail):
                continue

            # Both halves through the hardened resolver, which restricts to the
            # shipped global taxonomy. A raw `Category.objects.filter(title=...,
            # parent=...)` looks equivalent and is not: `Category.company` is
            # nullable and tenant-writable, and `ordering = ("-created_at",)`
            # makes `.first()` return the NEWEST match -- so any tenant that
            # created a category named "Service/Fee Income" under the shipped
            # `Income` node would have had its private row written into the
            # control accounts of all sixty other companies. The detail half
            # used to do exactly that.
            new_type = resolve_taxonomy_category(want_type)
            new_detail = (
                resolve_taxonomy_category(want_detail, parent=new_type)
                if new_type is not None
                else None
            )
            # Both halves must resolve. Writing a null detail type is not a
            # repair -- it is the exact damage this command exists to undo, and
            # the templates caused it once already by naming a detail type
            # ("Service") that the category tree does not carry.
            if new_type is None or new_detail is None:
                no_answer.append((account, want_type, want_detail))
            elif _root_of(new_type) != (account.kind or "").upper():
                root_change.append((account, want_type, want_detail))
            elif current_type == want_type:
                detail_only.append((account, new_type, new_detail, current_detail))
            else:
                repairable.append((account, new_type, new_detail, current_detail))

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Control account classification -- {controls.count()} control "
                f"accounts across {companies.count()} company(ies)"
            )
        )
        self.stdout.write(f"  detail type only          : {len(detail_only)}")
        self.stdout.write(f"  account type and detail   : {len(repairable)}")
        self.stdout.write(f"  would change kind         : {len(root_change)}")
        self.stdout.write(f"  no template answer        : {len(no_answer)}")
        self.stdout.write("")

        self._list_repairs(
            "Detail type only -- account type, kind and side unchanged",
            detail_only,
        )
        self._list_repairs(
            "Account type changes -- regroups the account on the statements",
            repairable,
        )

        for account, want_type, _d in root_change:
            self.stdout.write(
                self.style.WARNING(
                    f"  {account.company.name[:22]:<24} id={account.id:<6} "
                    f"{account.system_key:<24} kind={account.kind} but the "
                    f"template says {want_type!r} -- resolve by hand"
                )
            )
        # The one bucket meaning "the taxonomy is still broken and I could not
        # resolve this" was only ever a number. Print it: it is the bucket that
        # says a template names a category the tree does not carry, which is the
        # fault that produced these sixty null detail types in the first place.
        for account, want_type, want_detail in no_answer:
            self.stdout.write(
                self.style.ERROR(
                    f"  {account.company.name[:22]:<24} id={account.id:<6} "
                    f"{account.system_key:<24} template wants "
                    f"{want_type!r}/{want_detail!r}, not in the category tree"
                )
            )
        self.stdout.write("")

        if options["snapshot"]:
            written = self._snapshot(controls, options["snapshot"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Snapshot: {written} control accounts -> {options['snapshot']}"
                )
            )
            self.stdout.write("")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("Dry run -- nothing changed. Re-run with --apply.")
            )
            return

        if not options["snapshot"]:
            self.stdout.write(
                self.style.WARNING(
                    "No --snapshot given. The write leaves no audit trail and does "
                    "not move updated_at, so nothing afterwards can tell you what "
                    "these rows held."
                )
            )

        # One transaction. Not because a partial apply is unrecoverable -- the
        # dry run recomputes the remaining work from present state, so re-running
        # is safe -- but because a partial apply is indistinguishable from a
        # complete one afterwards, for the same reason the snapshot exists.
        with transaction.atomic():
            for account, new_type, new_detail, _was in detail_only + repairable:
                # .update() on purpose -- see the module docstring. The model
                # guard refuses to reclassify a posted account, which is right in
                # general and wrong for restoring a classification that is
                # already incorrect.
                ChartOfAccount.objects.filter(pk=account.pk).update(
                    account_type=new_type, detail_type=new_detail
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Restored {len(detail_only) + len(repairable)} control account(s)."
            )
        )

    def _snapshot(self, controls, path):
        """Every control account's classification, by id, before anything moves.

        Ids rather than titles, because a title is not what gets written and two
        categories can share one. `company_id` on each category is here so the
        restore can also answer the question the command itself cannot: whether
        a row was ever pointed at a tenant-owned category rather than a shipped
        one.
        """
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "chart_of_account_id",
                    "company_id",
                    "system_key",
                    "kind",
                    "account_type_id",
                    "account_type_title",
                    "account_type_company_id",
                    "detail_type_id",
                    "detail_type_title",
                    "detail_type_company_id",
                ]
            )
            count = 0
            for account in controls:
                account_type, detail_type = account.account_type, account.detail_type
                writer.writerow(
                    [
                        account.id,
                        account.company_id,
                        account.system_key,
                        account.kind,
                        getattr(account_type, "id", None),
                        getattr(account_type, "title", None),
                        getattr(account_type, "company_id", None),
                        getattr(detail_type, "id", None),
                        getattr(detail_type, "title", None),
                        getattr(detail_type, "company_id", None),
                    ]
                )
                count += 1
        return count

    def _list_repairs(self, title, rows):
        """One line per repair, showing BOTH halves of the classification.

        Printing only the account type is what made the first production run
        unreadable: 60 rows reported as 'Income' -> 'Income', because the type
        already agreed and the whole change was a detail type that had never
        resolved.
        """
        if not rows:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        for account, new_type, new_detail, was_detail in rows:
            lines = account.journalentryconnector_set.count()
            was_type = account.account_type.title if account.account_type else None
            self.stdout.write(
                f"  {account.company.name[:22]:<24} id={account.id:<6} "
                f"{account.system_key:<24} lines={lines:<4} "
                f"{was_type!r}/{was_detail!r} -> "
                f"{new_type.title!r}/{new_detail.title!r}"
            )
        self.stdout.write("")
