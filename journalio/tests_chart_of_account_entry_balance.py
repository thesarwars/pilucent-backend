"""A CHART_OF_ACCOUNT journal entry must balance, whichever writer produced it.

Production holds **6 unbalanced `CHART_OF_ACCOUNT` entries out of 34**, carrying
the largest single money figure of any kind in the fleet -- 1,150,361.20 across
them, an average of 191,727 per broken entry. The most recent is dated
2026-06-02 on company 165 and is out by **-41,738.00** (credits exceed debits),
which is the signature of a *missing or wrong-sided debit leg*, not of a missing
credit.

Three code paths write that kind. The first two are the opening-balance writers
everybody thinks of; the third is not an opening balance at all and is the one
that can still produce the shape above:

1. **`PrivateWeChartOfAccountListSerializer.create`**
   (`weapi/django_rest/serializers/chart_of_accounts.py:262-330`) -- an account
   created with an opening balance, offset to Opening Balance Equity;

2. **`ChartOfAccountMigrationImporter`**
   (`datamigrationio/django_rest/services/chart_of_account_importer.py:112-165`)
   -- the same posting on the CSV import path;

3. **`transaction_rule_apply.apply_assignment`** -- the bank-feed rule engine.
   `get_rule_journal_kind` maps only EXPENSE, CHECK and DEPOSIT to a kind of
   their own and **defaults everything else to `CHART_OF_ACCOUNT`**
   (`transactionio/django_rest/helpers/transaction_rule_apply.py:95-103`), so an
   auto-add rule whose `trx_type` is `TRANSFER` or `CREDIT_CARD` files its entry
   under this kind. `build_connector_data_for_rule` (same file, lines 106-123)
   then picks both leg actions from **hard-coded strings** rather than from the
   side the transaction requires:

       if rule.transaction_type == TrxRuleTypeChoices.SPENT:
           bank_action, category_action = "substraction", "addition"
       else:
           bank_action, category_action = "addition", "addition"

   `get_debit_or_credit` resolves `"addition"` to DEBIT on ASSETS and EXPENSES
   and to CREDIT on the other three kinds, so a pair of hard-coded actions only
   lands on opposite sides for some combinations of the two accounts' kinds.
   A `TRANSFER` rule moves money between two ASSET accounts -- that is what a
   transfer is -- and a `CREDIT_CARD` rule pays or charges a LIABILITY. Both are
   exactly the combinations the hard-coding gets wrong.

The first class here posts opening balances for an ASSETS and an EQUITIES
account through the real serializer and sums the legs. The second covers the
`opening_balance` PATCH (gap #3) and the income/expense refusal (gap #4). The
third drives the rule engine for the two `trx_type` values that land on this
kind.

Every assertion sums `JournalEntryConnector.debit` / `.credit` for the entry
directly. `assert_entry_balances` **logs and returns a bool** -- it cannot fail
a test, and relying on it is how an unbalanced entry gets written in silence in
the first place.
"""

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from categoryio.models import Category

from companyio.choices import CompanyKindChoices
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
    """The chart-of-account serializers read nothing off the request but `user`."""

    def __init__(self, user):
        self.user = user


def entry_totals(journal_entry):
    """(debit, credit) actually stored against an entry.

    Read back from the connector rows rather than from anything the writer
    reported, because what the writer believed it posted is what is in question.
    """
    rows = JournalEntryConnector.objects.filter(journal=journal_entry)
    debit = sum(Decimal(str(row.debit or 0)) for row in rows)
    credit = sum(Decimal(str(row.credit or 0)) for row in rows)
    return debit, credit


class ChartOfAccountLedgerBase(TestCase):
    """A seeded company: taxonomy first, then the industry chart."""

    @classmethod
    def setUpTestData(cls):
        # The account-type / detail-type tree has to exist before a Company is
        # created: `create_chart_of_accounts` resolves every seed row against it
        # and silently drops the rows it cannot type.
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="Ada", email="coa-balance@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)
        cls.employee = Employee.objects.create(
            user=cls.user, company=cls.company, code="EMP-0001", name_en="Ada"
        )

    def request(self):
        return FakeRequest(self.user)

    def account_type(self, title):
        """A depth-1 taxonomy node -- the vocabulary the API uses."""
        return Category.objects.filter(
            title=title, kind="CHART_OF_ACCOUNT", parent__isnull=False
        ).first()

    def detail_type(self, account_type, title=None):
        queryset = Category.objects.filter(parent=account_type)
        return queryset.filter(title=title).first() if title else queryset.first()

    def obe(self):
        """The company's seeded Opening Balance Equity account.

        Resolved the way the poster resolves it, so a test failure here means
        the poster would have missed it too.
        """
        from common.django_rest.helpers.chart_of_account_helpers import (
            get_chart_of_account,
        )

        return get_chart_of_account(["Opening Balance Equity"], self.company).get(
            "Opening Balance Equity"
        )


