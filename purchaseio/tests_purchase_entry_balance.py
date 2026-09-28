"""Does a PURCHASE still write a journal entry whose debits differ from its credits?

Production holds 4 unbalanced PURCHASE entries out of 137, the newest dated
2026-04-22 -- the oldest "most recent" of any document kind, which reads like a
kind that was fixed long ago. The low rate is real and so is the age, but
neither is evidence about the code: they are evidence about *what shapes of bill
this tenant happens to enter*. A bill with one product line, tax, and nothing
else balances today and has for months. That is the shape almost every bill is.

Three shapes a client can still submit do not balance, and all three are reached
through the live endpoint (`PrivateWePurchaseListSerializer.create`,
`weapi/django_rest/serializers/purchases.py:265`):

1. **A discount.** The cost legs are the line totals; the funding leg is
   `due_total`. `Purchase.discount` is journaled nowhere, so the entry comes out
   long on the debit side by exactly the discount. Purchase discounts belong on
   a contra-expense / purchase-discount account, which is what the sale poster
   does for its own discount (`sale_posting.py:1023-1049`).

2. **A shipping charge.** Same asymmetry the other way -- `shipping_fee` widens
   `due_total` but is debited to no freight account, so the entry is long on the
   credit side by the shipping charge.

3. **A non-stock line** (SERVICE / PROJECT / EVENT product, or one flagged
   `is_non_stock`). The `tracks_stock()` guard added at
   `purchases.py:506-519` correctly stops a service from being treated as
   inventory -- but it `continue`s past the *whole* loop body, and the ledger
   leg is written at the bottom of that body (`purchases.py:569-577`). The cost is
   debited to nothing at all. A/P is still credited in full, and the entry is
   short by the entire line. This is a leg dropped silently: the log line says
   "recorded without touching inventory", not "recorded without a debit".

The header/`due_total` relationship assumed here is the codebase's own, stated
in `sale_posting.recalculate_sale_totals` and implemented by every programmatic
caller (`recurringio/services/generation.py:_build_bill_group`,
`datamigrationio/.../bill_importer.py:104`):

    total     = sum of the live lines, ex-tax
    due_total = total + tax - discount + shipping - deposit

Nothing below reads a log line to decide anything. `assert_entry_balances` only
LOGS -- see its own docstring -- so every assertion sums
`JournalEntryConnector.debit` against `.credit` for the entry that was really
written.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.models import ChartOfAccount, User

from common.tenant import set_current_company_id

from companyio.models import Company, CompanyUser

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from supplierio.choices import SupplierStatusChoices
from supplierio.models import Supplier


OMIT = object()
"""Sentinel: leave this field off the request body entirely."""


class _Request:
    """The one attribute the purchase serializer reads off the request."""

    def __init__(self, user):
        self.user = user


class PurchaseBalanceCase(TestCase):
    """Company, chart, supplier, product -- and the balance measurement."""

    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        # A clean company per scenario, so the identifiers have to be unique
        # per call.
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Purchase Balance Co {self._nth}", kind="ECOMMERCE"
        )
        self.user = User.objects.create(
            email=f"pur{self._nth}@example.com", name="P"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S Ltd",
            status=SupplierStatusChoices.ACTIVE,
        )
        self.payable = self._control("AP")
        self.inventory = self._control("INVENTORY_ASSET")
        self.tax_payable = self._control("SALES_TAX_PAYABLE")
        self.bank = ChartOfAccount.objects.filter(
            company=self.company, title="Checking Account"
        ).first()
        self.product = self._product("Widget", "W1")

    # --- fixtures ---------------------------------------------------------

    def _control(self, system_key):
        """Control accounts are seeded on Company creation.

        Looked up by `system_key` alone: `ChartOfAccount.status` defaults to
        DRAFT, so a queryset narrowed to ACTIVE is not a safe way to find these.
        """
        return ChartOfAccount.objects.filter(
            company=self.company, system_key=system_key
        ).first()

    def _product(self, title, sku, kind=ProductKindChoices.PRODUCT, **extra):
        return Product.objects.create(
            company=self.company, title=title, sku=sku, quantity=0,
            date="2026-01-01", kind=kind, status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("150.00"), asset_account=self.inventory, **extra
        )

    # --- driving the live endpoint ---------------------------------------

    def bill(self, lines=None, **extra):
        """A posted bill, built by the real `create()` the API calls."""
        from weapi.django_rest.serializers.purchases import (
            PrivateWePurchaseListSerializer,
        )

        lines = lines if lines is not None else [self.line(self.product)]
        subtotal = sum(Decimal(str(line["total"])) for line in lines)

        payload = {
            "supplier_uid": str(self.supplier.uid),
            "currency_kind": "USD",
            "currency_rate": "1",
            "is_bill": True,
            "is_cheque": False,
            "status": "OPEN",
            "tax_kind": "NO_TAX",
            "date": "2026-05-01",
            "bill_date": "2026-05-01",
            "due_date": "2026-06-01",
            "email": {"customer_email": "s@x.com", "cc_emails": [],
                      "bcc_emails": []},
            # `total_tax` has to be on the wire even at zero: the model default
            # is a float, and the PDF template does `total - total_tax`, which
            # raises `Decimal - float` and rolls the whole create back.
            "total": str(subtotal),
            "due_total": str(subtotal),
            "total_tax": "0.000",
            "deposit": "0.000",
            "discount": "0.000",
            "shipping_fee": "0.000",
            "purchase_items": lines,
        }
        payload.update(extra)
        # `OMIT` takes a field back off the wire, which is not the same as
        # sending it null -- an omitted field never reaches `validated_data`.
        for field in [k for k, v in payload.items() if v is OMIT]:
            payload.pop(field)

        set_current_company_id(self.company.id)
        try:
            serializer = PrivateWePurchaseListSerializer(
                data=payload, context={"request": _Request(self.user)}
            )
            serializer.is_valid(raise_exception=True)
            return serializer.save()
        finally:
            set_current_company_id(None)

    def line(self, product, quantity=10, price="100.000"):
        return {
            "product_uid": str(product.uid),
            "quantity": quantity,
            "purchase_price": price,
            "total": str(Decimal(price) * quantity),
            "section": "",
            "note": "",
            "description": product.title,
        }

    def expense_line(self, account, total="250.000"):
        return {
            "charter_account_uid": str(account.uid),
            "total": total,
            "section": "",
            "note": "",
            "description": account.title,
        }

    # --- the measurement --------------------------------------------------

    def rows(self, purchase):
        entries = JournalEntry.objects.filter(purchase=purchase)
        return list(
            JournalEntryConnector.objects.filter(journal__in=entries)
            .select_related("account")
        )

    def totals(self, purchase):
        """(debit, credit) summed off the connectors, not read off a log line."""
        rows = self.rows(purchase)
        debit = sum(Decimal(str(r.debit or 0)) for r in rows)
        credit = sum(Decimal(str(r.credit or 0)) for r in rows)
        return debit, credit

    def report(self, label, purchase):
        debit, credit = self.totals(purchase)
        print(f"\n  RESULT {label}")
        for row in self.rows(purchase):
            title = row.account.title if row.account else "(no account)"
            print(f"         {title:<28} D {row.debit:>11}  C {row.credit:>11}")
        print(f"         {'':<28} {'-' * 27}")
        print(f"         {'TOTAL':<28} D {debit:>11}  C {credit:>11}"
              f"    D-C = {debit - credit}")
        return debit, credit

    def assert_balances(self, purchase, label):
        debit, credit = self.report(label, purchase)
        self.assertEqual(
            debit, credit, f"{label}: entry is out by {debit - credit}"
        )

    def assert_out_by(self, purchase, expected, label):
        debit, credit = self.report(label, purchase)
        self.assertEqual(
            debit - credit, Decimal(str(expected)),
            f"{label}: expected the entry to be out by {expected}",
        )


class BillShapesThatBalanceTests(PurchaseBalanceCase):
    """The shapes production actually contains, kept as a regression guard.

    These are why PURCHASE reads as "fixed long ago": the ordinary bill has
    balanced for a long time and still does.
    """

    def test_the_journal_entry_is_written_under_the_purchase_kind(self):
        purchase = self.bill()

        entry = JournalEntry.objects.get(purchase=purchase)
        self.assertEqual(entry.kind, JournalEntryKindChoices.PURCHASE)

    def test_a_plain_product_bill_balances(self):
        self.assert_balances(self.bill(), "bill: 10 x 100.00, no tax")

    def test_a_bill_with_exclusive_tax_balances(self):
        """Input tax debits Sales Tax Payable; A/P carries the gross."""
        purchase = self.bill(
            tax_kind="EXCLUSIVE", total_tax="100.000", due_total="1100.000"
        )
        self.assert_balances(purchase, "bill: 1000.00 + 100.00 tax")

    def test_a_bill_part_settled_by_a_deposit_balances(self):
        """The deposit credits the account it was paid from, A/P the remainder."""
        purchase = self.bill(
            deposit="400.000", due_total="600.000",
            charter_account_uid=str(self.bank.uid),
        )
        self.assert_balances(purchase, "bill: 1000.00, deposit 400.00 from bank")

    def test_an_expense_category_line_balances(self):
        """A category (non-product) line debits the account the client chose."""
        freight = ChartOfAccount.objects.filter(
            company=self.company, title="Freight In (Inbound Shipping)"
        ).first()
        purchase = self.bill(
            lines=[],
            custom_expense_items=[self.expense_line(freight, "250.000")],
            total="250.000", due_total="250.000",
        )
        self.assert_balances(purchase, "bill: one 250.00 category line")


class BillShapesThatDoNotBalanceTests(PurchaseBalanceCase):
    """Three shapes the live endpoint still posts out of balance today."""

    def test_a_discount_is_journaled_to_no_account(self):
        """`Purchase.discount` never reaches a leg.

        The cost side is the line totals and the funding side is `due_total`,
        which the discount has already reduced. Nothing debits a purchase
        discount / contra-expense account, so the entry is long on debits by
        exactly the discount.
        """
        purchase = self.bill(
            discount_kind="FLAT", discount="100.000", due_total="900.000"
        )
        self.assert_out_by(purchase, "100.000", "bill: 1000.00 less 100.00 discount")

    def test_a_percentage_discount_is_journaled_to_no_account(self):
        purchase = self.bill(
            discount_kind="PERCENTAGE", discount="10.000", due_total="900.000"
        )
        self.assert_out_by(
            purchase, "100.000", "bill: 1000.00 less 10% discount"
        )

    def test_a_shipping_charge_is_journaled_to_no_account(self):
        """`Purchase.shipping_fee` widens A/P and debits no freight account."""
        purchase = self.bill(shipping_fee="50.000", due_total="1050.000")
        self.assert_out_by(purchase, "-50.000", "bill: 1000.00 plus 50.00 shipping")

    def test_a_service_line_still_posts_its_cost(self):
        """`tracks_stock()` must skip the inventory effect, not the leg.

        Was: out by -1500.000. `purchases.py:519` `continue`d past the rest of
        the loop body, and the journal leg is written at the bottom of that body
        -- so A/P was credited for the full bill and nothing was debited.

        Now the non-stock branch posts the same debit to `resolve_cogs_account`
        instead of to Inventory Asset. The leg to drop was Inventory Asset, not
        the cost. Fixed alongside this assertion; see the module docstring.
        """
        service = self._product("Consulting", "S1", kind=ProductKindChoices.SERVICE)
        purchase = self.bill(lines=[self.line(service, 10, "150.000")])
        self.assert_balances(purchase, "bill: 10 x 150.00 service line")

    def test_a_non_stock_product_still_posts_its_cost(self):
        """Same hole reached by the flag rather than by the item kind.

        Was: out by -1000.000.
        """
        non_stock = self._product("Drop Ship", "D1", is_non_stock=True)
        purchase = self.bill(lines=[self.line(non_stock, 4, "250.000")])
        self.assert_balances(purchase, "bill: 4 x 250.00 non-stock line")

    def test_a_mixed_bill_posts_both_lines(self):
        """The stocked line and the service line beside it both post.

        Was: out by -300.000 -- exactly the service line, with the stocked line
        posting correctly beside it. That asymmetry is what identified the
        `continue` as the cause.
        """
        service = self._product("Install", "S2", kind=ProductKindChoices.SERVICE)
        purchase = self.bill(lines=[
            self.line(self.product, 10, "100.000"),
            self.line(service, 1, "300.000"),
        ])
        self.assert_balances(purchase, "bill: 1000.00 stock + 300.00 service")


class AdjacentBreakageOnTheSameWritePathTests(PurchaseBalanceCase):
    """Two ways the same `create()` fails outright rather than silently.

    Neither writes a bad entry -- `create` is `@transaction.atomic`, so the
    whole bill rolls back -- but both are 500s on a payload the serializer
    accepts, and both sit directly beside the balance bugs above. Recorded here
    because whoever fixes the legs is editing these same lines.
    """

    def test_a_deposit_with_no_funding_account_raises(self):
        """`charter_account_uid` is optional; the deposit branch dereferences it.

        `purchases.py:657-658` reads `bank_cash_charter_account.kind` with no
        guard,
        and `bank_cash_charter_account` is whatever `charter_account_uid`
        resolved to -- None when the client omitted it.
        """
        with self.assertRaises(AttributeError):
            self.bill(deposit="400.000", due_total="600.000")

    def test_omitting_total_tax_rolls_the_whole_bill_back(self):
        """`Purchase.total_tax`'s model default is a float, not a Decimal.

        The PDF template computes `purchase.total - purchase.total_tax`
        (`templates/emails/purchases/purchase_pdf_template.html:205`) on the
        in-memory instance, where an omitted `total_tax` is still the float
        `0.00`. `Decimal - float` raises, and because the email block sits
        inside the atomic `create`, the posted bill and its journal entry are
        rolled back after the ledger work has already been done.
        """
        with self.assertRaises(TypeError):
            self.bill(total_tax=OMIT)

        self.assertFalse(JournalEntry.objects.filter(company=self.company).exists())


class TheServiceCostLandsOnACostAccountTests(PurchaseBalanceCase):
    """Where the service line's money went, not merely that the totals agree.

    Worth pinning separately from the arithmetic, and in both directions. The
    original defect was that A/P was the entry's ONLY leg -- 1,500.00 credited
    and nothing debited. Balanced totals alone would not catch a fix that put
    the debit somewhere wrong, and "somewhere wrong" has a specific candidate
    here: **Inventory Asset**, which is what the pre-`d67d4b7e` code did and
    what the `tracks_stock()` guard exists to prevent. A service must not
    capitalise into inventory.

    So this asserts three things: two legs, the cost on a cost account, and
    that cost account is not the inventory one.
    """

    def test_a_service_bill_debits_a_cost_account_and_credits_payable(self):
        service = self._product("Consulting", "S3", kind=ProductKindChoices.SERVICE)
        purchase = self.bill(lines=[self.line(service, 10, "150.000")])

        rows = self.rows(purchase)
        self.assertEqual(len(rows), 2, "the cost leg is missing again")

        payable = [r for r in rows if r.account == self.payable]
        cost = [r for r in rows if r.account != self.payable]
        self.assertEqual(len(payable), 1)
        self.assertEqual(len(cost), 1)

        self.assertEqual(Decimal(str(payable[0].credit)), Decimal("1500.000"))
        self.assertEqual(Decimal(str(payable[0].debit)), Decimal("0.000"))
        self.assertEqual(Decimal(str(cost[0].debit)), Decimal("1500.000"))
        self.assertEqual(Decimal(str(cost[0].credit)), Decimal("0.000"))

    def test_the_service_cost_does_not_capitalise_into_inventory(self):
        """The half of `d67d4b7e`'s intent that must survive the fix."""
        service = self._product("Consulting", "S4", kind=ProductKindChoices.SERVICE)
        purchase = self.bill(lines=[self.line(service, 10, "150.000")])

        accounts = {r.account for r in self.rows(purchase)}
        self.assertNotIn(
            self.inventory, accounts,
            "a service line capitalised into Inventory Asset -- the inventory "
            "reports filter on is_inventory and would never show it",
        )
