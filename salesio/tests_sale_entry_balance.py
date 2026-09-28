"""Does a SALE still write a journal entry whose debits differ from its credits?

Production holds 144 unbalanced SALE entries out of 807, the most recent dated
2026-08-06 -- the day the unified poster landed. Two samples, both company 114,
both three legs and both out by -550.00: a COGS/inventory pair that balances
internally, plus a `Sales of Product Income` credit with no debit anywhere.

The unified poster (`weapi/django_rest/helpers/sale_posting.py`) really did
close the audit finding it was written against: revenue is no longer a function
of what FIFO managed to consume, and an out-of-stock or service line now
balances. That is verified below and kept as a regression guard.

It did not close the document kind, because **SALE has a second writer**.
`MigrationInvoiceCreateService.create_invoice`
(`datamigrationio/django_rest/services/invoice_importer.py`) builds a
`Sale(is_invoice=True)` and a `JournalEntry(kind=SALE)` with its own inline
posting block, which `post_sale_document` never replaced. That block still
emits the income leg *inside* the FIFO loop -- audit finding 1, verbatim -- and
still journals neither the deposit, the discount nor the shipping charge --
audit finding 2, verbatim. It is not a dormant migration path: recurring
invoice generation fires through it nightly
(`recurringio/services/generation.py:generate_invoice_from_template`).

Nothing here reads a log line to decide. `assert_entry_balances` and
`_log_balance` only LOG, so every assertion sums `JournalEntryConnector.debit`
against `.credit` for the entry that was actually written.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.db.models import F
from django.test import TestCase

from accounts.models import ChartOfAccount, User

from common.tenant import set_current_company_id

from companyio.models import Company, CompanyUser

from customerio.models import Customer

from journalio.models import JournalEntry, JournalEntryConnector

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product, ProductAdditionalCost

from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import Purchase, PurchaseItem

from supplierio.models import Supplier


class _Request:
    """The one attribute the sale serializer reads off the request."""

    def __init__(self, user):
        self.user = user


class SaleBalanceCase(TestCase):
    """Company, chart, customer, product -- and the balance measurement."""

    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        # Re-invoked per scenario where a scenario needs a clean chart, so the
        # identifiers have to be unique per call.
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Balance Co {self._nth}", kind="ECOMMERCE"
        )
        self.user = User.objects.create(email=f"bal{self._nth}@example.com", name="B")
        CompanyUser.objects.create(user=self.user, company=self.company)
        self.customer = Customer.objects.create(
            company=self.company, first_name="C", display_name="C"
        )
        self.income = self._control("SALES_OF_PRODUCT_INCOME")
        self.asset = self._control("INVENTORY_ASSET")
        self.cogs = self._control("COGS")
        self.receivable = self._control("AR")
        self.product = self._product("Widget", "W1")

    # --- fixtures ---------------------------------------------------------

    def _control(self, system_key):
        """Control accounts are seeded on Company creation, and are DRAFT.

        Filtering these to ACTIVE finds nothing -- `ChartOfAccount.status`
        defaults to DRAFT -- so the lookup is by `system_key` alone.
        """
        return ChartOfAccount.objects.filter(
            company=self.company, system_key=system_key
        ).first()

    def _product(self, title, sku, kind=ProductKindChoices.PRODUCT, **extra):
        fields = {"income_account": self.income, "asset_account": self.asset}
        fields.update(extra)
        return Product.objects.create(
            company=self.company, title=title, sku=sku, quantity=0,
            date="2026-01-01", kind=kind, status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("100.00"), **fields,
        )

    def _layer(self, product, quantity, price):
        """One published purchase lot for the FIFO walk to consume."""
        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S"
        )
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN,
        )
        item = PurchaseItem.objects.create(
            purchase=purchase, product=product, quantity=quantity,
            opening_quantity=quantity, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED,
        )
        # On-hand has to reflect the lot or the FIFO walk drives
        # Product.quantity negative and the PositiveIntegerField rejects it --
        # and the in-memory instance has to be refreshed with it, because the
        # FIFO walk decrements whatever `product.quantity` says.
        Product.objects.filter(pk=product.pk).update(
            quantity=F("quantity") + quantity
        )
        product.refresh_from_db(fields=["quantity"])
        return item

    def _cost_account(self, product, account=None):
        """Cost of sales lives on a child row, not on the product."""
        ProductAdditionalCost.objects.create(
            product=product, amount=Decimal("0.00"),
            expense_account=account or self.cogs,
        )

    # --- the measurement --------------------------------------------------

    def totals(self, sale):
        """(debit, credit) summed off the connectors, not read off a log line."""
        rows = self.rows(sale)
        debit = sum(Decimal(str(r.debit or 0)) for r in rows)
        credit = sum(Decimal(str(r.credit or 0)) for r in rows)
        return debit, credit

    def rows(self, sale):
        entries = JournalEntry.objects.filter(sale=sale)
        return list(
            JournalEntryConnector.objects.filter(journal__in=entries)
            .select_related("account")
        )

    def report(self, label, sale):
        debit, credit = self.totals(sale)
        print(f"\n  RESULT {label}")
        for row in self.rows(sale):
            title = row.account.title if row.account else "(no account)"
            print(f"         {title:<32} D {row.debit:>11}  C {row.credit:>11}")
        print(f"         {'':<32} {'-' * 27}")
        print(f"         {'TOTAL':<32} D {debit:>11}  C {credit:>11}"
              f"    D-C = {debit - credit}")
        return debit, credit

    def assert_balances(self, sale, label):
        debit, credit = self.report(label, sale)
        self.assertEqual(
            debit, credit,
            f"{label}: entry is out by {debit - credit}",
        )

    def assert_out_by(self, sale, expected, label):
        debit, credit = self.report(label, sale)
        self.assertEqual(
            debit - credit, Decimal(str(expected)),
            f"{label}: expected the entry to be out by {expected}",
        )


class UnifiedPosterBalanceTests(SaleBalanceCase):
    """`post_sale_document`, reached through the real create() serializer.

    The engine that landed 2026-08-06. Its headline fix holds; four shapes a
    client can still submit today do not.
    """

    def sale(self, lines=None, **extra):
        from weapi.django_rest.serializers.sales import PrivateWeSaleListSerializer

        lines = lines if lines is not None else [
            {"product_uid": str(self.product.uid), "quantity": 1,
             "sale_price": "550.00", "total": "550.00"}
        ]
        total = sum(Decimal(str(line["total"])) for line in lines)
        payload = {
            "customer_uid": str(self.customer.uid),
            "currency_kind": "USD", "currency_rate": "1",
            "is_invoice": True, "status": "OPEN", "tax_kind": "NO_TAX",
            "email": {"customer_email": "c@x.com", "cc_emails": [],
                      "bcc_emails": []},
            "total": str(total), "due_total": str(total),
            "sales_items": lines,
        }
        payload.update(extra)

        set_current_company_id(self.company.id)
        try:
            serializer = PrivateWeSaleListSerializer(
                data=payload, context={"request": _Request(self.user)}
            )
            serializer.is_valid(raise_exception=True)
            return serializer.save()
        finally:
            set_current_company_id(None)

    # --- what 4567a927 fixed, kept as a guard -----------------------------

    def test_an_out_of_stock_line_balances(self):
        """Audit finding 1's shape. Revenue no longer waits on FIFO."""
        self.assert_balances(self.sale(), "out-of-stock product, plain invoice")

    def test_a_service_line_balances(self):
        service = self._product("Consulting", "S1", kind=ProductKindChoices.SERVICE)
        sale = self.sale(lines=[
            {"product_uid": str(service.uid), "quantity": 10,
             "sale_price": "150.00", "total": "1500.00"}
        ])
        self.assert_balances(sale, "service line, 10 x 150.00")

    def test_a_stocked_line_balances(self):
        self._cost_account(self.product)
        self._layer(self.product, 10, "40.00")
        sale = self.sale(lines=[
            {"product_uid": str(self.product.uid), "quantity": 10,
             "sale_price": "100.00", "total": "1000.00"}
        ])
        self.assert_balances(sale, "stocked line, lots available")

    def test_discount_and_shipping_balance(self):
        """Audit finding 2's shape, on this path."""
        self.assert_balances(
            self.sale(discount_kind="PERCENTAGE", discount="10",
                      due_total="495.00"),
            "10% discount",
        )
        self.assert_balances(
            self.sale(shipping_fee="25.00", due_total="575.00"),
            "shipping fee 25.00",
        )

    # --- what it did not fix ----------------------------------------------

    def test_a_product_with_no_income_account_drops_the_revenue_leg(self):
        """`Product.income_account` is nullable and has no fallback.

        `resolve_cogs_account` falls back to the company's COGS control account
        precisely because skipping a leg was never the right answer -- but the
        revenue leg twelve lines above it has no equivalent, and no log line
        either. The receivable is debited in full and nothing is credited.
        """
        no_income = self._product("No Income", "N1", income_account=None)
        sale = self.sale(lines=[
            {"product_uid": str(no_income.uid), "quantity": 1,
             "sale_price": "550.00", "total": "550.00"}
        ])
        self.assert_out_by(sale, "550.000", "product with no income account")

    def test_a_paid_receipt_with_no_deposit_account_drops_the_cash_leg(self):
        """`receivable_charter_account_uid` is optional on the wire.

        A sale receipt settled on the spot carries `due_total = 0`, so there is
        no receivable leg by design, and the whole debit side rests on the
        deposit. With no charter account the deposit is logged and dropped, and
        what is left is a revenue credit with no debit at all -- the production
        shape exactly.
        """
        sale = self.sale(
            is_invoice=False, is_sale_receipt=True,
            deposit="550.00", due_total="0.00",
        )
        self.assert_out_by(sale, "-550.000", "sale receipt, no deposit account")

    def test_a_receipt_reporting_neither_a_due_nor_a_deposit_posts_no_debit(self):
        """Nothing validates that a document's money side reaches an account."""
        sale = self.sale(
            is_invoice=False, is_sale_receipt=True, due_total="0.00",
        )
        self.assert_out_by(sale, "-550.000", "sale receipt, due 0, deposit 0")

    def test_a_line_total_that_disagrees_with_price_times_quantity(self):
        """The poster uses two different definitions of a line's value.

        Revenue is `sale_price * quantity` (`_post_sale_line`), while the
        header total, the tax base and therefore the receivable all come from
        `line.total`. A line where the two disagree splits the entry by the
        difference.
        """
        sale = self.sale(lines=[
            {"product_uid": str(self.product.uid), "quantity": 3,
             "sale_price": "100.00", "total": "270.00"}
        ])
        self.assert_out_by(sale, "-30.000", "line total 270 vs 3 x 100")


