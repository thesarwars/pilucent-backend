"""A BANK_DEPOSIT entry must balance whichever writer produced it.

Production holds 16 unbalanced `BANK_DEPOSIT` journal entries out of 44, most
recent 2026-08-02, 12,228.00 out. **Two** code paths write that kind, and only
one of them has ever been looked at:

1. the bank-deposit document -- `PrivateWeBankDepositListCreateSerializer` --
   which the manual screen and the recurring generator both drive. Its leg sides
   were made kind-aware in 5c132875 / 40dd9ccf and its cash-back-with-no-account
   hole was closed by `validate`;

2. **the bank-feed rule engine** -- `transaction_rule_apply.apply_assignment`.
   `TransactionRuleAssign.trx_type` defaults to `DEPOSIT`, and
   `get_rule_journal_kind` maps `DEPOSIT` to `JournalEntryKindChoices.BANK_DEPOSIT`,
   so every auto-add rule that has not explicitly chosen another type posts a
   `BANK_DEPOSIT` entry. `build_connector_data_for_rule` is still written the way
   the deposit serializer used to be: the two leg actions are **hard-coded
   strings**, not resolved from the side the transaction requires.

   For a RECEIVED rule both legs are `"addition"`. `get_debit_or_credit` maps
   `"addition"` to DEBIT on assets and expenses and to CREDIT on the other three
   kinds, so the pair only lands on opposite sides when the categorised account
   is an income, liability or equity account. Categorise a deposit to an ASSET
   -- Undeposited Funds, Accounts Receivable, a second bank -- or to an EXPENSE
   -- a vendor refund -- and the bank leg and the category leg are **both
   debits**. The entry is out by twice the amount, and nothing says so:
   `assert_entry_balances` only logs, and `apply_assignment` wraps the whole
   posting in `except Exception: continue`.

The first class here posts real deposit documents end to end and sums the legs,
to confirm the document path is genuinely fixed rather than fixed-by-inspection.
The second does the same through the rule engine, which is not.

Both sum `JournalEntryConnector.debit` / `.credit` directly. `assert_entry_balances`
logs and returns a bool -- it cannot fail a test.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from employeeio.models import Employee

from journalio.choices import JournalEntryKindChoices
from journalio.models import JournalEntry, JournalEntryConnector

from transactionio.choices import TrxAssignTypeChoices, TrxRuleTypeChoices
from transactionio.models import (
    TransactionInformation,
    TransactionRuleAssign,
    TransactionRuleParams,
    TransactionRules,
)


class FakeRequest:
    """The deposit serializer reads nothing off the request but `user`."""

    def __init__(self, user):
        self.user = user


def entry_totals(journal_entry):
    """(debit, credit) actually stored for an entry.

    Read from the connectors rather than from anything the writer reported,
    because what the writer believed it posted is exactly what is in question.
    """
    rows = JournalEntryConnector.objects.filter(journal=journal_entry)
    debit = sum(Decimal(str(row.debit or 0)) for row in rows)
    credit = sum(Decimal(str(row.credit or 0)) for row in rows)
    return debit, credit


class BankDepositLedgerBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")
        cls.user = User.objects.create_user(
            name="Ada", email="ada@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)
        cls.employee = Employee.objects.create(
            user=cls.user, company=cls.company, name="Ada"
        )

    def account(self, title, kind, code="1000"):
        return ChartOfAccount.objects.create(
            company=self.company,
            title=title,
            code=code,
            kind=kind,
            # Not DRAFT: the serializer's picker querysets filter to ACTIVE and
            # the model default is DRAFT, so a DRAFT account is invisible here.
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )


class BankDepositDocumentBalanceTests(BankDepositLedgerBase):
    """The deposit document: build one, post it, sum its legs."""

    def deposit(self, items, bank, **extra):
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer,
        )

        payload = {
            "date": date(2026, 8, 2).isoformat(),
            "bank_chart_of_account_uid": str(bank.uid),
            "description": "test deposit",
            "deposit_items": [
                {
                    "date": date(2026, 8, 2).isoformat(),
                    "description": "line",
                    "reference_number": "",
                    "type": "",
                    "amount": str(amount),
                    "received_from_account_uid": str(account.uid),
                }
                for account, amount in items
            ],
        }
        payload.update(extra)

        serializer = PrivateWeBankDepositListCreateSerializer(
            data=payload, context={"request": FakeRequest(self.user)}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def posted_entry(self, deposit):
        entry = JournalEntry.objects.filter(bank_deposit=deposit).first()
        self.assertIsNotNone(entry, "the deposit posted no journal entry at all")
        self.assertEqual(entry.kind, JournalEntryKindChoices.BANK_DEPOSIT)
        return entry

    def test_a_plain_two_item_deposit_balances(self):
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        undeposited = self.account(
            "Undeposited Funds", ChartOfAccountKindChoices.ASSETS, code="1100"
        )
        income = self.account(
            "Other Income", ChartOfAccountKindChoices.INCOMES, code="4100"
        )

        deposit = self.deposit(
            [(undeposited, "300.00"), (income, "200.00")], bank
        )
        debit, credit = entry_totals(self.posted_entry(deposit))

        self.assertEqual(debit, Decimal("500.000"))
        self.assertEqual(credit, Decimal("500.000"))

    def test_cash_back_to_a_liability_balances(self):
        """The shape 40dd9ccf fixed, checked on the posted legs this time."""
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        undeposited = self.account(
            "Undeposited Funds", ChartOfAccountKindChoices.ASSETS, code="1100"
        )
        mn_income_tax = self.account(
            "MN Income Tax", ChartOfAccountKindChoices.LIABILITIES, code="2100"
        )

        deposit = self.deposit(
            [(undeposited, "299.00")],
            bank,
            cash_back_amount="100.00",
            cash_back_account_uid=str(mn_income_tax.uid),
        )
        debit, credit = entry_totals(self.posted_entry(deposit))

        # bank 199 + cash back 100 debit, undeposited funds 299 credit.
        self.assertEqual(debit, Decimal("299.000"))
        self.assertEqual(credit, Decimal("299.000"))

    def test_a_deposit_from_every_account_kind_balances(self):
        """Money can be received from any kind; each must credit its source."""
        for index, kind in enumerate(ChartOfAccountKindChoices.values):
            with self.subTest(kind=kind):
                bank = self.account(
                    f"Bank {kind}", ChartOfAccountKindChoices.ASSETS,
                    code=f"10{index}0",
                )
                source = self.account(f"Source {kind}", kind, code=f"20{index}0")

                deposit = self.deposit([(source, "750.00")], bank)
                debit, credit = entry_totals(self.posted_entry(deposit))

                self.assertEqual(debit, credit, f"{kind}: {debit} vs {credit}")
                self.assertEqual(debit, Decimal("750.000"))

    def test_a_deposit_into_a_credit_card_liability_balances(self):
        bank = self.account("Amex", ChartOfAccountKindChoices.LIABILITIES)
        undeposited = self.account(
            "Undeposited Funds", ChartOfAccountKindChoices.ASSETS, code="1100"
        )

        deposit = self.deposit([(undeposited, "125.50")], bank)
        debit, credit = entry_totals(self.posted_entry(deposit))

        self.assertEqual(debit, Decimal("125.500"))
        self.assertEqual(credit, Decimal("125.500"))


class BankFeedRuleDepositBalanceTests(BankDepositLedgerBase):
    """The other BANK_DEPOSIT writer: auto-add bank-feed rules.

    `TransactionRuleAssign.trx_type` defaults to DEPOSIT, so this is the kind an
    auto-add rule posts unless the author picked otherwise.
    """

    def rule_for(self, category, transaction_type=TrxRuleTypeChoices.RECEIVED,
                 trx_type=TrxAssignTypeChoices.DEPOSIT):
        rule = TransactionRules.objects.create(
            company=self.company,
            transaction_type=transaction_type,
            all_account=True,
            is_all=True,
            auto_add=True,
        )
        TransactionRuleParams.objects.create(
            rule=rule, field="DESCRIPTION", operation="contains", value="deposit"
        )
        TransactionRuleAssign.objects.create(
            rule=rule, trx_type=trx_type, chart_of_account=category
        )
        return rule

    def transaction(self, bank, received=None, spent=None):
        return TransactionInformation.objects.create(
            company=self.company,
            chart_of_account=bank,
            date=date(2026, 8, 2),
            description="ACH DEPOSIT from customer",
            received=received,
            spent=spent,
        )

    def apply(self):
        from transactionio.django_rest.helpers.transaction_rule_apply import (
            apply_rules_for_transactions,
        )

        return apply_rules_for_transactions(company_uid=str(self.company.uid))

    def only_entry(self):
        entries = list(JournalEntry.objects.filter(company=self.company))
        self.assertEqual(len(entries), 1, f"expected one entry, got {entries}")
        self.assertEqual(entries[0].kind, JournalEntryKindChoices.BANK_DEPOSIT)
        return entries[0]

    def test_a_deposit_categorised_to_income_balances(self):
        """The one shape the hard-coded actions happen to get right."""
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        income = self.account(
            "Sales", ChartOfAccountKindChoices.INCOMES, code="4000"
        )
        self.rule_for(income)
        self.transaction(bank, received=Decimal("1000.00"))

        result = self.apply()
        self.assertEqual(result["auto_confirmed"], 1)

        debit, credit = entry_totals(self.only_entry())
        self.assertEqual(debit, Decimal("1000.00"))
        self.assertEqual(credit, Decimal("1000.00"))

    def test_a_deposit_categorised_to_undeposited_funds_posts_two_debits(self):
        """The failing shape. Both legs debit; the entry is out by 2x.

        Sweeping undeposited funds into the bank is the single most ordinary
        thing a deposit rule does, and it is an ASSET-to-ASSET move, so both
        legs resolve `"addition"` to DEBIT.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        undeposited = self.account(
            "Undeposited Funds", ChartOfAccountKindChoices.ASSETS, code="1100"
        )
        self.rule_for(undeposited)
        self.transaction(bank, received=Decimal("1000.00"))

        result = self.apply()
        self.assertEqual(result["auto_confirmed"], 1)

        entry = self.only_entry()
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit, credit,
            f"BANK_DEPOSIT {entry.entry_number} does not balance: "
            f"debit {debit} vs credit {credit} (out by {debit - credit})",
        )

    def test_the_stored_balances_double_count_the_same_cash(self):
        """The damage is not confined to the journal.

        `build_connector_data_for_rule` hard-codes the balance operation too --
        CREDIT (add) on both accounts for a RECEIVED rule. Sweeping undeposited
        funds into the bank should raise the bank and *lower* undeposited funds;
        instead both rise, so the same 1,000 is counted as cash twice.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        undeposited = self.account(
            "Undeposited Funds", ChartOfAccountKindChoices.ASSETS, code="1100"
        )
        self.rule_for(undeposited)
        self.transaction(bank, received=Decimal("1000.00"))

        self.apply()

        bank.refresh_from_db()
        undeposited.refresh_from_db()
        self.assertEqual(bank.opening_balance, Decimal("1000.000"))
        self.assertEqual(
            undeposited.opening_balance, Decimal("-1000.000"),
            "the funds swept into the bank should have left undeposited funds",
        )

    def test_a_deposit_categorised_to_an_expense_refund_posts_two_debits(self):
        """A vendor refund banked against the expense it reverses."""
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        expense = self.account(
            "Office Supplies", ChartOfAccountKindChoices.EXPENSES, code="6000"
        )
        self.rule_for(expense)
        self.transaction(bank, received=Decimal("237.50"))

        result = self.apply()
        self.assertEqual(result["auto_confirmed"], 1)

        entry = self.only_entry()
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit, credit,
            f"BANK_DEPOSIT {entry.entry_number} does not balance: "
            f"debit {debit} vs credit {credit} (out by {debit - credit})",
        )

    def test_every_category_kind_a_received_rule_can_name(self):
        """Which of the five kinds a RECEIVED auto-add rule mis-posts.

        Run as one matrix so the report is the whole picture rather than
        whichever kind happens to be asserted first.
        """
        broken = {}
        for index, kind in enumerate(ChartOfAccountKindChoices.values):
            # One rule live at a time. `apply_rules_for_transactions` runs every
            # rule in the company oldest-first and each of these matches the same
            # description, so leaving the previous round's rule in place would
            # categorise this round's transaction to the previous kind and the
            # matrix would report the first kind five times over.
            TransactionRules.objects.all().delete()

            bank = self.account(
                f"Bank {kind}", ChartOfAccountKindChoices.ASSETS, code=f"10{index}0"
            )
            category = self.account(f"Cat {kind}", kind, code=f"70{index}0")
            self.rule_for(category)
            trx = self.transaction(bank, received=Decimal("100.00"))

            self.apply()

            trx.refresh_from_db()
            self.assertIsNotNone(
                trx.journal_entry, f"{kind}: rule posted nothing"
            )
            debit, credit = entry_totals(trx.journal_entry)
            if debit != credit:
                broken[kind] = (debit, credit)

        self.assertEqual(broken, {}, f"kinds that post an unbalanced deposit: {broken}")

    def test_a_spent_rule_left_on_the_default_deposit_type_also_posts_bank_deposit(self):
        """`trx_type` defaults to DEPOSIT, so a SPENT rule lands here too.

        Paying down a credit card: bank `"substraction"` credits the asset, and
        the liability category's `"addition"` credits as well. Two credits, and
        the entry is filed under BANK_DEPOSIT because nobody changed the default.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS)
        card = self.account(
            "Amex Payable", ChartOfAccountKindChoices.LIABILITIES, code="2000"
        )
        self.rule_for(card, transaction_type=TrxRuleTypeChoices.SPENT)
        self.transaction(bank, spent=Decimal("500.00"))

        result = self.apply()
        self.assertEqual(result["auto_confirmed"], 1)

        entry = self.only_entry()
        self.assertEqual(entry.kind, JournalEntryKindChoices.BANK_DEPOSIT)
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit, credit,
            f"BANK_DEPOSIT {entry.entry_number} does not balance: "
            f"debit {debit} vs credit {credit} (out by {debit - credit})",
        )