class OpeningBalanceEntryBalanceTests(ChartOfAccountLedgerBase):
    """Create an account with an opening balance; sum what it posted."""

    def create_account(self, title, account_type_title, opening_balance, code,
                       detail_title=None):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as Serializer,
        )

        account_type = self.account_type(account_type_title)
        self.assertIsNotNone(
            account_type, f"taxonomy is missing {account_type_title!r}"
        )
        detail = self.detail_type(account_type, detail_title)
        self.assertIsNotNone(detail, f"no detail type under {account_type_title!r}")

        serializer = Serializer(
            data={
                "title": title,
                "code": code,
                "account_type_slug": account_type.slug,
                "detail_type_slug": detail.slug,
                "opening_balance": str(opening_balance),
            },
            context={"request": self.request()},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def only_entry(self):
        entries = list(
            JournalEntry.objects.filter(
                company=self.company, kind=JournalEntryKindChoices.CHART_OF_ACCOUNT
            )
        )
        self.assertEqual(len(entries), 1, f"expected one entry, got {entries}")
        return entries[0]

    # ------------------------------------------------------------ the seeding

    def test_the_company_is_seeded_with_an_opening_balance_equity_account(self):
        """Without it the poster raises COA's own validation error, not a leg.

        Asserted first because every test below is meaningless if the account
        the offset goes to does not exist -- and a missing control account is
        precisely how a poster comes to skip a leg silently elsewhere.
        """
        obe = self.obe()
        self.assertIsNotNone(obe, "company seeding produced no Opening Balance Equity")
        self.assertEqual(obe.kind, ChartOfAccountKindChoices.EQUITIES)
        self.assertEqual(obe.status, ChartOfAccountStatusChoices.ACTIVE)

    # ------------------------------------------------------------- the posting

    def test_an_asset_opening_balance_posts_a_balanced_entry(self):
        """Bank account opened at 1,150,361.20 -- the fleet's largest figure."""
        amount = Decimal("1150361.20")
        account = self.create_account(
            "Opening Bank", "Bank", amount, code="99010", detail_title="Checking"
        )
        self.assertEqual(account.kind, ChartOfAccountKindChoices.ASSETS)

        entry = self.only_entry()
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit,
            credit,
            f"CHART_OF_ACCOUNT entry {entry.pk} does not balance: debit {debit} "
            f"vs credit {credit} (out by {debit - credit})",
        )
        self.assertEqual(debit, amount)

    def test_an_asset_opening_balance_debits_the_account_and_credits_equity(self):
        """Balancing is necessary but not sufficient -- the sides matter too."""
        amount = Decimal("41738.00")
        account = self.create_account(
            "Opening Bank", "Bank", amount, code="99011", detail_title="Savings"
        )

        legs = {
            row.account_id: (Decimal(str(row.debit or 0)), Decimal(str(row.credit or 0)))
            for row in JournalEntryConnector.objects.filter(journal=self.only_entry())
        }
        self.assertEqual(len(legs), 2, f"expected two legs, got {legs}")
        self.assertEqual(legs[account.pk], (amount, Decimal("0")))
        self.assertEqual(legs[self.obe().pk], (Decimal("0"), amount))

    def test_a_liability_opening_balance_posts_a_balanced_entry(self):
        amount = Decimal("41738.00")
        account = self.create_account(
            "Opening Loan", "Long Term Liabilities", amount, code="99251"
        )
        self.assertEqual(account.kind, ChartOfAccountKindChoices.LIABILITIES)

        entry = self.only_entry()
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit,
            credit,
            f"CHART_OF_ACCOUNT entry {entry.pk} does not balance: debit {debit} "
            f"vs credit {credit} (out by {debit - credit})",
        )
        self.assertEqual(credit, amount)

    def test_an_equity_opening_balance_posts_a_balanced_entry(self):
        """The kind that shares its side with the offset account.

        Both legs land on an EQUITIES account here -- the new one and Opening
        Balance Equity -- so a writer that resolved the side from the account
        kind alone, without the action, would put both on the same side.
        """
        amount = Decimal("250000.00")
        account = self.create_account(
            "Owner Capital", "Equity", amount, code="99310"
        )
        self.assertEqual(account.kind, ChartOfAccountKindChoices.EQUITIES)

        entry = self.only_entry()
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit,
            credit,
            f"CHART_OF_ACCOUNT entry {entry.pk} does not balance: debit {debit} "
            f"vs credit {credit} (out by {debit - credit})",
        )

        legs = {
            row.account_id: (Decimal(str(row.debit or 0)), Decimal(str(row.credit or 0)))
            for row in JournalEntryConnector.objects.filter(journal=entry)
        }
        self.assertEqual(legs[account.pk], (Decimal("0"), amount))
        self.assertEqual(legs[self.obe().pk], (amount, Decimal("0")))

    def test_every_postable_kind_posts_a_balanced_opening_balance(self):
        """Run as a matrix, so the report is the whole picture.

        Asserting one kind at a time reports whichever fails first and hides the
        rest; this names every kind that mis-posts in a single failure message.
        """
        cases = [
            ("Bank", "99020", ChartOfAccountKindChoices.ASSETS),
            ("Other Current Assets", "99030", ChartOfAccountKindChoices.ASSETS),
            ("Fixed Assets", "99040", ChartOfAccountKindChoices.ASSETS),
            ("Credit Cards", "99210", ChartOfAccountKindChoices.LIABILITIES),
            ("Other Current Liabilities", "99220", ChartOfAccountKindChoices.LIABILITIES),
            ("Long Term Liabilities", "99230", ChartOfAccountKindChoices.LIABILITIES),
            ("Equity", "99320", ChartOfAccountKindChoices.EQUITIES),
        ]
        amount = Decimal("1000.00")
        broken = {}

        for index, (account_type_title, code, expected_kind) in enumerate(cases):
            account = self.create_account(
                f"Probe {index} {account_type_title}",
                account_type_title,
                amount,
                code=code,
            )
            self.assertEqual(account.kind, expected_kind)

            legs = JournalEntryConnector.objects.filter(account=account)
            self.assertEqual(
                legs.count(), 1, f"{account_type_title}: no opening-balance leg"
            )
            entry = legs.first().journal
            self.assertEqual(entry.kind, JournalEntryKindChoices.CHART_OF_ACCOUNT)
            debit, credit = entry_totals(entry)
            if debit != credit:
                broken[account_type_title] = (debit, credit)

        self.assertEqual(
            broken, {}, f"account types whose opening balance does not balance: {broken}"
        )

    def test_the_equity_offset_matches_the_journal(self):
        """The stored running balance and the ledger have to agree.

        An entry that balances while the offset account's stored figure moved
        the other way is the same defect one layer down -- the balance sheet
        reads the stored figure.
        """
        amount = Decimal("7500.00")
        before = Decimal(str(self.obe().opening_balance))

        self.create_account("Petty Cash", "Bank", amount, code="99060")

        self.assertEqual(Decimal(str(self.obe().opening_balance)), before + amount)

    def test_a_zero_opening_balance_posts_nothing(self):
        """No movement, no entry -- an empty entry would be the worse answer."""
        self.create_account("Empty Bank", "Bank", Decimal("0"), code="99070")

        self.assertFalse(
            JournalEntry.objects.filter(
                company=self.company, kind=JournalEntryKindChoices.CHART_OF_ACCOUNT
            ).exists()
        )