class MigrationInvoicePosterBalanceTests(SaleBalanceCase):
    """The OTHER SALE writer: `MigrationInvoiceCreateService.create_invoice`.

    Same document kind, same `JournalEntryKindChoices.SALE`, its own inline
    posting block. Nothing in the 2026-08-06 unification touched it, so both
    create-stage findings from the sales audit are still live here.

    Reached nightly by recurring invoice generation, and by every CSV invoice
    import.
    """

    def invoice(self, lines, **group):
        from datamigrationio.django_rest.services.invoice_importer import (
            MigrationInvoiceCreateService,
        )

        invoice_group = {
            "customer": self.customer,
            "invoice_number": "",
            "invoice_date": date(2026, 8, 6),
            "due_date": date(2026, 9, 5),
            "currency_kind": "USD", "currency_rate": Decimal("1"),
            "full_billing_address": "", "full_shipping_address": "",
            "shipping_by": None, "shipping_date": None, "term": None,
            "memo": "", "receivable_account": self.receivable,
            "lines": lines,
        }
        invoice_group.update(group)
        return MigrationInvoiceCreateService.create_invoice(
            invoice_group, self.user, self.company, options={"send_email": False}
        )

    def item_line(self, product, quantity, rate):
        """What `_map_estimate_lines` produces for an ITEM template line."""
        amount = Decimal(str(rate)) * quantity
        return {
            "product": product, "income_account": None, "quantity": quantity,
            "sale_price": Decimal(str(rate)), "total": amount,
            "description": "item", "tax": None, "is_tax": False,
        }

    def test_an_out_of_stock_item_still_recognises_its_revenue(self):
        """Audit finding 1. Was: out by 550.000.

        The income leg was emitted inside `for layer_source, qty, price in
        deduction_details:`. A product with nothing on hand consumes no layers,
        the loop never ran, and the entry was a lone A/R debit -- the exact
        defect 4567a927 fixed in the serializer and 2d95180d designed out of the
        unified poster. This importer is a second engine that was never folded
        in, so it kept writing it.

        Revenue is now recognised from the invoice line, outside the loop.
        """
        line = self.item_line(self.product, 1, "550.00")
        sale = self.invoice([line], total=Decimal("550.00"),
                            total_tax=Decimal("0"), due_total=Decimal("550.00"))
        self.assert_balances(sale, "importer: out-of-stock item")

    def test_a_partly_stocked_item_recognises_all_of_its_revenue(self):
        """The quieter half of the same defect. Was: out by 600.000.

        4 of 10 units on hand recognised 40% of the revenue and dropped the
        rest, leaving an entry that looked plausible. Worth keeping distinct
        from the out-of-stock case: a zero-revenue entry is obvious on sight,
        a 40% one is not.
        """
        self._cost_account(self.product)
        self._layer(self.product, 4, "40.00")
        line = self.item_line(self.product, 10, "100.00")
        sale = self.invoice([line], total=Decimal("1000.00"),
                            total_tax=Decimal("0"), due_total=Decimal("1000.00"))
        self.assert_balances(sale, "importer: 4 of 10 units on hand")

    def test_revenue_is_posted_once_per_line_not_once_per_consumed_layer(self):
        """The mirror of the same placement bug, in the other direction.

        A line drawing on three lots ran the loop three times, so the revenue
        was credited three times over while A/R was debited once. Posting from
        the line rather than from the layers fixes both directions at once, and
        this pins the one the out-of-stock tests cannot see.
        """
        self._cost_account(self.product)
        for _ in range(3):
            self._layer(self.product, 2, "40.00")
        line = self.item_line(self.product, 6, "100.00")
        sale = self.invoice([line], total=Decimal("600.00"),
                            total_tax=Decimal("0"), due_total=Decimal("600.00"))

        self.assert_balances(sale, "importer: one line drawing on three lots")
        revenue = [
            row for row in self.rows(sale)
            if row.account == self.income and Decimal(str(row.credit or 0))
        ]
        self.assertEqual(
            len(revenue), 1,
            "revenue was credited once per consumed layer, not once per line",
        )

    def test_a_deposit_is_never_journaled(self):
        """`due_total` is net of the deposit and no cash leg replaces it.

        The service stores `deposit` on the Sale and posts nothing for it, so
        the receivable is short by the deposit and no bank account is debited.
        """
        self._cost_account(self.product)
        self._layer(self.product, 1, "0.00")
        line = self.item_line(self.product, 1, "550.00")
        sale = self.invoice(
            [line], total=Decimal("550.00"), total_tax=Decimal("0"),
            deposit=Decimal("100.00"), due_total=Decimal("450.00"),
        )
        self.assert_out_by(sale, "-100.000", "importer: 100.00 deposit")

    def test_a_discount_and_a_shipping_charge_are_never_journaled(self):
        """Audit finding 2, unfixed on this path.

        `total = subtotal + shipping - discount` reaches the receivable, while
        revenue is the gross line amount and neither Sales Discounts nor
        Shipping Income is touched.
        """
        self._cost_account(self.product)
        self._layer(self.product, 1, "0.00")
        line = self.item_line(self.product, 1, "550.00")
        sale = self.invoice(
            [line], total=Decimal("525.00"), total_tax=Decimal("0"),
            discount=Decimal("50.00"), shipping_fee=Decimal("25.00"),
            due_total=Decimal("525.00"),
        )
        self.assert_out_by(sale, "-25.000",
                           "importer: 50.00 discount + 25.00 shipping")

    def test_the_production_shape_reproduces_exactly(self):
        """#JE-046202114, company 114, 2026-08-06: three legs, out by -550.00.

            DEBIT   Inventory Shrinkage      600.00
            CREDIT  Inventory Asset                    600.00
            CREDIT  Sales of Product Income            550.00

        "Inventory Shrinkage" rather than COGS because the debit account is
        whatever `ProductAdditionalCost.expense_account` happens to name -- this
        path never falls back to the company's COGS control account.

        The missing debit is the receivable: the leg sits behind `if
        receivable_account:` with no fallback and no error, so a caller that
        does not supply one -- which is what recurring generation did nightly
        until `receivable_account_for` -- ships a revenue credit with nothing
        against it.
        """
        # Seeded on the ECOMMERCE chart, alongside the real COGS account --
        # which is how a product comes to book cost of sales to it.
        shrinkage = ChartOfAccount.objects.filter(
            company=self.company, title="Inventory Shrinkage"
        ).first()
        self._cost_account(self.product, account=shrinkage)
        self._layer(self.product, 1, "600.00")

        line = self.item_line(self.product, 1, "550.00")
        sale = self.invoice([line], total=Decimal("550.00"),
                            total_tax=Decimal("0"), due_total=Decimal("550.00"),
                            receivable_account=None)

        debit, credit = self.report("importer: production replica", sale)
        titles = sorted(
            row.account.title for row in self.rows(sale) if row.account
        )
        self.assertEqual(
            titles,
            ["Inventory Asset", "Inventory Shrinkage", "Sales of Product Income"],
        )
        self.assertEqual(debit - credit, Decimal("-550.000"))


