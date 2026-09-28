"""An inactive account must not be offered when building a new document.

The other half of deactivation. Without it the state exists and the endpoint
works, but every account picker still lists the account you just retired -- the
feature looks finished and is not.

The two halves have opposite requirements, which is the whole difficulty:

* **Pickers** -- the writable related fields on serializers -- must withhold it.
  A user must not be able to put a retired account on a new invoice.
* **Everything else** -- reports, statements, registers, the ledger resolver,
  the chart-of-accounts list itself -- must keep showing it. An inactive account
  keeps its balance and its history; hiding it there would silently drop figures
  out of the books, which is the opposite of what s9.4 asks for.

That is why `selectable()` exists beside `get_status_all()` rather than
replacing it. `get_status_all()` excludes only REMOVED and is correct for the
second group; `selectable()` narrows to ACTIVE and belongs on pickers only.

Two call sites are deliberately excluded from the sweep and asserted below, so
"it was missed" and "it was decided" stay distinguishable.
"""

import re
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
)
from accounts.models import ChartOfAccount

from companyio.choices import CompanyKindChoices
from companyio.models import Company


# Assigns to a local `queryset` variable rather than a field kwarg, and must keep
# returning inactive accounts. Each needs a reason so the list cannot quietly
# absorb a real miss.
DELIBERATELY_UNNARROWED = {
    # The chart-of-accounts list itself. Hiding inactive accounts here would
    # leave a user no way to see, or reactivate, what they retired.
    "weapi/django_rest/views/chart_of_accounts.py",
    # Net income is a figure over the ledger. An inactive account's balance is
    # still in the books and still belongs in the total.
    "weapi/utils/net_income_calculator.py",
}


class SelectableQuerySetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )

    def account(self, title, status):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code="6990",
            kind=ChartOfAccountKindChoices.EXPENSES, status=status,
        )

    def test_selectable_offers_active_only(self):
        active = self.account("Live", Status.ACTIVE)
        inactive = self.account("Retired", Status.INACTIVE)
        removed = self.account("Gone", Status.REMOVED)

        selectable = ChartOfAccount.objects.filter(company=self.company).selectable()

        self.assertIn(active, selectable)
        self.assertNotIn(inactive, selectable)
        self.assertNotIn(removed, selectable)

    def test_get_status_all_still_includes_inactive(self):
        """Reports and resolvers must keep seeing it -- this is the point."""
        inactive = self.account("Retired", Status.INACTIVE)

        self.assertIn(
            inactive,
            ChartOfAccount.objects.filter(company=self.company).get_status_all(),
        )

    def test_selectable_still_offers_draft_and_pending(self):
        """It must narrow by exactly one state, and no more.

        `status` defaults to **DRAFT** on the model, so an ACTIVE-only filter
        here silently withheld every account created without an explicit status
        -- which is most of them outside the seeding path. Production hides
        that, because seeding sets ACTIVE and holds no DRAFT rows.
        """
        draft = self.account("Draft", Status.DRAFT)
        pending = self.account("Pending", Status.PENDING)

        selectable = ChartOfAccount.objects.filter(company=self.company).selectable()

        self.assertIn(draft, selectable)
        self.assertIn(pending, selectable)

    def test_an_account_created_without_a_status_is_selectable(self):
        """The default path, and the one the first cut of this broke."""
        account = ChartOfAccount.objects.create(
            company=self.company, title="Defaulted", code="6991",
            kind=ChartOfAccountKindChoices.EXPENSES,
        )

        self.assertEqual(account.status, Status.DRAFT)
        self.assertIn(
            account, ChartOfAccount.objects.filter(company=self.company).selectable()
        )

    def test_it_chains_from_the_manager_and_from_a_queryset(self):
        """The sweep relies on both, since call sites use each shape."""
        self.assertTrue(hasattr(ChartOfAccount.objects, "selectable"))
        self.assertTrue(hasattr(ChartOfAccount.objects.all(), "selectable"))


