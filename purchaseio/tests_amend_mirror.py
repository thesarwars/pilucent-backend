"""Amending a bill or its payment must move the balance the way the posting did.

Six amend legs in `purchases.py` went through
`update_opening_balance(account, "update", new, old)`, which decides its
direction from whether the figure rose or fell and reads no account kind at all.

Two of the six were moving the wrong way on the CONVENTIONAL kinds, not merely
on unusual ones -- these are live, not latent:

    Sales Tax Payable   posting DEBITS it (a purchase's tax is always a debit,
                        so the entry balances against net cost lines), which
                        SUBTRACTS from a liability's stored balance. Raising the
                        tax on an amendment ADDED to it.

    deposit funding     posting CREDITS it -- money leaving -- which SUBTRACTS
                        from a bank asset. Raising the deposit ADDED to it.

The remaining four were correct on their conventional kind and stopped mirroring
the posting the moment the posting legs became kind-aware, which they now are:
`purchases.py` resolves every create leg through `action_for_side`.

In all six the journal column written beside the balance move was already right.
So the journal and the stored balance moved opposite ways while the entry itself
still balanced -- the one shape the write-time balance check cannot see.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    amend_balance,
    amend_leg,
    balance_operation_for_action,
    get_debit_or_credit,
    update_opening_balance,
)

from companyio.models import Company

from journalio.choices import JournalEntryConnectorKindChoices


DEBIT = JournalEntryConnectorKindChoices.DEBIT
CREDIT = JournalEntryConnectorKindChoices.CREDIT

# Each amended leg, and the side the posting fixed it on.
LEGS = {
    "bill: accounts payable": CREDIT,
    "bill: sales tax payable": DEBIT,
    "bill: deposit funding": CREDIT,
    "expense payment: funding": CREDIT,
    "bill payment: accounts payable": DEBIT,
    "bill payment: funding": CREDIT,
}


class AmendMirrorTests(TestCase):
    BASELINE = Decimal("1000")

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    def account(self, title, kind):
        return ChartOfAccount.objects.create(
            company=self.company, title=title, kind=kind,
            opening_balance=self.BASELINE,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def post(self, account, side, amount):
        """What the kind-aware create path does."""
        action = action_for_side(account.kind, side)
        update_opening_balance(
            account, balance_operation_for_action(action), amount, 0
        )
        account.refresh_from_db()
        return action

    def side_of(self, account, action):
        return get_debit_or_credit(account.kind)[action]

    def test_posting_a_bill_then_amending_it_equals_posting_the_new_figure(self):
        """The mirror property, for every leg on every kind."""
        for leg, side in LEGS.items():
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(leg=leg, kind=kind):
                    stepped = self.account(f"stepped {leg} {kind}", kind)
                    self.post(stepped, side, Decimal("100"))
                    amend_leg(stepped, side, Decimal("150"), Decimal("100"))
                    stepped.refresh_from_db()

                    direct = self.account(f"direct {leg} {kind}", kind)
                    self.post(direct, side, Decimal("150"))

                    self.assertEqual(
                        Decimal(str(stepped.opening_balance)),
                        Decimal(str(direct.opening_balance)),
                    )

    def test_raising_the_tax_on_a_bill_reduces_sales_tax_payable(self):
        """Live defect: `"update"` raised it.

        A purchase debits Sales Tax Payable, and a debit on a liability reduces
        it. The old op added the difference instead.
        """
        tax = self.account("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES)

        self.post(tax, DEBIT, Decimal("100"))
        after_post = Decimal(str(tax.opening_balance))
        self.assertEqual(after_post, self.BASELINE - Decimal("100"))

        amend_leg(tax, DEBIT, Decimal("150"), Decimal("100"))
        tax.refresh_from_db()

        self.assertEqual(
            Decimal(str(tax.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_raising_a_deposit_reduces_the_funding_account(self):
        """Live defect: `"update"` raised it. Money leaving a bank lowers it."""
        bank = self.account("Business Checking", ChartOfAccountKindChoices.ASSETS)

        self.post(bank, CREDIT, Decimal("100"))
        amend_leg(bank, CREDIT, Decimal("150"), Decimal("100"))
        bank.refresh_from_db()

        self.assertEqual(
            Decimal(str(bank.opening_balance)), self.BASELINE - Decimal("150")
        )

    def test_the_old_update_op_moved_both_of_those_the_other_way(self):
        """Kept as the executable statement of what was wrong."""
        for title, kind, side in (
            ("Sales Tax Payable", ChartOfAccountKindChoices.LIABILITIES, DEBIT),
            ("Business Checking", ChartOfAccountKindChoices.ASSETS, CREDIT),
        ):
            with self.subTest(account=title):
                old_way = self.account(f"{title} old", kind)
                update_opening_balance(
                    old_way, "update", Decimal("150"), Decimal("100")
                )
                old_way.refresh_from_db()

                new_way = self.account(f"{title} new", kind)
                amend_leg(new_way, side, Decimal("150"), Decimal("100"))
                new_way.refresh_from_db()

                self.assertEqual(
                    Decimal(str(old_way.opening_balance)),
                    self.BASELINE + Decimal("50"),
                )
                self.assertEqual(
                    Decimal(str(new_way.opening_balance)),
                    self.BASELINE - Decimal("50"),
                )

    def test_lowering_a_figure_walks_each_leg_back(self):
        for leg, side in LEGS.items():
            for kind in ChartOfAccountKindChoices.values:
                with self.subTest(leg=leg, kind=kind):
                    account = self.account(f"down {leg} {kind}", kind)

                    amend_leg(account, side, Decimal("150"), Decimal("100"))
                    amend_leg(account, side, Decimal("100"), Decimal("150"))
                    account.refresh_from_db()

                    self.assertEqual(
                        Decimal(str(account.opening_balance)), self.BASELINE
                    )

    def test_the_journal_column_each_leg_writes_matches_its_side(self):
        """The in-place column writes were already right; the balance was not.

        If these ever disagree the fix has inverted the journal instead of the
        balance, which would be worse than what it replaced.
        """
        cases = [
            ("payable_journal_item.debit", ChartOfAccountKindChoices.LIABILITIES, DEBIT),
            ("payment_journal_item.credit", ChartOfAccountKindChoices.ASSETS, CREDIT),
            ("journal_entry_item.credit", ChartOfAccountKindChoices.LIABILITIES, CREDIT),
            ("journal_entry_item.debit", ChartOfAccountKindChoices.LIABILITIES, DEBIT),
        ]
        for column, kind, side in cases:
            with self.subTest(column=column):
                account = self.account(f"col {column} {kind}", kind)
                landed = self.side_of(account, action_for_side(account.kind, side))
                self.assertEqual(landed, column.rsplit(".", 1)[1].upper())


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.serializers import purchases

        return inspect.getsource(purchases)

    def test_no_chart_of_account_amends_through_the_update_op(self):
        """Only the BILL amend's Supplier balance may still use it.

        It was two. The payment amend's vendor line has moved to
        `amend_balance` -- see the two tests below for why one went and one
        stayed.

        `update_quantity(product, "update", ...)` is a stock movement, not a
        ledger leg, and keeps its literal too.
        """
        source = self.source()
        offenders = []
        for i, line in enumerate(source.splitlines()):
            if '"update",' not in line or line.strip().startswith("#"):
                continue
            window = "\n".join(source.splitlines()[max(0, i - 4):i])
            if "update_quantity(" in window:
                continue
            if "supplier" in window.lower():
                continue
            offenders.append(i + 1)

        self.assertEqual(offenders, [], f"chart-of-account amends still on 'update': {offenders}")

    def test_all_six_legs_route_through_amend_leg(self):
        self.assertEqual(self.source().count("amend_leg("), 6)

    def test_the_payment_amend_moves_the_vendor_the_way_the_payment_did(self):
        """The kind-less twin of the six legs above.

        A vendor balance has no account kind, so `amend_leg` cannot resolve it
        and it was left on `"update"` -- which takes its direction from whether
        the figure rose. Paying a bill SUBTRACTS from what the vendor is owed,
        so raising a payment 100 -> 150 added 50 to the vendor while the A/P leg
        beside it correctly subtracted 50. Twice the delta, the wrong way, on an
        entry that still balanced.
        """
        from supplierio.models import Supplier

        company = Company.objects.create(name="Vendor Books")
        vendor = Supplier.objects.create(
            company=company, first_name="V", display_name="V Ltd",
            opening_balance=Decimal("1000"),
        )

        # What the payment posting does to a vendor: DEBIT means subtract.
        update_opening_balance(vendor, DEBIT, Decimal("100"), 0)
        amend_balance(vendor, DEBIT, Decimal("150"), Decimal("100"))
        vendor.refresh_from_db()

        self.assertEqual(
            Decimal(str(vendor.opening_balance)),
            Decimal("850"),
            "raising a payment must reduce the vendor balance further",
        )

        # And the old op is what it must not do.
        legacy = Supplier.objects.create(
            company=company, first_name="L", display_name="L Ltd",
            opening_balance=Decimal("1000"),
        )
        update_opening_balance(legacy, DEBIT, Decimal("100"), 0)
        update_opening_balance(legacy, "update", Decimal("150"), Decimal("100"))
        legacy.refresh_from_db()
        self.assertEqual(Decimal(str(legacy.opening_balance)), Decimal("950"))

    def test_the_bill_amend_keeps_the_update_op_and_is_right_to(self):
        """The trap a sweep of this family walks into.

        A bill CREDITS the vendor balance -- the debt goes up -- so the signed
        delta `"update"` computes is already the correct rule. Changing both
        sites together inverts the bill path, which is the mistake
        `SUPPLIER_GAPS.md` D8 warns about by name.
        """
        source = self.source()
        supplier_updates = [
            i + 1
            for i, line in enumerate(source.splitlines())
            if '"update",' in line
            and not line.strip().startswith("#")
            and "supplier" in "\n".join(
                source.splitlines()[max(0, i - 4):i]
            ).lower()
        ]
        self.assertEqual(
            len(supplier_updates), 1,
            "expected exactly one supplier balance still on 'update' (the bill "
            f"amend); found {len(supplier_updates)} at lines {supplier_updates}",
        )

        # And it must still be the BILL path, not the payment path.
        window = "\n".join(
            source.splitlines()[supplier_updates[0] - 12:supplier_updates[0]]
        )
        self.assertIn("is_bill", window)
