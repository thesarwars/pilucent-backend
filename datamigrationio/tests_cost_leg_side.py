"""A bill's cost line must DEBIT whatever account it is coded to.

Production, company 114 "Jumatechs", journal 1460, PURCHASE, 2026-04-23:

    MN Income Tax             LIABILITIES  credit 147.000
    Accounts Payable (A/P)    LIABILITIES  credit 147.000
    -> out by -294.000, i.e. exactly -2 x 147, nothing debited.

The line was coded to a LIABILITY. `"addition"` resolves to DEBIT on assets and
expenses but CREDIT on liabilities, equity and income, so the cost leg credited
alongside the A/P leg and the entry was short by twice the amount.

These importers are what `recurringio` drives nightly, so this shape was being
regenerated unattended.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company

from datamigrationio.django_rest.services.bill_importer import (
    MigrationBillCreateService,
)

from journalio.django_rest.services.journals import assert_entry_balances
from journalio.models import JournalEntry

from supplierio.models import Supplier


class BillCostLegSideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.user = User.objects.create_user(
            name="Tester", email="importer@example.com", password="pass1234!"
        )
        cls.company = Company.objects.create(name="Acme Books")
        cls.supplier = Supplier.objects.create(
            company=cls.company, first_name="Widgets", display_name="Widgets Ltd"
        )

    def account(self, title, kind):
        """Reuse the seeded account of that title, or make one.

        Creating a Company seeds ~66 accounts from the category tree, so titles
        like "Office Supplies" and "Accounts Payable (A/P)" already exist. These
        tests used to create a second one, which `unique_title_per_company_ci`
        now forbids -- and reusing the seeded row is closer to production anyway,
        where the importer resolves an account that is already there.
        """
        existing = ChartOfAccount.objects.filter(
            company=self.company, title__iexact=title
        ).exclude(status=ChartOfAccountStatusChoices.REMOVED).first()
        if existing:
            if existing.kind != kind:
                existing.kind = kind
                existing.save(update_fields=["kind"])
            return existing

        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def payable(self):
        """Get-or-create, and it has to actually get.

        This filtered on `system_key=AP` while `account()` never sets one, so the
        lookup never matched and every call minted another "Accounts Payable
        (A/P)". Harmless until `unique_title_per_company_ci` existed; now it is
        an IntegrityError on the second `import_bill` in a test.
        """
        existing = ChartOfAccount.objects.filter(
            company=self.company, title__iexact="Accounts Payable (A/P)"
        ).first()
        if existing:
            return existing

        account = self.account(
            "Accounts Payable (A/P)", ChartOfAccountKindChoices.LIABILITIES
        )
        account.system_key = ChartOfAccountSystemKeyChoices.AP
        account.save(update_fields=["system_key"])
        return account

    def import_bill(self, cost_account, amount=Decimal("147.000")):
        payable = self.payable()
        bill_group = {
            "supplier": self.supplier,
            "bill_number": "",
            "bill_date": "2026-08-07",
            "due_date": "2026-09-07",
            "currency_kind": "USD",
            "currency_rate": 1,
            "full_billing_address": "",
            "memo": "",
            "total": amount,
            "total_tax": Decimal("0"),
            "due_total": amount,
            "warehouse": None,
            "payable_account": payable,
            "lines": [
                {
                    "line_kind": "EXPENSE",
                    "expense_account": cost_account,
                    "product": None,
                    "quantity": 1,
                    "purchase_price": amount,
                    "total": amount,
                    "description": "one line",
                    "tax": None,
                }
            ],
        }
        return MigrationBillCreateService.create_bill(
            bill_group, self.user, self.company, options={}
        )

    def legs(self, purchase):
        entry = JournalEntry.objects.filter(purchase=purchase).first()
        self.assertIsNotNone(entry, "the bill wrote no journal entry")
        return entry, {
            row.account.title: row
            for row in entry.journalentryconnector_set.select_related("account")
        }

    def test_a_line_coded_to_a_liability_debits_it(self):
        """The production defect, reproduced with the same account and amount."""
        cost = self.account("MN Income Tax", ChartOfAccountKindChoices.LIABILITIES)

        purchase = self.import_bill(cost)

        entry, rows = self.legs(purchase)
        leg = rows["MN Income Tax"]
        self.assertEqual(leg.debit, Decimal("147.000"))
        self.assertEqual(leg.credit, Decimal("0.000"))
        self.assertTrue(
            assert_entry_balances(entry),
            "the entry does not balance -- this is journal 1460's -294",
        )

    def test_the_stored_balance_moves_with_the_leg(self):
        """A debit on a liability SUBTRACTS from the stored balance.

        Pairing the balance operation to the action is what lets the rollback
        services unwind to zero: they re-derive the undo from the stored
        connector kind.
        """
        cost = self.account("MN Income Tax", ChartOfAccountKindChoices.LIABILITIES)
        before = cost.opening_balance

        self.import_bill(cost)

        cost.refresh_from_db()
        # `opening_balance` is stored as a float, so compare in Decimal.
        self.assertEqual(
            Decimal(str(cost.opening_balance)), Decimal(str(before)) - Decimal("147")
        )

    def test_every_account_kind_debits_and_balances(self):
        """The account is user-chosen, so all five kinds have to work."""
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                cost = self.account(f"Coded {kind}", kind)

                purchase = self.import_bill(cost)

                entry, rows = self.legs(purchase)
                leg = rows[f"Coded {kind}"]
                self.assertEqual(leg.debit, Decimal("147.000"))
                self.assertEqual(leg.credit, Decimal("0.000"))
                self.assertTrue(assert_entry_balances(entry))

    def test_an_expense_coded_line_is_unchanged(self):
        """The no-op proof.

        A correctly-typed tenant must see identical rows before and after. If
        this moves, the change is not a repair.
        """
        cost = self.account("Office Supplies", ChartOfAccountKindChoices.EXPENSES)
        before = cost.opening_balance

        purchase = self.import_bill(cost)

        entry, rows = self.legs(purchase)
        leg = rows["Office Supplies"]
        self.assertEqual(leg.debit, Decimal("147.000"))
        self.assertEqual(leg.credit, Decimal("0.000"))
        cost.refresh_from_db()
        self.assertEqual(
            Decimal(str(cost.opening_balance)), Decimal(str(before)) + Decimal("147")
        )
        self.assertTrue(assert_entry_balances(entry))
