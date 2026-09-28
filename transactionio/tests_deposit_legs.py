"""A deposit debits where the money lands and credits where it came from.

Company 114's nightly recurring deposit was out by -200 every night:

    MN Income Tax                 LIABILITIES  credit 100.000
    City Bank                     ASSETS       debit  299.000
    Federal Taxes (941/943/944)   EXPENSES     credit 399.000

Recurring template 9 takes 100.000 of cash back to `MN Income Tax` -- a
LIABILITY. Cash back has to DEBIT, because the bank leg is posted net of it,
but the action was hard-coded `"addition"`, which resolves to DEBIT only on
assets and expenses. On a liability it credited, so the amount landed on the
wrong side and the entry was out by twice the cash back. Fixed in 40dd9ccf;
production deposits have balanced since.

These pin the two siblings that were still hard-coded, plus the case where cash
back names no account at all -- the bank leg is netted down regardless, so the
entry would be short by exactly the cash back with nothing saying why.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    get_debit_or_credit,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices


class DepositLegSideTests(TestCase):
    """The side each deposit leg must land on, for every account kind.

    Driving the serializer needs a request, deposit items and a bank account;
    the defect is entirely in which side each leg resolves to, so this pins the
    resolution the serializer now uses.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Jumatechs")

    def account(self, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=f"Acct {kind}", kind=kind,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def side(self, account, action):
        return get_debit_or_credit(account.kind)[action]

    def test_the_bank_leg_debits_whatever_kind_it_is(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                account = self.account(kind)
                action = action_for_side(
                    account.kind, JournalEntryConnectorKindChoices.DEBIT
                )
                self.assertEqual(
                    self.side(account, action),
                    JournalEntryConnectorKindChoices.DEBIT,
                )

    def test_the_received_from_leg_credits_whatever_kind_it_is(self):
        for kind in ChartOfAccountKindChoices.values:
            with self.subTest(kind=kind):
                account = self.account(kind)
                action = action_for_side(
                    account.kind, JournalEntryConnectorKindChoices.CREDIT
                )
                self.assertEqual(
                    self.side(account, action),
                    JournalEntryConnectorKindChoices.CREDIT,
                )

    def test_the_old_hard_coded_actions_were_wrong_for_three_kinds(self):
        """Why this needed changing at all.

        `"substraction"` was the received-from action and `"addition"` the bank
        one. Each is right for only two of the five kinds.
        """
        wrong_received_from = [
            kind for kind in ChartOfAccountKindChoices.values
            if get_debit_or_credit(kind)["substraction"]
            != JournalEntryConnectorKindChoices.CREDIT
        ]
        wrong_bank = [
            kind for kind in ChartOfAccountKindChoices.values
            if get_debit_or_credit(kind)["addition"]
            != JournalEntryConnectorKindChoices.DEBIT
        ]
        self.assertEqual(sorted(wrong_received_from), sorted(wrong_bank))
        self.assertEqual(len(wrong_received_from), 3)

    def test_cash_back_to_a_liability_debits(self):
        """Template 9's exact shape: cash back taken to MN Income Tax."""
        account = self.account(ChartOfAccountKindChoices.LIABILITIES)
        action = action_for_side(
            account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        self.assertEqual(
            self.side(account, action), JournalEntryConnectorKindChoices.DEBIT
        )


class CashBackValidationTests(TestCase):
    def test_cash_back_without_an_account_is_rejected(self):
        from rest_framework.serializers import ValidationError
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer,
        )

        serializer = PrivateWeBankDepositListCreateSerializer()
        with self.assertRaises(ValidationError) as raised:
            serializer.validate({
                "deposit_items": [{"amount": "100"}],
                "cash_back_amount": Decimal("100.00"),
            })

        self.assertIn("cash_back_account_uid", str(raised.exception))

    def test_cash_back_with_an_account_passes(self):
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer,
        )

        serializer = PrivateWeBankDepositListCreateSerializer()
        data = serializer.validate({
            "deposit_items": [{"amount": "100"}],
            "cash_back_amount": Decimal("100.00"),
            "cash_back_account_uid": object(),
        })

        self.assertIn("deposit_items", data)

    def test_no_cash_back_needs_no_account(self):
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer,
        )

        serializer = PrivateWeBankDepositListCreateSerializer()
        data = serializer.validate({"deposit_items": [{"amount": "100"}]})

        self.assertIn("deposit_items", data)