class RecurringInvoiceBalanceTests(SaleBalanceCase):
    """The importer is not a dormant migration path -- it fires on a schedule.

    `generate_invoice_from_template` is what the recurring beat calls, and it
    posts through `MigrationInvoiceCreateService`, not through
    `post_sale_document`. So every defect in the block above is a live,
    unattended writer of SALE entries, running without anyone submitting a
    payload.
    """

    def template(self, **overrides):
        from recurringio.choices import (
            RecurringTemplateStatusChoices, RecurringTxnTypeChoices,
        )
        from recurringio.models import RecurringTemplate

        fields = dict(
            name="Monthly retainer",
            txn_type=RecurringTxnTypeChoices.INVOICE,
            status=RecurringTemplateStatusChoices.ACTIVE,
            company=self.company, customer=self.customer,
            currency_code="USD", memo="", mailing_address="",
            payment_account=None, auto_email=False,
        )
        fields.update(overrides)
        return RecurringTemplate.objects.create(**fields)

    def item_line(self, template, product, quantity, rate):
        from recurringio.choices import RecurringLineTypeChoices
        from recurringio.models import RecurringTemplateLine

        return RecurringTemplateLine.objects.create(
            template=template, company=self.company,
            line_type=RecurringLineTypeChoices.ITEM,
            product=product, quantity=quantity,
            rate=Decimal(str(rate)),
            amount=Decimal(str(rate)) * quantity,
            description="retainer",
        )

    def fire(self, template):
        from recurringio.services.generation import generate_invoice_from_template

        return generate_invoice_from_template(
            template, self.user, self.company, invoice_date=date(2026, 8, 6)
        )

    def test_a_scheduled_invoice_for_an_out_of_stock_item_balances(self):
        """Nobody submitted anything. The beat wrote this. Was: out by 550.000.

        The reason this one mattered most: an interactive defect is bounded by
        how often someone clicks. This path fires unattended, so a single
        template reproduced the same imbalance every night, which is how weeks
        of identical 550.00 entries reached production.
        """
        template = self.template()
        self.item_line(template, self.product, 1, "550.00")

        sale = self.fire(template)

        self.assert_balances(sale, "recurring beat: out-of-stock item")

    def test_a_scheduled_invoice_with_a_deposit_does_not_balance(self):
        self._cost_account(self.product)
        self._layer(self.product, 1, "0.00")
        template = self.template(deposit=Decimal("100.00"))
        self.item_line(template, self.product, 1, "550.00")

        sale = self.fire(template)

        self.assert_out_by(sale, "-100.000", "recurring beat: 100.00 deposit")
