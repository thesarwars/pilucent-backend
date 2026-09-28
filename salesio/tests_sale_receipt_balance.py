"""A SALE_RECEPT whose header tax exceeds what its tax-flagged lines account for.

Production holds 48 unbalanced SALE_RECEPT entries out of 96 -- a 50% failure
rate. The worst-shaped one, company 165, journal #JE-107272165, 2026-07-06:

    City Bank                 ASSETS       debit   8,090.625
    Sales of Product Income   INCOME       credit  3,000.000 + 4,500.000
    Metro Housing             LIABILITIES  credit     37.500
    (COGS / Inventory pairs balance internally)
    -> out by +553.125

Cash in 8,090.625 against revenue of 7,500 means 590.625 of tax was collected,
but only 37.50 reached a liability account. `_post_unattributed_tax` used to
return as soon as ANY tax leg had posted, so the other 553.125 was detected,
logged, and discarded.

This file is the end-to-end half of `tests_tax_residual.py`, which pins the
helper in isolation against a SimpleNamespace. Here the document is really
built -- Company, seeded chart, Product, FIFO lot, Agency tax, two lines, one
of them tax-flagged -- posted through `post_sale_document`, and the legs are
summed off `JournalEntryConnector` directly.

Summing the connectors is the point. `assert_entry_balances` / `_log_balance`
only LOG an imbalance, so a test that leaned on them would pass on a broken
ledger.

The SALE_RECEPT shape matters and is not the invoice shape already covered in
`journalio.tests.UnattributedTaxTests`: a receipt is paid on the spot, so
`due_total` is 0 and the whole tax-inclusive amount arrives on the *deposit*
leg via `receivable_charter_account`. Both legs run through `quantize_money`,
which rounds to 2 places, while the ledger columns hold 3 and the tax residual
is deliberately posted UNQUANTIZED. On the production figures that is the
difference between 8,090.63 debited and 8,090.625 credited.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from agencyio.models import Agency, AgencyTax, AgencyTaxSet

from common.choices import TaxKindChoices

from companyio.models import Company

from customerio.models import Customer

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from purchaseio.choices import PurchaseItemStatus, PurchaseStatus
from purchaseio.models import Purchase, PurchaseItem

from salesio.choices import (
    SaleItemStatusChoices,
    SaleReceptKindChoices,
    SalesStatusChoices,
)
from salesio.models import Sale, SaleItem

from supplierio.models import Supplier

from weapi.django_rest.helpers.sale_posting import post_sale_document


class SaleReceiptBalanceTests(TestCase):
    """Every SALE_RECEPT this engine writes must have debits == credits."""

    @classmethod
    def setUpTestData(cls):
        # The taxonomy the company chart seeder hangs off. Without it a new
        # Company gets no accounts at all and every control lookup misses.
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Receipt Co {self._nth}", kind="ECOMMERCE"
        )
        self.customer = Customer.objects.create(
            company=self.company, first_name="C", display_name="C"
        )

        # Seeded by the Company signal helpers; resolved by system_key, which is
        # what the poster itself prefers.
        self.income = self._system("SALES_OF_PRODUCT_INCOME")
        self.inventory = self._system("INVENTORY_ASSET")
        self.cogs = self._system("COGS")
        self.payable = self._system("SALES_TAX_PAYABLE")

        # The bank the receipt is deposited into -- "City Bank" in production.
        # NOT filtered to ACTIVE anywhere in the posting path, but created
        # ACTIVE regardless: ChartOfAccount.status defaults to DRAFT, and a
        # queryset that does filter would silently see nothing.
        self.bank = ChartOfAccount.objects.create(
            company=self.company,
            title="City Bank",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

        self.product = Product.objects.create(
            company=self.company, title="Widget", sku=f"W{self._nth}",
            quantity=0, date="2026-01-01",
            kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("100.00"),
            income_account=self.income, asset_account=self.inventory,
        )

        # The agency account the 37.50 landed on. A separate liability from
        # Sales Tax Payable, which is where the residual is meant to go.
        agency = Agency.objects.create(
            company=self.company, title="Metro Housing", status="ACTIVE"
        )
        self.agency_account = ChartOfAccount.objects.create(
            company=self.company,
            title="Metro Housing",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.tax = AgencyTax.objects.create(company=self.company, title="Metro")
        AgencyTaxSet.objects.create(
            taxes=self.tax, agency=agency, rate=Decimal("1.250"),
            sales_tax_account=self.agency_account,
        )

    def _system(self, key):
        account = ChartOfAccount.objects.filter(
            company=self.company, system_key=key
        ).first()
        self.assertIsNotNone(account, f"company chart has no {key} account")
        return account

    def _lot(self, quantity, price):
        """A published purchase lot, so the COGS/inventory pair really posts."""
        from django.db.models import F

        supplier = Supplier.objects.create(
            company=self.company, first_name="S", display_name="S"
        )
        purchase = Purchase.objects.create(
            company=self.company, supplier=supplier, is_bill=True,
            status=PurchaseStatus.OPEN,
        )
        PurchaseItem.objects.create(
            purchase=purchase, product=self.product, quantity=quantity,
            opening_quantity=quantity, purchase_price=Decimal(str(price)),
            status=PurchaseItemStatus.PUBLISHED,
        )
        Product.objects.filter(pk=self.product.pk).update(
            quantity=F("quantity") + quantity
        )

    def _receipt(self, *, total, total_tax, deposit, lines, tax_kind=None):
        """A paid-on-the-spot sale receipt, built from persisted state only.

        `is_sale_receipt` + `kind=SALE` is what makes the poster stamp
        SALE_RECEPT; `due_total=0` with the whole amount on `deposit` is what
        makes it a receipt rather than an invoice.
        """
        sale = Sale.objects.create(
            company=self.company, customer=self.customer,
            invoice_id=f"SR-{self._nth}-{Sale.objects.count() + 1}",
            status=SalesStatusChoices.OPEN,
            kind=SaleReceptKindChoices.SALE,
            is_sale_receipt=True,
            tax_kind=tax_kind or TaxKindChoices.EXCLUSIVE,
            total=Decimal(str(total)),
            total_tax=Decimal(str(total_tax)),
            deposit=Decimal(str(deposit)),
            due_total=Decimal("0.000"),
            receivable_charter_account=self.bank,
        )
        for amount, is_tax in lines:
            SaleItem.objects.create(
                sale=sale, product=self.product, quantity=1,
                sale_price=Decimal(str(amount)), total=Decimal(str(amount)),
                status=SaleItemStatusChoices.PUBLISHED,
                is_tax=is_tax, tax=self.tax if is_tax else None,
            )
        return sale

    def _legs(self, sale):
        entry = JournalEntry.objects.filter(sale=sale).first()
        self.assertIsNotNone(entry, "the receipt posted no journal entry at all")
        return entry, list(entry.journalentryconnector_set.all())

    def _totals(self, sale, label):
        """Sum the connectors by hand. `_log_balance` only logs; it never fails."""
        entry, rows = self._legs(sale)
        debit = sum(Decimal(r.debit or 0) for r in rows)
        credit = sum(Decimal(r.credit or 0) for r in rows)
        print(f"\n  RESULT {label}")
        print(f"         kind={entry.kind} legs={len(rows)}")
        for row in rows:
            title = row.account.title if row.account else "(none)"
            print(f"         {title:<30} dr={row.debit} cr={row.credit}")
        print(f"         debit={debit} credit={credit} D-C={debit - credit}")
        return entry, rows, debit, credit

    # -- the production case ------------------------------------------------

    def test_the_production_receipt_balances(self):
        """Company 165, journal 2694: 590.625 declared, 37.50 attributed.

        3,000 taxed at 1.25% gives the 37.50 that reached Metro Housing; the
        4,500 line carries no tax flag. The header declares 590.625 and the
        bank really took 8,090.625, so 553.125 has to reach a liability.
        """
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("3000.000", True), ("4500.000", False)],
        )
        post_sale_document(sale)

        entry, rows, debit, credit = self._totals(sale, "production receipt")

        self.assertEqual(entry.kind, JournalEntryKindChoices.SALE_RECEPT)
        self.assertEqual(
            debit, credit,
            f"SALE_RECEPT does not balance: debit {debit} vs credit {credit} "
            f"(out by {debit - credit})",
        )

    def test_the_residual_reaches_a_liability_account(self):
        """The 553.125 has to be somewhere, not merely balanced away."""
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("3000.000", True), ("4500.000", False)],
        )
        post_sale_document(sale)

        _entry, rows, _debit, _credit = self._totals(sale, "residual placement")
        agency = sum(
            Decimal(r.credit or 0) for r in rows
            if r.account_id == self.agency_account.pk
        )
        payable = sum(
            Decimal(r.credit or 0) for r in rows if r.account_id == self.payable.pk
        )
        print(f"         agency={agency} sales tax payable={payable}")

        self.assertEqual(agency, Decimal("37.500"))
        self.assertEqual(payable, Decimal("553.130"),
                         "quantized: 553.13 + 7500 + 37.50 = 8090.63, the quantized debit")
        # 590.63, not the declared 590.625. The residual is quantized because
        # the legs it plugs are, so the liability total lands half a tenth of a
        # cent above the header. That is the correct trade: the alternative is
        # a liability matching the header exactly on an entry that does not
        # balance, and an unbalanced ledger is the worse of the two.
        self.assertEqual(agency + payable, Decimal("590.630"))

    # -- the same shape on round money --------------------------------------

    def test_a_whole_cent_receipt_balances(self):
        """The same disagreement with no sub-cent figure anywhere.

        Isolates the header-vs-detail fault from any rounding effect: header
        says 250 of tax, the tax-flagged line accounts for 12.50.
        """
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="250.000", deposit="7750.000",
            lines=[("1000.000", True), ("6500.000", False)],
        )
        post_sale_document(sale)

        _entry, rows, debit, credit = self._totals(sale, "whole-cent receipt")
        payable = sum(
            Decimal(r.credit or 0) for r in rows if r.account_id == self.payable.pk
        )
        print(f"         residual on Sales Tax Payable={payable}")

        self.assertEqual(debit, credit)
        self.assertEqual(payable, Decimal("237.500"))

    def test_a_receipt_with_no_tax_flagged_line_balances(self):
        """Declared tax with nothing attributing it at all."""
        self._lot(2, "10.00")
        sale = self._receipt(
            total="1000.000", total_tax="100.000", deposit="1100.000",
            lines=[("1000.000", False)],
        )
        post_sale_document(sale)

        _entry, rows, debit, credit = self._totals(sale, "wholly unattributed")
        payable = sum(
            Decimal(r.credit or 0) for r in rows if r.account_id == self.payable.pk
        )

        self.assertEqual(debit, credit)
        self.assertEqual(payable, Decimal("100.000"))

    def test_an_inclusive_receipt_balances(self):
        """Inclusive tax sits inside the price, so deposit == total."""
        self._lot(2, "10.00")
        sale = self._receipt(
            total="1000.000", total_tax="90.000", deposit="1000.000",
            lines=[("1000.000", False)],
            tax_kind=TaxKindChoices.INCLUSIVE,
        )
        post_sale_document(sale)

        _entry, rows, debit, credit = self._totals(sale, "inclusive receipt")
        income = sum(
            Decimal(r.credit or 0) for r in rows if r.account_id == self.income.pk
        )
        print(f"         revenue net of inclusive tax={income}")

        self.assertEqual(debit, credit)
        self.assertEqual(income, Decimal("910.000"))

    # -- isolating the sub-cent fault --------------------------------------

    def test_a_sub_cent_header_still_balances(self):
        """A third-decimal tax figure, which the columns hold and money does not.

        `_post_unattributed_tax` posts the residual UNQUANTIZED on purpose --
        its comment (sale_posting.py:889-898) argues that rounding 590.625 to
        590.63 would leave the entry out by 0.005. Every leg opposite it is
        quantized to 2 places, though: `deposit = quantize_money(sale.deposit)`
        at sale_posting.py:1077. So the two conventions have to meet, and this
        checks that they do.
        """
        self._lot(2, "10.00")
        sale = self._receipt(
            total="1000.000", total_tax="100.005", deposit="1100.005",
            lines=[("1000.000", False)],
        )
        post_sale_document(sale)

        _entry, _rows, debit, credit = self._totals(sale, "sub-cent header, up")

        self.assertEqual(
            debit, credit,
            f"sub-cent SALE_RECEPT out by {debit - credit}",
        )

    def test_a_sub_cent_header_rounding_down_still_balances(self):
        """The other rounding direction: quantize takes the deposit DOWN.

        The imbalance is not a fixed +0.005; it is whatever `quantize_money`
        moved the deposit by, so it can land either side of zero.
        """
        self._lot(2, "10.00")
        sale = self._receipt(
            total="1000.000", total_tax="100.001", deposit="1100.001",
            lines=[("1000.000", False)],
        )
        post_sale_document(sale)

        _entry, _rows, debit, credit = self._totals(sale, "sub-cent header, down")

        self.assertEqual(
            debit, credit,
            f"sub-cent SALE_RECEPT out by {debit - credit}",
        )

    def test_a_sub_cent_tax_fully_attributed_to_its_agency_balances(self):
        """The control that names the culprit.

        Same sub-cent tax, same sub-cent deposit -- but the whole 590.625 is
        attributed by the line's own rate (7.875% of 7,500), so no residual leg
        is written. The per-line leg goes through `quantize_money` like every
        other leg and the entry closes.

        If this passes while `test_the_production_receipt_balances` fails, the
        fault is not sub-cent money in general: it is specifically the
        unquantized residual leg at sale_posting.py:903/946.
        """
        AgencyTaxSet.objects.filter(taxes=self.tax).update(rate=Decimal("7.875"))
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("7500.000", True)],
        )
        post_sale_document(sale)

        _entry, rows, debit, credit = self._totals(sale, "fully attributed 7.875%")
        payable = sum(
            Decimal(r.credit or 0) for r in rows if r.account_id == self.payable.pk
        )
        print(f"         residual legs on Sales Tax Payable={payable}")

        self.assertEqual(payable, Decimal("0.000"))
        self.assertEqual(debit, credit)

    def test_the_invoice_path_carries_the_same_fault(self):
        """Blast radius: SALE_RECEPT is not the only kind exposed.

        The receipt's counter-leg is `deposit` (sale_posting.py:1077); an
        invoice's is `due_total` (sale_posting.py:987). Both go through
        `quantize_money`, so the identical document filed as an invoice lands
        the identical imbalance under JournalEntryKindChoices.SALE.
        """
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("3000.000", True), ("4500.000", False)],
        )
        # Same document, billed rather than paid on the spot.
        sale.is_sale_receipt = False
        sale.is_invoice = True
        sale.deposit = Decimal("0.000")
        sale.due_total = Decimal("8090.625")
        sale.receivable_charter_account = None
        sale.save()
        post_sale_document(sale)

        entry, _rows, debit, credit = self._totals(sale, "same figures as an invoice")

        self.assertEqual(entry.kind, JournalEntryKindChoices.SALE)
        self.assertEqual(
            debit, credit,
            f"SALE does not balance either: out by {debit - credit}",
        )

    def test_without_a_sales_tax_payable_account_the_whole_hole_returns(self):
        """The residual has exactly one home, and nothing checks it exists.

        `_post_unattributed_tax` resolves "Sales Tax Payable" through
        `get_chart_of_account`, which prefers `system_key=SALES_TAX_PAYABLE`
        and so survives a rename -- but not a delete or a REMOVED status. With
        the account gone the shortfall leg is skipped, and the entry is short
        by the full 553.125 again, not 0.005.

        Recorded as the size of the remaining exposure, not as a passing
        expectation: this asserts the imbalance rather than the balance.
        """
        self.payable.delete()
        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("3000.000", True), ("4500.000", False)],
        )
        post_sale_document(sale)

        _entry, _rows, debit, credit = self._totals(sale, "no Sales Tax Payable")

        self.assertEqual(debit - credit, Decimal("553.130"))

    def test_the_engine_no_longer_reports_an_imbalance_on_this_shape(self):
        """WAS: `_log_balance` saw the 0.005, wrote an ERROR, stored it anyway.

        The original point of this test was that the finding could not be
        argued away as invisible -- the engine already knew the entry did not
        balance at the moment it committed it, and logging is not a guard.

        That is still true of the engine, and there is simply nothing left for
        it to report on this shape. Inverted rather than deleted, so that if the
        residual ever stops matching its counter-legs the ERROR comes back and
        this test fails loudly instead of quietly passing.
        """
        import logging

        self._lot(2, "10.00")
        sale = self._receipt(
            total="7500.000", total_tax="590.625", deposit="8090.625",
            lines=[("3000.000", True), ("4500.000", False)],
        )
        with self.assertLogs(
            "weapi.django_rest.helpers.sale_posting", level=logging.WARNING
        ) as captured:
            post_sale_document(sale)

        output = "\n".join(captured.output)
        self.assertNotIn(
            "does NOT balance", output,
            "the engine still considers this entry unbalanced",
        )
        # The header-disagrees-with-its-detail WARNING is still expected and is
        # what keeps assertLogs satisfied: 590.625 declared against 37.50 of
        # line tax is a real disagreement, and topping it up does not make the
        # document consistent.
        self.assertTrue(JournalEntry.objects.filter(sale=sale).exists())
