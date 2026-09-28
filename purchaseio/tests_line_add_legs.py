"""Adding a line to a posted bill must write both legs, or neither.

`PrivateWePurchaseItemListSerializer.create` appended exactly one leg to the
document's existing journal entry -- the inventory debit on a PRODUCT line, the
expense debit on an EXPENSE line -- and nothing to fund it. An entry that
balanced before the line was added came out short by exactly the line.

That matters beyond the arithmetic: producing unbalanced entries from a live
endpoint is what stops the write-time balance check in
`create_journal_entry_connector` being turned from a log into a raise.

Which account funds it depends on the document. A bill increases what is owed,
so it credits Accounts Payable; a cheque comes straight out of the account it
is drawn on; an expense comes out of the account it was paid from.
"""

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from companyio.models import Company

from purchaseio.models import Expense, ExpenseConnector, Purchase

from supplierio.models import Supplier

from weapi.django_rest.serializers.purchases import funding_account_for_line_add


class FundingAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.supplier = Supplier.objects.create(
            company=cls.company, first_name="Widgets", display_name="Widgets Ltd"
        )
        cls.payable = ChartOfAccount.objects.create(
            company=cls.company, title="Accounts Payable (A/P)", code="2000",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        cls.bank = ChartOfAccount.objects.create(
            company=cls.company, title="City Bank", code="1000",
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def purchase(self, **flags):
        return Purchase.objects.create(
            company=self.company, supplier=self.supplier, **flags
        )

    def test_a_bill_is_funded_from_accounts_payable(self):
        purchase = self.purchase(is_bill=True)

        self.assertEqual(
            funding_account_for_line_add(purchase, self.company), self.payable
        )

    def test_a_cheque_is_funded_from_the_account_it_is_drawn_on(self):
        purchase = self.purchase(is_cheque=True, charter_account=self.bank)

        self.assertEqual(
            funding_account_for_line_add(purchase, self.company), self.bank
        )

    def test_an_expense_is_funded_from_its_payment_account(self):
        purchase = self.purchase(is_via_expense=True)
        expense = Expense.objects.create(
            supplier=self.supplier, payment_account=self.bank
        )
        ExpenseConnector.objects.create(purchase=purchase, expense=expense)

        self.assertEqual(
            funding_account_for_line_add(purchase, self.company), self.bank
        )

    def test_a_document_with_nothing_to_fund_it_returns_none(self):
        """The caller posts neither leg rather than the cost one alone."""
        purchase = self.purchase(is_cheque=True, charter_account=None)

        self.assertIsNone(funding_account_for_line_add(purchase, self.company))

    def test_a_company_without_accounts_payable_returns_none(self):
        self.payable.delete()
        purchase = self.purchase(is_bill=True)

        self.assertIsNone(funding_account_for_line_add(purchase, self.company))


class LineAddPostsBothLegsTests(TestCase):
    """The structural guarantee, pinned at the source.

    Driving the serializer needs a posted purchase, its journal entry, a
    product with stock and a request user. What regressed is that one leg
    could be written without the other, and that the balance moved before the
    funding account was known -- so those are what these assert.
    """

    def source(self):
        import inspect

        from weapi.django_rest.serializers import purchases

        return inspect.getsource(purchases.PrivateWePurchaseItemListSerializer.create)

    def test_both_branches_are_gated_on_having_somewhere_to_fund_from(self):
        source = self.source()

        self.assertEqual(source.count("and posts_to_ledger"), 2)
        self.assertNotIn("and journal_entry\n        ):", source)

    def test_the_funding_account_is_resolved_before_any_balance_moves(self):
        """Resolving it late meant the cost leg's balance had already moved.

        A balance that moves with no journal line beside it is the divergence
        this whole sweep has been closing; the guard must not create one.
        """
        source = self.source()

        resolve_at = source.index("funding_account_for_line_add(purchase, company)")
        first_balance_move = source.index("update_opening_balance(")
        self.assertLess(resolve_at, first_balance_move)
