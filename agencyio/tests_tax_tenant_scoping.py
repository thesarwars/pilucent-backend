"""A tax rate could be borrowed from another company, and the tax booked to theirs.

Eight lookups resolved `AgencyTax` by a `uid` taken straight from the request
payload, with no company filter: on sales, purchases, credit notes and the
sale-posting amend path.

This is worse than a disclosure. `AgencyTax` is not a number -- it walks to
accounts:

    for tax_group in item_tax.tax_groups.all():
        item_payable_account = tax_group.sales_tax_account

So submitting another tenant's `tax_uid` did not merely apply their rate to your
document; it posted your tax liability into **their** Sales Tax Payable account.
Their liability grows, their filing is wrong, and nothing on either side records
why.

`agencyio_agencytax` carries no row-level security policy, so unlike
ChartOfAccount, Product, Sale and Purchase there was no database backstop
either. The application filter was the only control, and it was absent.

Found by the sweep after `COA_FIX_PLAN_V3.md` P0.1. Seven sites came from that
sweep; the eighth -- `sale_posting.py` -- uses `.filter().first()` rather than
`get_object_or_404` and was missed by it, which is worth remembering about the
sweep's shape rather than its findings.
"""

import re
from pathlib import Path

from django.test import TestCase

from agencyio.models import AgencyTax

from companyio.models import Company


class TaxScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Acme Books")
        cls.company_b = Company.objects.create(name="Beta Ledger")
        cls.tax_a = AgencyTax.objects.create(
            company=cls.company_a, title="A State Tax", total_rate=5
        )
        cls.tax_b = AgencyTax.objects.create(
            company=cls.company_b, title="B State Tax", total_rate=9
        )

    def test_a_scoped_lookup_refuses_the_other_companys_tax(self):
        self.assertEqual(
            AgencyTax.objects.filter(
                uid=self.tax_b.uid, company=self.company_a
            ).count(),
            0,
        )
        self.assertEqual(
            AgencyTax.objects.filter(
                uid=self.tax_a.uid, company=self.company_a
            ).count(),
            1,
        )

    def test_the_model_carries_a_company(self):
        """If it did not, every call site below would need a different fix."""
        self.assertIn("company", {f.name for f in AgencyTax._meta.get_fields()})

    def test_agencytax_has_no_row_level_security_backstop(self):
        """Why the application filter is the only control.

        ChartOfAccount, Product, Sale and Purchase are RLS-protected, so an
        unscoped lookup on those is a defence-in-depth gap rather than a live
        leak. This table is not in that set, which is what made these eight
        sites exploitable and the others not.
        """
        from django.db import connection

        if connection.vendor != "postgresql":
            self.skipTest("RLS is a Postgres feature; sqlite test run")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = %s",
                [AgencyTax._meta.db_table],
            )
            row = cursor.fetchone()

        self.assertTrue(
            row is None or row[0] is False,
            "AgencyTax gained RLS -- revisit whether these filters are still "
            "the only control, and update this test's premise",
        )


class CallSiteTests(TestCase):
    """Every `AgencyTax` lookup must name a company, in every module."""

    FILES = [
        "weapi/django_rest/serializers/creditnotes.py",
        "weapi/django_rest/serializers/purchases.py",
        "weapi/django_rest/serializers/sales.py",
        "weapi/django_rest/serializers/agencies.py",
        "weapi/django_rest/views/agencies.py",
        "weapi/django_rest/helpers/sale_posting.py",
    ]

    def lookups(self):
        """Every `AgencyTax.objects.filter(...)` call, with its full argument list."""
        found = []
        for name in self.FILES:
            source = Path(name).read_text()
            for match in re.finditer(r"AgencyTax\.objects\.filter\(", source):
                i, depth = match.end(), 1
                while i < len(source) and depth:
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                    i += 1
                found.append(
                    (name, source[: match.start()].count("\n") + 1,
                     source[match.start(): i])
                )
        return found

    def test_every_lookup_is_scoped(self):
        lookups = self.lookups()
        self.assertGreaterEqual(len(lookups), 8, "the sweep lost call sites")

        for name, line, call in lookups:
            with self.subTest(site=f"{name}:{line}"):
                self.assertTrue(
                    "company" in call or "agency" in call,
                    f"{name}:{line} resolves a tax with no tenant filter",
                )

    def test_the_posting_engine_scopes_through_the_sale(self):
        """The one site the `get_object_or_404` sweep did not match."""
        source = Path("weapi/django_rest/helpers/sale_posting.py").read_text()

        self.assertIn("uid=tax_uid, company=item.sale.company", source)
        self.assertNotIn("AgencyTax.objects.filter(uid=tax_uid).first()", source)