class OpeningBalanceAmendmentTests(ChartOfAccountLedgerBase):
    """Gap #3 and gap #4: the routes that were storing a balance with no journal."""

    def bank_account(self, amount, code="99080"):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as Serializer,
        )

        account_type = self.account_type("Bank")
        serializer = Serializer(
            data={
                "title": f"Bank {code}",
                "code": code,
                "account_type_slug": account_type.slug,
                "detail_type_slug": self.detail_type(account_type).slug,
                "opening_balance": str(amount),
            },
            context={"request": self.request()},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_patching_the_opening_balance_no_longer_moves_the_stored_figure(self):
        """Gap #3. The field is read-only on update, so the PATCH is a no-op.

        That is the half of the gap that mattered: the old behaviour rewrote the
        stored balance with no journal entry and no Opening Balance Equity
        offset behind it, so the account disagreed with its own ledger from that
        moment on. Refusing the write leaves the account correct and the
        correction to a dated journal entry.
        """
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as Serializer,
        )

        account = self.bank_account(Decimal("5000.00"), code="99081")
        entries_before = JournalEntry.objects.filter(company=self.company).count()

        serializer = Serializer(
            instance=account,
            data={"opening_balance": "9999.00"},
            partial=True,
            context={"request": self.request()},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        account.refresh_from_db()
        self.assertEqual(Decimal(str(account.opening_balance)), Decimal("5000.000"))
        self.assertEqual(
            JournalEntry.objects.filter(company=self.company).count(), entries_before
        )

    def test_an_income_account_cannot_carry_an_opening_balance(self):
        """Gap #4. It used to be stored on the row and never journaled."""
        from rest_framework.exceptions import ValidationError

        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as Serializer,
        )

        for account_type_title in ("Income", "Expense"):
            with self.subTest(account_type=account_type_title):
                account_type = self.account_type(account_type_title)
                serializer = Serializer(
                    data={
                        "title": f"Probe {account_type_title}",
                        "code": "99490",
                        "account_type_slug": account_type.slug,
                        "detail_type_slug": self.detail_type(account_type).slug,
                        "opening_balance": "1000.00",
                    },
                    context={"request": self.request()},
                )
                with self.assertRaises(ValidationError):
                    serializer.is_valid(raise_exception=True)


