"""Every EXPENSE journal entry the current code writes must have debits == credits.

Production holds 6 unbalanced EXPENSE entries out of 75 (8%), 4,972.00 in total,
the most recent dated 2026-07-30. A low rate means the common path is fine and
something *conditional* breaks it, so this file builds a real Expense down each
variant and sums `JournalEntryConnector.debit` / `.credit` by hand.

Summing by hand is the point. `assert_entry_balances` only LOGS an imbalance --
it deliberately does not raise, because several writers still produce unbalanced
entries -- so a test that leaned on it would pass on a broken ledger.

Two live writers produce `kind=EXPENSE`, and they disagree about one thing:

    weapi PrivateWeExpenseListSerializer.create   the expense screen
    MigrationExpenseCreateService.create_expense  CSV import AND the nightly
                                                 recurring-template generator

Both credit the funding account with the document's `total` and debit the cost
lines plus the tax separately, so both are balanced only when `total` is
TAX-INCLUSIVE. That is the convention the screen uses (the bill and cheque
posters credit `due_total` / `total` against lines + tax, same shape).

`create_expense` inherited that assumption -- its own docstring says it "mirrors
PrivateWeExpenseListSerializer.create()" -- but **neither of its callers passes
a tax-inclusive total**:

    recurringio/services/generation.py:166,179  `_map_lines` returns the EX-TAX
        subtotal, and `_build_expense_group` puts it in "total" with the tax
        alongside in "total_tax" (its own test asserts total=99, tax=9.90 for a
        99.00 line at 10%, and it sets deposit = total + total_tax, which is
        only correct if total is net).
    datamigrationio/.../expense_importer.py:571  the CSV grouper does
        `total += line_amount` per row and accumulates `total_tax` separately.

So the funding credit is short by exactly the tax on every generated or imported
expense that carries any. A tax-free one balances, which is why the rate is 8%
and not 100%.

The variants are pinned individually so the fix can be aimed at the right line
rather than at "expenses".
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIRequestFactory

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from adminio.models import CompanyRole

from agencyio.models import Agency, AgencyTax, AgencyTaxSet

from companyio.models import Company, CompanyUser

from datamigrationio.django_rest.services.expense_importer import (
    MigrationExpenseCreateService,
)

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry

from paymentio.choices import PaymentMethodStatusChoices
from paymentio.models import PaymentMethod

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product

from purchaseio.choices import (
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchaseStatus,
)
from purchaseio.models import Purchase, PurchaseItem

from recurringio.choices import (
    RecurringLineTypeChoices,
    RecurringTemplateTypeChoices,
    RecurringTxnTypeChoices,
)
from recurringio.models import RecurringTemplate, RecurringTemplateLine
from recurringio.services.generation import generate_expense_from_template

from supplierio.choices import SupplierStatusChoices
from supplierio.models import Supplier

from weapi.django_rest.serializers.purchases import (
    PrivateWeExpenseListSerializer,
    PrivateWePurchaseItemDetailsSerializer,
)


class ExpenseLedgerTestCase(TestCase):
    """Shared scaffolding: a company that can actually post an expense."""

    @classmethod
    def setUpTestData(cls):
        # The taxonomy the company chart seeder hangs off. Without it a new
        # Company is seeded with NO accounts and every control lookup misses.
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        super().setUp()
        self._nth = getattr(self, "_nth", 0) + 1
        self.company = Company.objects.create(
            name=f"Expense Co {self._nth}", kind="ECOMMERCE"
        )
        self.user = User.objects.create_user(
            name="Tester",
            email=f"expense{self._nth}@example.com",
            password="pass1234!",
        )
        membership = CompanyUser.objects.create(user=self.user, company=self.company)
        membership.roles.add(
            CompanyRole.objects.create(
                company=self.company, name="admin", is_system=True
            )
        )
        self.supplier = Supplier.objects.create(
            company=self.company,
            first_name="Widgets",
            display_name="Widgets Ltd",
            status=SupplierStatusChoices.ACTIVE,
        )
        self.payment_method = PaymentMethod.objects.create(
            company=self.company, status=PaymentMethodStatusChoices.ACTIVE
        )

        # Seeded by the Company signal helpers and resolved by system_key --
        # which is what the posters themselves prefer, falling back to title.
        self.inventory = self._system("INVENTORY_ASSET")
        self.sales_tax_payable = self._system("SALES_TAX_PAYABLE")

        # ACTIVE explicitly: ChartOfAccount.status defaults to DRAFT, and the
        # serializer's payment-account field filters on ACTIVE.
        self.bank = ChartOfAccount.objects.create(
            company=self.company,
            title="City Bank",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        self.rent = ChartOfAccount.objects.create(
            company=self.company,
            title="Rent Expense",
            kind=ChartOfAccountKindChoices.EXPENSES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def _system(self, key):
        account = ChartOfAccount.objects.filter(
            company=self.company, system_key=key
        ).first()
        self.assertIsNotNone(account, f"company chart has no {key} account")
        return account

    def _tax(self, rate):
        """An AgencyTax whose combined group rate is `rate` percent."""
        agency = Agency.objects.create(
            company=self.company, title="Metro", status="ACTIVE"
        )
        agency_account = ChartOfAccount.objects.create(
            company=self.company,
            title=f"Metro Tax {self._nth}",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        tax = AgencyTax.objects.create(company=self.company, title="Metro")
        AgencyTaxSet.objects.create(
            taxes=tax,
            agency=agency,
            rate=Decimal(str(rate)),
            sales_tax_account=agency_account,
        )
        return tax

    def _totals(self, entry, label=""):
        """Sum the legs by hand and report them. Never trusts the log-only check."""
        rows = list(entry.journalentryconnector_set.all())
        debit = sum(Decimal(str(row.debit or 0)) for row in rows)
        credit = sum(Decimal(str(row.credit or 0)) for row in rows)
        print(
            f"\n[{label or entry.entry_number}] {len(rows)} legs  "
            f"debit={debit}  credit={credit}  out_by={debit - credit}"
        )
        for row in rows:
            print(
                f"    {row.account.title:<28} {row.account.kind:<12} "
                f"{row.kind:<7} debit={row.debit} credit={row.credit}"
            )
        return debit, credit

    def _entry_for(self, expense):
        entry = JournalEntry.objects.filter(
            expense=expense, kind=JournalEntryKindChoices.EXPENSE
        ).first()
        self.assertIsNotNone(entry, "the expense posted no journal entry at all")
        return entry

    # -- the expense screen: an Expense pays off existing purchases, so the
    #    legs come from the PURCHASE's lines, its `total_tax` and its `total`.

    def _purchase(self, *, total, total_tax=Decimal("0")):
        return Purchase.objects.create(
            company=self.company,
            supplier=self.supplier,
            status=PurchaseStatus.OPEN,
            total=Decimal(str(total)),
            total_tax=Decimal(str(total_tax)),
            due_total=Decimal(str(total)),
        )

    def _line(self, purchase, *, kind, total, product=None, account=None):
        return PurchaseItem.objects.create(
            purchase=purchase,
            status=PurchaseItemStatus.PUBLISHED,
            kind=kind,
            total=Decimal(str(total)),
            quantity=1 if product else 0,
            opening_quantity=1 if product else 0,
            product=product,
            charter_account=account,
        )

    def _product(self):
        return Product.objects.create(
            company=self.company,
            title="Widget",
            sku=f"W{self._nth}{Product.objects.count()}",
            quantity=0,
            date="2026-01-01",
            kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("100.00"),
            asset_account=self.inventory,
        )

    def _post_expense(self, purchases, *, total):
        factory = APIRequestFactory()
        request = factory.post("/", {}, format="json")
        request.user = self.user
        payload = {
            "date": "2026-07-30",
            "total": str(total),
            "supplier_uid": str(self.supplier.uid),
            "payment_method_uid": str(self.payment_method.uid),
            "payment_account_uid": str(self.bank.uid),
            "purchase_uids": [str(purchase.uid) for purchase in purchases],
        }
        serializer = PrivateWeExpenseListSerializer(
            data=payload, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()


class ExpenseScreenBalanceTests(ExpenseLedgerTestCase):
    """`PrivateWeExpenseListSerializer.create` -- the expense screen."""

    def test_a_plain_product_expense_balances(self):
        """The common path: one stocked line, no tax. Control case."""
        purchase = self._purchase(total="500")
        self._line(
            purchase,
            kind=PurchaseItemkind.PRODUCT,
            total="500",
            product=self._product(),
        )

        expense = self._post_expense([purchase], total="500")
        debit, credit = self._totals(self._entry_for(expense), "screen: product")

        self.assertEqual(debit, Decimal("500.000"))
        self.assertEqual(credit, Decimal("500.000"))

    def test_an_account_coded_expense_line_balances(self):
        """The other common path: a category line coded to an expense account."""
        purchase = self._purchase(total="500")
        self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="500", account=self.rent
        )

        expense = self._post_expense([purchase], total="500")
        debit, credit = self._totals(self._entry_for(expense), "screen: category")

        self.assertEqual(debit, Decimal("500.000"))
        self.assertEqual(credit, Decimal("500.000"))

    def test_tax_balances_when_the_documents_total_includes_it(self):
        """Tax is debited on top of the lines, so `total` has to be gross."""
        purchase = self._purchase(total="550", total_tax="50")
        self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="500", account=self.rent
        )

        expense = self._post_expense([purchase], total="550")
        debit, credit = self._totals(self._entry_for(expense), "screen: gross total")

        self.assertEqual(debit, Decimal("550.000"))
        self.assertEqual(credit, Decimal("550.000"))

    def test_a_net_of_tax_header_total_leaves_the_entry_short(self):
        """The screen's half of the same contract, stated as a fact.

        Nothing on this path derives `total` from the lines -- it is whatever
        the caller sent. Send it net of tax and the funding credit is short by
        exactly the tax, with no error and no rejection. This is the shape the
        recurring generator hits every night; see the class below.
        """
        purchase = self._purchase(total="500", total_tax="50")
        self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="500", account=self.rent
        )

        expense = self._post_expense([purchase], total="500")
        debit, credit = self._totals(self._entry_for(expense), "screen: net total")

        self.assertEqual(debit, Decimal("550.000"))
        self.assertEqual(credit, Decimal("500.000"))
        self.assertNotEqual(
            debit, credit, "if this now balances the header contract changed"
        )

    def test_an_expense_line_with_no_account_drops_its_debit(self):
        """`if expense_item.charter_account:` skips the leg, not the money.

        weapi/django_rest/serializers/purchases.py:2169. The funding credit
        still carries the whole document total, so the line's cost simply
        vanishes from the debit side.
        """
        purchase = self._purchase(total="500")
        self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="300", account=self.rent
        )
        self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="200", account=None
        )

        expense = self._post_expense([purchase], total="500")
        debit, credit = self._totals(self._entry_for(expense), "screen: no account")

        self.assertEqual(debit, Decimal("300.000"))
        self.assertEqual(credit, Decimal("500.000"))

    def test_a_product_line_with_no_product_drops_its_debit(self):
        """`if product_item.product:` -- same shape, on the inventory leg.

        weapi/django_rest/serializers/purchases.py:2145.
        """
        purchase = self._purchase(total="500")
        self._line(
            purchase,
            kind=PurchaseItemkind.PRODUCT,
            total="300",
            product=self._product(),
        )
        self._line(purchase, kind=PurchaseItemkind.PRODUCT, total="200", product=None)

        expense = self._post_expense([purchase], total="500")
        debit, credit = self._totals(self._entry_for(expense), "screen: no product")

        self.assertEqual(debit, Decimal("300.000"))
        self.assertEqual(credit, Decimal("500.000"))


class ExpenseLineAmendBalanceTests(ExpenseLedgerTestCase):
    """Amending a line of an already-expensed purchase.

    `PrivateWePurchaseItemDetailsSerializer.update` restates the line's own
    debit to the new total and moves `JournalEntry.amount`, but never touches
    the funding credit the Expense posted for the whole document -- the mirror
    rule this codebase keeps rediscovering. The entry is left out by exactly the
    change.
    """

    def _patch_line(self, item, payload):
        factory = APIRequestFactory()
        request = factory.patch("/", payload, format="json")
        request.user = self.user
        serializer = PrivateWePurchaseItemDetailsSerializer(
            item, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_raising_a_line_total_leaves_the_funding_credit_behind(self):
        purchase = self._purchase(total="500")
        item = self._line(
            purchase, kind=PurchaseItemkind.EXPENSE, total="500", account=self.rent
        )
        expense = self._post_expense([purchase], total="500")
        entry = self._entry_for(expense)
        self.assertEqual(self._totals(entry, "amend: before"), (
            Decimal("500.000"), Decimal("500.000")
        ))

        purchase.refresh_from_db()  # the Expense create sets is_via_expense
        self._patch_line(item, {"total": "700"})

        debit, credit = self._totals(entry, "amend: after")
        self.assertEqual(debit, Decimal("700.000"))
        self.assertEqual(credit, Decimal("500.000"))


class RecurringAndImportedExpenseBalanceTests(ExpenseLedgerTestCase):
    """`MigrationExpenseCreateService.create_expense` -- cron and CSV import.

    This is the writer that runs unattended, so an imbalance here is never seen
    by anyone at the time it is written.
    """

    def _template(self, *, tax=None, tax_kind=None, amount="500"):
        template = RecurringTemplate.objects.create(
            company=self.company,
            name="Monthly rent",
            txn_type=RecurringTxnTypeChoices.EXPENSE,
            template_type=RecurringTemplateTypeChoices.SCHEDULED,
            supplier=self.supplier,
            payment_account=self.bank,
            payment_method=self.payment_method,
            currency_code="USD",
            tax_kind=tax_kind,
            memo="monthly rent",
        )
        RecurringTemplateLine.objects.create(
            company=self.company,
            template=template,
            line_type=RecurringLineTypeChoices.CATEGORY,
            position=0,
            amount=Decimal(str(amount)),
            charter_account=self.rent,
            tax=tax,
            description="rent",
        )
        return template

    def test_a_recurring_expense_without_tax_balances(self):
        """Control: the tax-free firing is fine, which is why the rate is 8%."""
        template = self._template()

        expense = generate_expense_from_template(
            template, self.user, self.company, expense_date=date(2026, 7, 30)
        )
        debit, credit = self._totals(self._entry_for(expense), "recurring: no tax")

        self.assertEqual(debit, Decimal("500.000"))
        self.assertEqual(credit, Decimal("500.000"))

    def test_a_recurring_expense_with_tax_balances(self):
        """WAS THE BUG: tax debited, the funding credit never grew to match.

        500.00 of rent at 10% exclusive:

            Rent Expense       debit  500.00
            Sales Tax Payable  debit   50.00
            City Bank          credit 500.00   <- should be 550.00

        `_build_expense_group` hands `create_expense` the EX-TAX subtotal as
        "total" (recurringio/services/generation.py:179), and `create_expense`
        credits exactly that
        (datamigrationio/django_rest/services/expense_importer.py:344-363)
        while debiting the tax on top (:369-387).
        """
        tax = self._tax(10)
        template = self._template(tax=tax, tax_kind="EXCLUSIVE")

        expense = generate_expense_from_template(
            template, self.user, self.company, expense_date=date(2026, 7, 30)
        )
        entry = self._entry_for(expense)
        debit, credit = self._totals(entry, "recurring: 10% exclusive")

        self.assertEqual(debit, Decimal("550.000"))
        self.assertEqual(credit, Decimal("550.000"),
                         "the funding credit must carry the gross, not the net")
        self.assertEqual(debit - credit, Decimal("0.000"))

    def test_an_inclusive_recurring_expense_balances(self):
        """WAS out by twice the tax: the line stayed gross, the total went net.

        `_map_lines` keeps the line's own amount on the line dict but backs the
        tax out of the subtotal, so the debit side gains the tax while the
        credit side loses it.
        """
        tax = self._tax(10)
        template = self._template(tax=tax, tax_kind="INCLUSIVE", amount="550")

        expense = generate_expense_from_template(
            template, self.user, self.company, expense_date=date(2026, 7, 30)
        )
        debit, credit = self._totals(self._entry_for(expense), "recurring: inclusive")

        self.assertEqual(debit, Decimal("550.000"),
                         "an inclusive line must be debited NET of its tax")
        self.assertEqual(credit, Decimal("550.000"))
        self.assertEqual(debit - credit, Decimal("0.000"))

    def test_the_importer_contract_credits_the_gross(self):
        """Pinned at the service, independent of the recurring mapper.

        The CSV importer builds its group the same way -- `total += line_amount`
        per row with `total_tax` accumulated separately
        (expense_importer.py:568,585) -- so it lands here too.
        """
        expense = MigrationExpenseCreateService.create_expense(
            {
                "supplier": self.supplier,
                "payment_account": self.bank,
                "payment_method": self.payment_method,
                "expense_date": date(2026, 7, 30),
                "reference_number": "EXP-1",
                "currency_kind": "USD",
                "currency_rate": Decimal("1"),
                "description": "imported",
                "total": Decimal("500"),
                "total_tax": Decimal("50"),
                "lines": [
                    {
                        "line_kind": "EXPENSE",
                        "expense_account": self.rent,
                        "total": Decimal("500"),
                        "description": "rent",
                        "tax": None,
                    }
                ],
            },
            self.user,
            self.company,
        )
        debit, credit = self._totals(self._entry_for(expense), "import: net total")

        self.assertEqual(debit, Decimal("550.000"))
        self.assertEqual(credit, Decimal("550.000"),
                         "`total` is ex-tax by contract, so the credit is total + total_tax")

    def test_a_missing_inventory_account_drops_every_product_debit(self):
        """The silent skip named in the brief, on the biggest leg there is.

        `if product_lines and inventory_charter_account:` (expense_importer.py
        :276). A company whose Inventory Asset account was renamed away or
        removed posts the funding credit and nothing against it.
        """
        product = Product.objects.create(
            company=self.company,
            title="Widget",
            sku=f"W{self._nth}",
            quantity=0,
            date="2026-01-01",
            kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE,
            sale_price=Decimal("100.00"),
        )
        # Rename it out of reach of both the system_key and the title lookup.
        ChartOfAccount.objects.filter(pk=self.inventory.pk).update(
            system_key=None, title="Old Inventory"
        )

        expense = MigrationExpenseCreateService.create_expense(
            {
                "supplier": self.supplier,
                "payment_account": self.bank,
                "payment_method": self.payment_method,
                "expense_date": date(2026, 7, 30),
                "reference_number": "EXP-2",
                "currency_kind": "USD",
                "currency_rate": Decimal("1"),
                "description": "imported",
                "total": Decimal("400"),
                "total_tax": Decimal("0"),
                "lines": [
                    {
                        "line_kind": "PRODUCT",
                        "product": product,
                        "quantity": 4,
                        "purchase_price": Decimal("100"),
                        "total": Decimal("400"),
                        "description": "widgets",
                        "tax": None,
                    }
                ],
            },
            self.user,
            self.company,
        )
        debit, credit = self._totals(self._entry_for(expense), "import: no inventory")

        self.assertEqual(debit, Decimal("0.000"))
        self.assertEqual(credit, Decimal("400.000"))
