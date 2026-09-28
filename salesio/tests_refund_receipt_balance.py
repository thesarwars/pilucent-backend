"""Does a REFUND_RECEIPT still write a journal entry that does not balance?

Production holds 19 unbalanced REFUND_RECEIPT entries out of 54, and the most
recent bad entry of ANY kind -- 2026-08-07 -- is one of them. `236e1d2b`
("refunds: cost of sales was relieved without the inventory leg") landed the
morning after, so the cost half of that story is meant to be closed. Nobody had
proved it by building a refund and summing its legs, and "no new bad entries
since" is 20 documents across nine writers.

So this builds refund receipts and sums their legs. The untaxed cases fire a
recurring REFUND_RECEIPT template through `generate_refund_receipt_from_template`
-- the path that wrote the production case, journal 2766 being a nightly
recurring refund. The taxed cases go through `PrivateWeSaleListSerializer`, the
manual screen's own path, which the generator itself defers to rather than
opening a second GL route (and which the generator cannot reach with tax on
today -- see the last test). Either way the entry is measured by summing
`JournalEntryConnector.debit` and `.credit` and comparing them.

`assert_entry_balances` and `_log_balance` only LOG, so neither can be leaned on
here: a test that trusted them would pass on an entry that is out by hundreds.

What the runs show, on a 100.00 refund of goods costing 80.00:

* a refund that relieves cost of sales BALANCES at 180.000/180.000 -- 236e1d2b
  holds up under an end-to-end posting, not just a mirrored guard;
* the production shape (a COGS account resolves, the product has no inventory
  account) posts neither cost leg and BALANCES at 100.000/100.000;
* a refund carrying EXCLUSIVE tax BALANCES at 190.000/190.000;
* a refund carrying INCLUSIVE tax DOES NOT: debit 190.000 against credit
  180.000, out by +10.000 -- the whole of the tax.

The inclusive case is not an edge: `tax_kind` is a document-level setting both
the refund screen and the recurring template offer, and every inclusive refund
posts short by about its own tax. `post_sale_document` computes the
inclusive-tax backout (`inclusive_tax_allocation`, sale_posting.py:978) and
hands it only to `_post_sale_line` (:983). `_post_refund_line` (:981, defined at
:634) takes no such argument, so :646 reverses the GROSS line value as revenue
while `_post_tax_legs` debits the tax again beside it. The same document entered
as a SALE comes out at 180.000/180.910 -- a tenth of the error, from a different
and smaller defect.

Diagnosis only. Nothing here proposes the fix.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.db.models import F
from django.test import TestCase

from accounts.models import ChartOfAccount, User

from agencyio.models import Agency, AgencyTax, AgencyTaxSet

from companyio.models import Company, CompanyUser

from customerio.models import Customer

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import Purchase, PurchaseItem

from supplierio.models import Supplier


REFUND_DATE = date(2026, 8, 12)


class _Request:
    """The two attributes the sales serializer reads off a request."""

    def __init__(self, user):
        self.user = user

    def get_host(self):
        return "localhost:8000"


class RefundReceiptBalanceTests(TestCase):
    """Build a refund receipt, post it, and sum its legs.

    The fixture is an ordinary inventory item on a seeded chart: income,
    inventory asset and a cost lot, so a refund of it has something to put back
    and a cost to relieve. That is the shape the 2026-08-07 production entry
    had.
    """

    @classmethod
    def setUpTestData(cls):
        # The chart taxonomy has to exist before a company can be seeded from
        # it; without this a new company gets no control accounts at all.
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(name="Refund Co", kind="ECOMMERCE")
        self.user = User.objects.create(email="refund@example.com", name="R")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="Dana", display_name="Northgate"
        )

        # Seeded by system_key, not title -- a title lookup would silently miss
        # on any chart whose accounts have been renamed.
        self.income = self._seeded("SALES_OF_PRODUCT_INCOME")
        self.inventory = self._seeded("INVENTORY_ASSET")
        self.cogs = self._seeded("COGS")
        self.sales_tax_payable = self._seeded("SALES_TAX_PAYABLE")
        self.bank = self._seeded("UNDEPOSITED_FUNDS")

        self.product = Product.objects.create(
            company=self.company, title="Widget", sku="W-1", quantity=0,
            date=REFUND_DATE, kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE, sale_price=Decimal("50.00"),
            income_account=self.income, asset_account=self.inventory,
            cogs_account=self.cogs,
        )

    # -- fixtures ----------------------------------------------------------

    def _seeded(self, system_key):
        account = ChartOfAccount.objects.filter(
            company=self.company, system_key=system_key
        ).first()
        self.assertIsNotNone(account, f"company was seeded without {system_key}")
        return account

    def _lot(self, quantity, price):
        """A published purchase lot, so the refund finds a cost to put back."""
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S"
        )
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN, date=date(2026, 1, 1),
        )
        item = PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=quantity,
            opening_quantity=quantity, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED,
        )
        # On-hand has to reflect the lot, or the FIFO walk on the sale side
        # drives Product.quantity negative and the PositiveIntegerField
        # rejects it.
        Product.objects.filter(pk=self.product.pk).update(
            quantity=F("quantity") + quantity
        )
        self.product.refresh_from_db()
        return item

    def _tax(self, rate):
        agency = Agency.objects.create(
            company=self.company, title="State", status="ACTIVE"
        )
        tax = AgencyTax.objects.create(company=self.company, title="ST")
        AgencyTaxSet.objects.create(
            taxes=tax, agency=agency, rate=Decimal(str(rate)),
            sales_tax_account=self.sales_tax_payable,
        )
        return tax

    def _fire(self, *, tax=None, tax_kind="NO_TAX", quantity="2", rate="50"):
        """Fire a REFUND_RECEIPT template and return the Sale it produced."""
        from recurringio.models import RecurringTemplate, RecurringTemplateLine
        from recurringio.services.generation import generate_from_template

        template = RecurringTemplate.objects.create(
            name="Monthly refund", txn_type="REFUND_RECEIPT",
            template_type="SCHEDULED", company=self.company,
            customer=self.customer, payment_account=self.bank,
            tax_kind=tax_kind, memo="Refund for the cancelled plan",
            frequency="MONTHLY", interval_count=1, start_date=REFUND_DATE,
            end_type="NONE", next_run_date=REFUND_DATE,
        )
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="ITEM",
            product=self.product, quantity=Decimal(quantity),
            rate=Decimal(rate),
            amount=Decimal(quantity) * Decimal(rate),
            tax=tax, position=0,
        )
        return generate_from_template(
            template, self.user, self.company, transaction_date=REFUND_DATE
        )

    def _refund_via_screen(self, *, tax=None, tax_kind="NO_TAX", quantity=2,
                           rate="50", total="100.000", total_tax="0",
                           deposit="100.000", due_total="0", kind="REFUND"):
        """A refund receipt entered on the manual screen.

        The taxed cases cannot go through the recurring generator: it builds
        `total_tax` by raw Decimal division (`line_tax_amount`), so a 100.0000
        line at a 10.000% rate yields "10.0000000" and the serializer rejects
        it for having more than three decimal places -- a recurring refund
        carrying any tax code cannot fire at all today. That is a separate
        defect and is reported separately; it must not stop the ledger question
        being answered, so the taxed refunds are entered the way the screen
        enters them, through the same serializer the generator itself defers
        to.
        """
        from common.tenant import set_current_company_id
        from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer

        line_total = str(Decimal(str(rate)) * quantity)
        # Money leaves through the PAYABLE account on a refund and arrives
        # through the RECEIVABLE one on a receipt -- the poster picks the leg's
        # side off the direction, so the two documents differ by this alone.
        settlement = (
            "payable_charter_account_uid" if kind == "REFUND"
            else "receivable_charter_account_uid"
        )
        payload = {
            "date": REFUND_DATE.isoformat(),
            "kind": kind,
            "status": "OPEN",
            "is_sale_receipt": True,
            "customer_uid": str(self.customer.uid),
            "currency_kind": "USD",
            "currency_rate": "1",
            settlement: str(self.bank.uid),
            "tax_kind": tax_kind,
            "total": total,
            "total_tax": total_tax,
            "deposit": deposit,
            "due_total": due_total,
            "discount_kind": "PERCENTAGE",
            "discount": "0",
            "shipping_fee": "0",
            "sales_items": [
                {
                    "product_uid": str(self.product.uid),
                    "quantity": str(quantity),
                    "sale_price": str(rate),
                    "total": line_total,
                    "is_item_tax": bool(tax),
                    "tax_uid": str(tax.uid) if tax else "",
                }
            ],
            "email": {"customer_email": "c@x.test", "cc_emails": "",
                      "bcc_emails": ""},
        }

        set_current_company_id(self.company.id)
        try:
            serializer = PrivateWeSaleListSerializer(
                data=payload, context={"request": _Request(self.user)}
            )
            serializer.is_valid(raise_exception=True)
            return serializer.save()
        finally:
            set_current_company_id(None)

    # -- measurement -------------------------------------------------------

    def _entry(self, sale, kind=JournalEntryKindChoices.REFUND_RECEIPT):
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry, "the document posted no journal entry at all")
        self.assertEqual(entry.kind, kind)
        return entry

    def _totals(self, sale, label,
                kind=JournalEntryKindChoices.REFUND_RECEIPT):
        """(debit, credit) summed off the connectors themselves.

        Not `assert_entry_balances` and not `_log_balance` -- both only write a
        log line, so a test built on either passes on an entry that is out.
        """
        entry = self._entry(sale, kind)
        rows = list(entry.journalentryconnector_set.select_related("account"))
        debit = sum(Decimal(row.debit or 0) for row in rows)
        credit = sum(Decimal(row.credit or 0) for row in rows)

        print(f"\n  RESULT {label}")
        print(f"         sale total={sale.total} tax={sale.total_tax} "
              f"deposit={sale.deposit} due_total={sale.due_total} "
              f"tax_kind={sale.tax_kind}")
        for row in rows:
            side = "debit " if row.debit else "credit"
            amount = row.debit if row.debit else row.credit
            print(f"         {row.account.title:<32} {side} {amount}")
        print(f"         -> debit {debit} vs credit {credit} "
              f"(out by {debit - credit})")
        return debit, credit

    # -- the cases ---------------------------------------------------------

    def test_a_refund_that_relieves_cost_of_sales_balances(self):
        """The shape 236e1d2b was written for, driven end to end.

        Journal 2766 credited cost of sales with no inventory debit. Both legs
        now resolve, so both post: revenue reversal 100 debit against the bank
        100 credit, with the cost pair netting to zero on top.
        """
        self._lot(10, "40.00")

        sale = self._fire()
        debit, credit = self._totals(sale, "refund relieving cost of sales")

        self.assertEqual(debit, credit)

    def test_the_production_shape_posts_neither_cost_leg_and_balances(self):
        """A product with no inventory account, whose COGS still resolves.

        `resolve_cogs_account` falls back to the company's COGS control
        account, so before the fix the cost half posted alone. With the pairing
        guard neither posts and the entry closes on revenue against the bank.
        """
        self.product.asset_account = None
        self.product.cogs_account = None
        self.product.save(update_fields=["asset_account", "cogs_account"])
        self._lot(10, "40.00")

        sale = self._fire()
        debit, credit = self._totals(sale, "refund with no inventory account")

        self.assertEqual(debit, credit)

    def test_a_refund_carrying_exclusive_tax_balances(self):
        """Tax added on top of the price.

        100.00 of goods at 10%: the customer gets 110.00 back, so the bank pays
        110.00 while revenue is reversed by 100.00 and the liability debited
        10.00. Nothing is double counted and the entry closes.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(
            tax=self._tax("10.000"), tax_kind="EXCLUSIVE",
            total="100.000", total_tax="10.000", deposit="110.000",
        )
        debit, credit = self._totals(sale, "refund carrying EXCLUSIVE tax")

        self.assertEqual(debit, credit)

    def test_a_refund_carrying_inclusive_tax_balances(self):
        """WAS: tax inside the price, revenue reversed GROSS and taxed again.

        100.00 refunded at 10% inclusive is 90.91 of revenue plus 9.09 of tax,
        and the bank pays out 100.00 -- the header says exactly that
        (total 100.000, total_tax 9.091, deposit 100.000).

        `post_sale_document` works out the inclusive backout for every line
        (`inclusive_tax_allocation`, sale_posting.py:978) and then hands it
        only to `_post_sale_line` (:983). `_post_refund_line` (:981) takes no
        such argument, so the whole gross 100.000 is debited back to revenue --
        and `_post_tax_legs` debits the tax beside it, which on an inclusive
        document is already inside that 100.000.

        Every inclusive refund is therefore short by about its own tax. The
        residual leg cannot rescue it either: the legs already exceed the
        declared tax, and `_post_unattributed_tax` refuses to post a negative
        one.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(
            tax=self._tax("10.000"), tax_kind="INCLUSIVE",
            total="100.000", total_tax="9.091", deposit="100.000",
        )
        debit, credit = self._totals(sale, "refund carrying INCLUSIVE tax")

        # It was intended, and the figures are updated. `post_sale_document`
        # now hands the inclusive backout to BOTH line posters, so revenue comes
        # back net of the tax sitting inside the price and the tax leg is the
        # only thing unwinding the liability.
        self.assertEqual(
            debit, credit,
            "an inclusive refund must not remove its tax twice",
        )
        # 90.91 revenue + 9.09 tax + 80.00 inventory back in = 180.00,
        # against 100.00 out of the bank + 80.00 off cost of sales.
        self.assertEqual(debit, Decimal("180.000"))
        self.assertEqual(debit - credit, Decimal("0.000"))

    def test_the_inclusive_refund_reverses_revenue_net(self):
        """The single leg the imbalance came from.

        Revenue must come back net of the tax that sits inside the price --
        90.909 here. It is debited for the full 100.000, which is the missing
        backout on its own, independent of how the tax leg is priced.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(
            tax=self._tax("10.000"), tax_kind="INCLUSIVE",
            total="100.000", total_tax="9.091", deposit="100.000",
        )
        entry = self._entry(sale)
        revenue = entry.journalentryconnector_set.filter(
            account=self.income
        ).first()

        print(f"\n  RESULT inclusive refund revenue leg: debit {revenue.debit} "
              f"(gross 100.000; net of the document's own tax would be 90.909)")
        self.assertEqual(
            Decimal(revenue.debit), Decimal("90.910"),
            "revenue must come back NET of the tax inside the price",
        )

    def test_the_imbalance_is_not_an_artefact_of_the_headers_tax_figure(self):
        """Same document, with the header's tax stated the other way.

        9.091 is the tax truly inside a 100.00 inclusive price; a client that
        computes it exclusively sends 10.000 instead. Neither figure rescues
        the entry, because the missing leg is on the revenue side: the shortfall
        stays 10.000 while `_post_unattributed_tax` goes quiet, which is the
        worse of the two -- the same imbalance with no log line naming it.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(
            tax=self._tax("10.000"), tax_kind="INCLUSIVE",
            total="100.000", total_tax="10.000", deposit="100.000",
        )
        debit, credit = self._totals(
            sale, "INCLUSIVE refund whose header states tax exclusively"
        )

        self.assertEqual(
            debit - credit, Decimal("0.000"),
            "a header stating its inclusive tax exclusively must still balance",
        )

    def test_the_same_document_as_a_sale_is_not_short_the_whole_tax(self):
        """The contrast that places the defect on the refund path.

        Identical header, identical line, `kind=SALE` instead of REFUND. The
        sale path receives the inclusive backout, so revenue is recognised net
        at 90.909 and the entry lands within a rounding step of balancing --
        out by 0.909, which is the tax leg being priced off the GROSS line
        total (`_post_tax_legs`: `item_total * rate / 100` on a tax-inclusive
        item_total). That second defect is real and shared by both directions;
        it is an order of magnitude smaller than the 10.000 the refund is out
        by, and it is not what this report is about.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(
            kind="SALE", tax=self._tax("10.000"), tax_kind="INCLUSIVE",
            total="100.000", total_tax="9.091", deposit="100.000",
        )
        debit, credit = self._totals(
            sale, "the same INCLUSIVE document entered as a SALE",
            kind=JournalEntryKindChoices.SALE_RECEPT,
        )

        self.assertLess(abs(debit - credit), Decimal("10.000"))

    def test_a_partly_settled_refund_debits_the_receivable(self):
        """A second way the same document can come out unbalanced.

        `post_sale_document` debits A/R for `due_total` whatever the direction
        (sale_posting.py:1002-1016) -- right for an invoice, backwards for a
        refund, where the customer is owed rather than owing. Refunds are
        settled in full by every first-party builder (the recurring generator
        sends `deposit = total`, and the screen's own default does the same),
        so `due_total` is 0 and the leg never appears. It is client-supplied,
        though, and one that arrives non-zero puts the entry out by twice it.

        Recorded rather than asserted as a live production fault: nothing in
        this repo builds this document today.
        """
        self._lot(10, "40.00")

        sale = self._refund_via_screen(deposit="40.000", due_total="60.000")
        debit, credit = self._totals(sale, "refund settled only in part")

        self.assertEqual(debit - credit, Decimal("120.000"))

    def test_a_taxed_recurring_refund_cannot_fire_at_all(self):
        """Why the taxed cases above are entered on the screen, not fired.

        `line_tax_amount` divides raw Decimals, so a 100.000 line at a 10.000%
        rate produces "10.000000" -- six decimal places against the
        serializer's three, and the firing dies with a ValidationError before
        anything posts. Every recurring REFUND_RECEIPT template carrying a tax
        code is in that state, so this is a generation outage rather than a
        ledger fault: no entry, balanced or otherwise.
        """
        from rest_framework.exceptions import ValidationError

        self._lot(10, "40.00")

        with self.assertRaises(ValidationError) as caught:
            self._fire(tax=self._tax("10.000"), tax_kind="EXCLUSIVE")

        print(f"\n  RESULT firing a taxed recurring refund: {caught.exception}")
        self.assertIn("total_tax", str(caught.exception))
        self.assertFalse(JournalEntry.objects.exists())