class BankFeedRuleChartOfAccountEntryTests(ChartOfAccountLedgerBase):
    """The third writer of this kind, and the only one that is not an opening balance.

    `get_rule_journal_kind` names EXPENSE, CHECK and DEPOSIT and defaults
    everything else to CHART_OF_ACCOUNT, so an auto-add rule whose `trx_type` is
    TRANSFER or CREDIT_CARD posts under this kind. Those are precisely the two
    types whose category account shares a side with the bank account, which is
    what `build_connector_data_for_rule`'s hard-coded actions cannot express.
    """

    def account(self, title, kind, code):
        return ChartOfAccount.objects.create(
            company=self.company,
            title=title,
            code=code,
            kind=kind,
            # Not DRAFT. `ChartOfAccount.status` defaults to DRAFT and the
            # resolvers filter it out, so a DRAFT account is invisible.
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )

    def rule_for(self, category, *, trx_type, transaction_type):
        rule = TransactionRules.objects.create(
            company=self.company,
            transaction_type=transaction_type,
            all_account=True,
            is_all=True,
            auto_add=True,
        )
        TransactionRuleParams.objects.create(
            rule=rule, field="DESCRIPTION", operation="contains", value="wire"
        )
        TransactionRuleAssign.objects.create(
            rule=rule, trx_type=trx_type, chart_of_account=category
        )
        return rule

    def transaction(self, bank, received=None, spent=None):
        return TransactionInformation.objects.create(
            company=self.company,
            chart_of_account=bank,
            date=date(2026, 6, 2),
            description="ONLINE WIRE TRANSFER",
            received=received,
            spent=spent,
        )

    def apply(self):
        from transactionio.django_rest.helpers.transaction_rule_apply import (
            apply_rules_for_transactions,
        )

        return apply_rules_for_transactions(company_uid=str(self.company.uid))

    def posted_entry(self, transaction):
        transaction.refresh_from_db()
        self.assertIsNotNone(
            transaction.journal_entry,
            "the rule engine posted nothing -- `apply_assignment` swallows every "
            "exception, so a failure here means the posting itself raised",
        )
        self.assertEqual(
            transaction.journal_entry.kind,
            JournalEntryKindChoices.CHART_OF_ACCOUNT,
            "this trx_type is expected to fall through to the default kind",
        )
        return transaction.journal_entry

    def test_a_transfer_type_rule_files_its_entry_under_chart_of_account(self):
        """The premise. TRANSFER is not in `get_rule_journal_kind`'s map."""
        from transactionio.django_rest.helpers.transaction_rule_apply import (
            get_rule_journal_kind,
        )

        for trx_type in (
            TrxAssignTypeChoices.TRANSFER,
            TrxAssignTypeChoices.CREDIT_CARD,
        ):
            with self.subTest(trx_type=trx_type):
                assign = TransactionRuleAssign(trx_type=trx_type)
                self.assertEqual(
                    get_rule_journal_kind(assign),
                    JournalEntryKindChoices.CHART_OF_ACCOUNT,
                )

    def test_an_incoming_transfer_between_two_banks_balances(self):
        """Money arriving from the company's own second account.

        Both accounts are ASSETS, both actions are the hard-coded `"addition"`,
        and `get_debit_or_credit` resolves `"addition"` to DEBIT on an asset --
        so both legs are debits and the entry is out by twice the amount.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "99110")
        savings = self.account("Savings", ChartOfAccountKindChoices.ASSETS, "99120")
        self.rule_for(
            savings,
            trx_type=TrxAssignTypeChoices.TRANSFER,
            transaction_type=TrxRuleTypeChoices.RECEIVED,
        )
        transaction = self.transaction(bank, received=Decimal("20869.00"))

        self.assertEqual(self.apply()["auto_confirmed"], 1)

        entry = self.posted_entry(transaction)
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit,
            credit,
            f"CHART_OF_ACCOUNT entry {entry.entry_number} does not balance: "
            f"debit {debit} vs credit {credit} (out by {debit - credit})",
        )

    def test_a_transfer_moves_the_money_rather_than_duplicating_it(self):
        """The damage is not confined to the journal.

        `build_connector_data_for_rule` hard-codes the *balance* operation from
        the same branch -- CREDIT (add) on both accounts for a RECEIVED rule --
        so the account the money came FROM is raised by the transfer instead of
        being drawn down. The same cash is then counted twice on the balance
        sheet, which is how a stored figure comes to exceed its own ledger.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "99140")
        savings = self.account("Savings", ChartOfAccountKindChoices.ASSETS, "99150")
        self.rule_for(
            savings,
            trx_type=TrxAssignTypeChoices.TRANSFER,
            transaction_type=TrxRuleTypeChoices.RECEIVED,
        )
        self.transaction(bank, received=Decimal("20869.00"))

        self.apply()

        bank.refresh_from_db()
        savings.refresh_from_db()
        self.assertEqual(bank.opening_balance, Decimal("20869.000"))
        self.assertEqual(
            savings.opening_balance,
            Decimal("-20869.000"),
            "the account the transfer came from should have been drawn down",
        )

    def test_a_credit_card_charge_balances(self):
        """Spending on a card: credit the liability, debit the expense.

        A SPENT rule hard-codes `"substraction"` for the funding account and
        `"addition"` for the category. With the card as the funding account
        (`trx.chart_of_account`) and an expense as the category the pair is
        right; with the card as the *category* -- which is what a CREDIT_CARD
        rule names -- `"addition"` credits the liability while the bank's
        `"substraction"` credits the asset, and both legs are credits.
        """
        bank = self.account("City Bank", ChartOfAccountKindChoices.ASSETS, "99130")
        card = self.account("Amex", ChartOfAccountKindChoices.LIABILITIES, "99211")
        self.rule_for(
            card,
            trx_type=TrxAssignTypeChoices.CREDIT_CARD,
            transaction_type=TrxRuleTypeChoices.SPENT,
        )
        transaction = self.transaction(bank, spent=Decimal("20869.00"))

        self.assertEqual(self.apply()["auto_confirmed"], 1)

        entry = self.posted_entry(transaction)
        debit, credit = entry_totals(entry)

        self.assertEqual(
            debit,
            credit,
            f"CHART_OF_ACCOUNT entry {entry.entry_number} does not balance: "
            f"debit {debit} vs credit {credit} (out by {debit - credit})",
        )

    def test_every_category_kind_a_transfer_rule_can_name(self):
        """Which combinations mis-post, reported as one matrix.

        Both directions, all five kinds. A rule author picks the category from
        the whole chart, so every one of these ten is reachable through the UI.
        """
        broken = {}
        for direction in (TrxRuleTypeChoices.RECEIVED, TrxRuleTypeChoices.SPENT):
            for index, kind in enumerate(ChartOfAccountKindChoices.values):
                # One rule live at a time: `apply_rules_for_transactions` runs
                # every rule in the company oldest-first and they all match the
                # same description, so a leftover rule would categorise this
                # round's transaction and the matrix would repeat one result.
                TransactionRules.objects.all().delete()

                suffix = f"{direction[:3]}{index}"
                bank = self.account(
                    f"Bank {suffix}", ChartOfAccountKindChoices.ASSETS, f"991{index}9"
                )
                category = self.account(f"Cat {suffix}", kind, f"971{index}9")
                self.rule_for(
                    category,
                    trx_type=TrxAssignTypeChoices.TRANSFER,
                    transaction_type=direction,
                )
                amount = Decimal("100.00")
                transaction = self.transaction(
                    bank,
                    received=amount if direction == TrxRuleTypeChoices.RECEIVED else None,
                    spent=amount if direction == TrxRuleTypeChoices.SPENT else None,
                )

                self.apply()

                transaction.refresh_from_db()
                self.assertIsNotNone(
                    transaction.journal_entry, f"{direction}/{kind}: posted nothing"
                )
                debit, credit = entry_totals(transaction.journal_entry)
                if debit != credit:
                    broken[f"{direction}->{kind}"] = (debit, credit)

        self.assertEqual(
            broken, {}, f"rule shapes that post an unbalanced entry: {broken}"
        )
