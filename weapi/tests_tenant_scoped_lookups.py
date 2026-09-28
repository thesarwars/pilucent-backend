"""Records resolved by `uid` alone, on models with no row-level security.

The sweep that followed `COA_FIX_PLAN_V3.md` P0.1 found 46 `get_object_or_404`
calls with no company filter. Most were fine: 8 were scoped indirectly, and 17
sit on ChartOfAccount, Product, Sale or Purchase, which carry a forced RLS
policy, so the database refuses a cross-tenant row even when the query forgets.

The rest sit on models with **no such policy** -- CreditNote, Supplier,
AgencyTax, FileItem, Employee, PayBill, PurchasePayment, Inbox -- where the
application filter was the only control and it was missing.

Two things this file exists to remember:

**The first sweep had the wrong shape.** It matched `get_object_or_404` only. A
second pass for `Model.objects.filter(uid=...)` and `.objects.get(uid=...)`
found 19 more, including two AgencyTax sites that the first fix had declared
complete. The call-site test below sweeps for the general shape rather than one
spelling of it.

**A written check is not an applied one.** `views/support_and_tickets.py`
assigned `filters["user"] = user` for non-staff -- into a dict that was never
read again, because the object had already been fetched two lines above. The
ownership check existed in the source and did nothing.
"""

import re
from pathlib import Path

from django.test import TestCase

from accounts.models import User

from companyio.models import Company, CompanyUser

from messageio.choices import InboxKindChoices
from messageio.models import Inbox


# Models with no RLS policy: for these the application filter is the only
# control. Kept as a list so a model gaining RLS is a deliberate edit here.
UNPROTECTED_MODELS = [
    "AgencyTax",
    "BankReconciliation",
    "CreditNote",
    "Employee",
    "FileItem",
    "PayBill",
    "PurchasePayment",
    "StockAdjustmentItem",
    "Supplier",
]

# Sites that cannot be scoped by company and are handled another way. Each needs
# a reason, so the list cannot quietly absorb a real miss.
ALLOWED_UNSCOPED = {
    # `Expense` has no company column. The endpoint returns Purchases, and those
    # are filtered by company -- see the comment at the call site.
    "weapi/django_rest/views/purchases.py": ["Expense.objects.filter"],
    # Scoped to its PARENT rather than to the company, which is narrower: the
    # adjustment is already tenant-scoped by the view's `get_object`, and a line
    # belonging to a different adjustment of the same company has no business
    # being rewritten by this endpoint either. Before the fix this was a bare
    # `.objects.get(uid=...)` on a model with no RLS policy -- a write straight
    # into another company's stock adjustment line.
    "weapi/django_rest/serializers/stock.py": [
        "StockAdjustmentItem.objects.filter(\n                            uid=",
    ],
}


class CallSiteSweepTests(TestCase):
    def unscoped_lookups(self):
        pattern = re.compile(
            r"\b(" + "|".join(UNPROTECTED_MODELS) + r")\.objects\.(filter|get)\("
        )
        found = []
        for path in sorted(Path("weapi").rglob("*.py")):
            if path.name.startswith("tests"):
                continue
            source = path.read_text()
            for match in pattern.finditer(source):
                i, depth = match.end(), 1
                while i < len(source) and depth:
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                    i += 1
                call = source[match.start(): i]
                if "uid" not in call:
                    continue
                if "company" in call or "user" in call or "agency" in call:
                    continue
                allowed = ALLOWED_UNSCOPED.get(str(path), [])
                if any(call.startswith(prefix) for prefix in allowed):
                    continue
                found.append(
                    (str(path), source[: match.start()].count("\n") + 1,
                     " ".join(call.split())[:90])
                )
        return found

    def test_no_unprotected_model_is_resolved_by_uid_alone(self):
        unscoped = self.unscoped_lookups()

        self.assertEqual(
            unscoped,
            [],
            "these resolve a record by uid with no tenant filter, on models "
            "with no RLS backstop:\n"
            + "\n".join(f"  {f}:{n}  {c}" for f, n, c in unscoped),
        )

    def test_the_sweep_can_still_see_call_sites(self):
        """Guards the guard: a broken regex would pass the test above silently."""
        pattern = re.compile(
            r"\b(" + "|".join(UNPROTECTED_MODELS) + r")\.objects\.(filter|get)\("
        )
        total = sum(
            len(pattern.findall(p.read_text()))
            for p in Path("weapi").rglob("*.py")
            if not p.name.startswith("tests")
        )
        self.assertGreater(total, 20, "the sweep stopped matching anything")


class SupportTicketOwnershipTests(TestCase):
    """The check that was written but never applied."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.owner = User.objects.create_user(
            name="Owner", email="owner@example.com", password="pass1234!"
        )
        cls.stranger = User.objects.create_user(
            name="Stranger", email="stranger@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.owner, company=cls.company)
        cls.ticket = Inbox.objects.create(
            user=cls.owner,
            kind=InboxKindChoices.SUPPORT_AND_TICKET,
            title="Cannot reconcile March",
        )

    def fetch_as(self, user):
        from weapi.django_rest.views.support_and_tickets import (
            PrivateWeSupportTicketDetails,
        )

        view = PrivateWeSupportTicketDetails()
        view.kwargs = {"uid": str(self.ticket.uid)}
        view.request = type("R", (), {"user": user})()
        return view.get_object()

    def test_the_owner_can_open_their_ticket(self):
        self.assertEqual(self.fetch_as(self.owner).pk, self.ticket.pk)

    def test_a_stranger_cannot_open_it(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            self.fetch_as(self.stranger)

    def test_the_filter_is_applied_before_the_fetch_not_after(self):
        """The defect was ordering, not absence.

        `filters["user"] = user` was assigned after `get_object_or_404` had
        already run, so it never reached a query.
        """
        source = Path("weapi/django_rest/views/support_and_tickets.py").read_text()
        body = source.split("def get_object(self):")[1].split("\n    def ")[0]

        assign = body.index('filters["user"] = user')
        fetch = body.index("get_object_or_404(")
        self.assertLess(
            assign, fetch, "the ownership filter is still set after the fetch"
        )