class PickerSweepTests(TestCase):
    """Ratchet: a new account picker must not forget to narrow itself."""

    PICKER = re.compile(r"queryset=ChartOfAccount\.objects\.")

    def picker_sites(self):
        found = []
        for path in sorted(Path(".").rglob("*.py")):
            text = str(path)
            if any(
                skip in text
                for skip in ("migrations", "/benv/", "/tests", "test_")
            ):
                continue
            source = path.read_text(errors="ignore")
            for match in self.PICKER.finditer(source):
                line = source[: match.start()].count("\n") + 1
                snippet = source[match.start(): match.start() + 70]
                found.append((str(path).lstrip("./"), line, snippet))
        return found

    def test_every_picker_is_narrowed_to_selectable(self):
        offenders = [
            f"{path}:{line}"
            for path, line, snippet in self.picker_sites()
            if ".selectable()" not in snippet
        ]

        self.assertEqual(
            offenders,
            [],
            "account picker(s) that would offer a retired account:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_sweep_still_finds_pickers(self):
        """Guards the guard: a regex that matches nothing would pass silently."""
        self.assertGreater(len(self.picker_sites()), 40)

    def test_the_unnarrowed_call_sites_are_the_ones_we_chose(self):
        """`queryset = ` with a space is the non-picker form -- keep it deliberate."""
        local = re.compile(r"queryset = ChartOfAccount\.objects\.")
        found = set()
        for path in sorted(Path(".").rglob("*.py")):
            text = str(path)
            if any(
                skip in text for skip in ("migrations", "/benv/", "/tests", "test_")
            ):
                continue
            if local.search(path.read_text(errors="ignore")):
                found.add(str(path).lstrip("./"))

        self.assertEqual(
            found,
            DELIBERATELY_UNNARROWED,
            "a call site started or stopped returning inactive accounts -- decide "
            "whether it is a picker (narrow it) or a report (add it here with a "
            "reason)",
        )


class HeaderAccountsAreNotOfferedTests(TestCase):
    """Spec s9.2 / COA-131: data belongs at leaf level.

    Production shows the cost of not enforcing it: one company posted 13,500 of
    payroll to "Company Contributions", a parent, so the figure sits on a
    summary line while its children total something else. Fleet-wide only 5
    lines land on parents, and 4 of them are zero-value or an opening balance --
    so this is a pattern worth stopping before it grows, not a widespread mess.

    Withheld from pickers rather than refused at posting time. The spec makes
    COA-131 a validation error, but one of those four accounts is a live payroll
    route, and refusing outright would turn a working pay run into a 400.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Header Co", kind=CompanyKindChoices.ECOMMERCE
        )

    _seq = 0

    def account(self, title, parent=None, status=Status.ACTIVE):
        type(self)._seq += 1
        return ChartOfAccount.objects.create(
            company=self.company, title=f"{title} {type(self)._seq}",
            code=f"68{type(self)._seq:02d}",
            kind=ChartOfAccountKindChoices.EXPENSES, status=status, parent=parent,
        )

    def selectable(self):
        return ChartOfAccount.objects.filter(company=self.company).selectable()

    def test_a_leaf_is_offered(self):
        leaf = self.account("Ordinary")

        self.assertIn(leaf, self.selectable())

    def test_a_parent_is_not_offered(self):
        parent = self.account("Payroll Expenses")
        self.account("Wages", parent=parent)

        self.assertNotIn(parent, self.selectable())

    def test_the_child_is_still_offered(self):
        """Only the summary line is withheld; the leaf is where data goes."""
        parent = self.account("Payroll Expenses")
        child = self.account("Wages", parent=parent)

        self.assertIn(child, self.selectable())

    def test_an_account_whose_only_child_is_retired_is_offered_again(self):
        """A parent stops being a header when it stops having children."""
        parent = self.account("Payroll Expenses")
        child = self.account("Wages", parent=parent)

        self.assertNotIn(parent, self.selectable())

        child.status = Status.REMOVED
        child.save(update_fields=["status"])

        self.assertIn(parent, self.selectable())

    def test_an_inactive_child_does_not_make_a_header(self):
        parent = self.account("Payroll Expenses")
        self.account("Wages", parent=parent, status=Status.INACTIVE)

        self.assertIn(parent, self.selectable())

    def test_reports_still_see_the_parent(self):
        """`get_status_all()` is unchanged -- headers belong on statements."""
        parent = self.account("Payroll Expenses")
        self.account("Wages", parent=parent)

        self.assertIn(
            parent,
            ChartOfAccount.objects.filter(company=self.company).get_status_all(),
        )

    def test_a_parent_with_several_children_is_excluded_once(self):
        """The join must not duplicate the row out of the queryset."""
        parent = self.account("Payroll Expenses")
        for name in ("Wages", "Taxes", "Benefits"):
            self.account(name, parent=parent)

        selectable = list(self.selectable())

        self.assertNotIn(parent, selectable)
        self.assertEqual(len(selectable), len(set(a.pk for a in selectable)))
