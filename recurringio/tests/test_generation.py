"""Unit tests for the recurring bill-generation mapping (pure, no DB).

These cover the recurring-specific transformation from template lines to the
``bill_group`` payload; the actual posting is delegated to the already-tested
``MigrationBillCreateService``.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountSystemKeyChoices,
)
from accounts.models import ChartOfAccount
from companyio.models import Company
from currencyio.models import Currency
from purchaseio.models import Purchase
from supplierio.models import Supplier

from recurringio.choices import RecurringLineTypeChoices
from recurringio.services.generation import (
    _build_bill_group,
    _build_check_group,
    _build_estimate_group,
    _build_expense_group,
    _build_invoice_group,
    _due_date_from_terms,
    next_cheque_number,
)
from recurringio.services.totals import compute_totals, line_tax_amount


class _Rel:
    """Stand-in for a related manager exposing ``.all()``."""

    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


def _tax(*rates):
    return SimpleNamespace(tax_groups=_Rel([SimpleNamespace(rate=r) for r in rates]))


def _category(amount, account, tax=None):
    return SimpleNamespace(
        line_type=RecurringLineTypeChoices.CATEGORY,
        amount=Decimal(amount),
        charter_account=account,
        product=None,
        quantity=None,
        rate=None,
        description="cat",
        tax=tax,
    )


def _item(amount, product, quantity, rate, tax=None):
    return SimpleNamespace(
        line_type=RecurringLineTypeChoices.ITEM,
        amount=Decimal(amount),
        charter_account=None,
        product=product,
        quantity=Decimal(quantity),
        rate=Decimal(rate),
        description="item",
        tax=tax,
    )


class TaxTests(SimpleTestCase):
    def test_no_tax_is_zero(self):
        self.assertEqual(line_tax_amount(_category("100", object())), Decimal("0"))

    def test_tax_summed_across_groups(self):
        line = _category("200", object(), tax=_tax(10, 5))
        self.assertEqual(line_tax_amount(line), Decimal("30"))  # 20 + 10

    def test_compute_totals(self):
        lines = [_category("1000", object()), _item("50", object(), 5, 10, tax=_tax(10))]
        subtotal, tax = compute_totals(lines)
        self.assertEqual(subtotal, Decimal("1050"))
        self.assertEqual(tax, Decimal("5"))

    def test_inclusive_tax_is_backed_out_not_added_on_top(self):
        # A 110.00 line at 10% INCLUSIVE is 100.00 + 10.00 = 110.00 total.
        # Computing it exclusively would give 110.00 + 11.00 = 121.00.
        line = _category("110", object(), tax=_tax(10))
        self.assertEqual(line_tax_amount(line, "INCLUSIVE"), Decimal("10"))
        self.assertEqual(line_tax_amount(line), Decimal("11"))  # exclusive default

    def test_inclusive_totals_do_not_inflate_the_document(self):
        lines = [_category("110", object(), tax=_tax(10))]

        subtotal, tax = compute_totals(lines, "INCLUSIVE")
        self.assertEqual(subtotal, Decimal("100"))
        self.assertEqual(subtotal + tax, Decimal("110"))  # what the user typed

        subtotal, tax = compute_totals(lines, "EXCLUSIVE")
        self.assertEqual(subtotal, Decimal("110"))
        self.assertEqual(subtotal + tax, Decimal("121"))  # tax added on top

    def test_no_tax_kind_keeps_historical_exclusive_behaviour(self):
        # None / NO_TAX must not change existing templates' totals.
        lines = [_category("110", object(), tax=_tax(10))]
        self.assertEqual(compute_totals(lines, None), compute_totals(lines, "NO_TAX"))
        self.assertEqual(compute_totals(lines, None), compute_totals(lines))


class BuildBillGroupTests(TestCase):
    """DB-backed: currency is resolved from the company's rate table."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _template(self, **overrides):
        defaults = dict(
            supplier=SimpleNamespace(uid="sup"),
            customer=None,
            tax_kind=None,
            currency_code="USD",
            company=self.company,
            mailing_address="123 Main St",
            memo="monthly",
            warehouse=SimpleNamespace(uid="wh"),
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_maps_category_and_item_lines(self):
        account = SimpleNamespace(uid="acct")
        product = SimpleNamespace(uid="prod")
        lines = [_category("1000", account), _item("50", product, 5, 10, tax=_tax(10))]

        group = _build_bill_group(
            self._template(), lines, bill_date=date(2026, 1, 1), due_date=date(2026, 1, 16)
        )

        self.assertEqual(group["total"], Decimal("1050"))
        self.assertEqual(group["total_tax"], Decimal("5"))
        self.assertEqual(group["bill_number"], "")
        self.assertEqual(group["currency_kind"], "USD")
        self.assertEqual(group["full_billing_address"], "123 Main St")
        self.assertEqual(len(group["lines"]), 2)

        category_line = group["lines"][0]
        self.assertEqual(category_line["line_kind"], "EXPENSE")
        self.assertIs(category_line["expense_account"], account)

        item_line = group["lines"][1]
        self.assertEqual(item_line["line_kind"], "PRODUCT")
        self.assertIs(item_line["product"], product)
        self.assertEqual(item_line["quantity"], Decimal("5"))
        self.assertEqual(item_line["purchase_price"], Decimal("10"))

    def test_currency_falls_back_to_company(self):
        group = _build_bill_group(
            self._template(currency_code=None),
            [_category("10", SimpleNamespace())],
            bill_date=date(2026, 1, 1),
            due_date=None,
        )
        self.assertEqual(group["currency_kind"], "USD")


class BuildExpenseGroupTests(TestCase):
    """DB-backed: currency is resolved from the company's rate table."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _template(self, **overrides):
        defaults = dict(
            supplier=SimpleNamespace(uid="sup"),
            customer=None,
            tax_kind=None,
            payment_account=SimpleNamespace(uid="bank"),
            payment_method=SimpleNamespace(uid="card"),
            currency_code="USD",
            company=self.company,
            memo="software subscription",
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_currency_resolved_from_payee_not_hardcoded(self):
        """A hardcoded rate of 1 would mint a bogus 'EUR @ 1.0' Currency row.

        expense_importer does ``Currency.objects.get_or_create(kind=…,
        exchange_rate=…)`` with whatever it is handed, so the rate has to be
        real before it gets there.
        """
        Currency.objects.create(
            title="Euro", kind="EUR", exchange_rate=Decimal("1.0850"),
            company=self.company,
        )
        supplier = Supplier.objects.create(
            first_name="Ada", display_name="Ada GmbH",
            company=self.company, currency="EUR",
        )

        group = _build_expense_group(
            self._template(supplier=supplier),
            [_category("100", SimpleNamespace())],
            expense_date=date(2026, 1, 1),
        )

        self.assertEqual(group["currency_kind"], "EUR")
        self.assertEqual(group["currency_rate"], Decimal("1.0850"))

    def test_expense_settles_in_full_when_recorded(self):
        # An expense is money already paid. Both at zero left the record saying
        # neither paid nor outstanding.
        group = _build_expense_group(
            self._template(), [_category("99", SimpleNamespace(), tax=_tax(10))],
            expense_date=date(2026, 1, 1),
        )
        self.assertEqual(group["deposit"], group["total"] + group["total_tax"])
        self.assertEqual(group["due_total"], Decimal("0"))

    def test_maps_payment_account_and_lines(self):
        account = SimpleNamespace(uid="acct")
        template = self._template()
        lines = [_category("99", account, tax=_tax(10))]

        group = _build_expense_group(template, lines, expense_date=date(2026, 1, 1))

        self.assertIs(group["payment_account"], template.payment_account)
        self.assertIs(group["payment_method"], template.payment_method)
        self.assertEqual(group["expense_date"], date(2026, 1, 1))
        self.assertEqual(group["total"], Decimal("99"))
        self.assertEqual(group["total_tax"], Decimal("9.9"))
        self.assertNotIn("due_date", group)  # expenses have no due date
        self.assertEqual(group["lines"][0]["line_kind"], "EXPENSE")
        self.assertIs(group["lines"][0]["expense_account"], account)


class BuildCheckGroupTests(TestCase):
    """DB-backed: cheque numbering has to consult numbers already issued.

    The template's ``cheque_number`` is a seed, not a literal — copying it
    verbatim would issue twelve identically-numbered cheques against one bank
    account, silently (nothing on this write path enforces uniqueness).
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="Landlord", display_name="Landlord LLC",
            company=cls.company, currency="USD",
        )
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Checking", company=cls.company
        )
        cls.other_bank = ChartOfAccount.objects.create(
            code="1020", title="Savings", company=cls.company
        )

    def _template(self, **overrides):
        defaults = dict(
            supplier=self.supplier,
            customer=None,
            tax_kind=None,
            payment_account=self.bank,
            company=self.company,
            print_later=False,
            cheque_number="1005",
            currency_code="USD",
            mailing_address="123 Main St",
            memo="rent",
            warehouse=None,
            uid="tpl-1",
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _issue(self, number, account=None):
        """Record a cheque already drawn on an account."""
        return Purchase.objects.create(
            company=self.company,
            supplier=self.supplier,
            charter_account=account or self.bank,
            is_cheque=True,
            cheque_number=number,
            date=date(2026, 1, 1),
        )

    def test_unused_seed_is_used_as_is(self):
        group = _build_check_group(
            self._template(), [_category("1200", SimpleNamespace())],
            check_date=date(2026, 1, 1),
        )
        self.assertIs(group["bank_account"], self.bank)
        self.assertEqual(group["check_number"], "1005")
        self.assertEqual(group["check_date"], date(2026, 1, 1))
        self.assertEqual(group["total"], Decimal("1200"))

    def test_seed_increments_past_numbers_already_issued(self):
        self._issue("1005")
        self._issue("1006")
        self.assertEqual(next_cheque_number(self._template()), "1007")

    def test_increment_preserves_prefix_and_zero_padding(self):
        template = self._template(cheque_number="CHQ-004182")
        self.assertEqual(next_cheque_number(template), "CHQ-004182")
        self._issue("CHQ-004182")
        self.assertEqual(next_cheque_number(template), "CHQ-004183")

    def test_numbers_used_on_another_bank_account_do_not_block(self):
        # A cheque book belongs to an account, not to a company.
        self._issue("1005", account=self.other_bank)
        self.assertEqual(next_cheque_number(self._template()), "1005")

    def test_print_later_defers_number(self):
        template = self._template(print_later=True, cheque_number="1005")
        self.assertEqual(next_cheque_number(template), "")  # assigned at print time

    def test_blank_seed_is_left_for_the_print_queue(self):
        self.assertEqual(next_cheque_number(self._template(cheque_number="")), "")
        self.assertEqual(next_cheque_number(self._template(cheque_number=None)), "")

    def test_seed_without_a_numeric_tail_is_left_unnumbered(self):
        # "DRAFT" cannot be advanced; queueing beats issuing duplicates.
        self.assertEqual(next_cheque_number(self._template(cheque_number="DRAFT")), "")

    def test_template_seed_is_never_mutated(self):
        template = self._template()
        self._issue("1005")
        next_cheque_number(template)
        self.assertEqual(template.cheque_number, "1005")

    def test_currency_resolved_from_payee_at_fire_time(self):
        Currency.objects.create(
            title="Euro", kind="EUR", exchange_rate=Decimal("1.0850"),
            company=self.company,
        )
        self.supplier.currency = "EUR"
        self.supplier.save(update_fields=["currency"])

        group = _build_check_group(
            self._template(), [_category("100", SimpleNamespace())],
            check_date=date(2026, 1, 1),
        )
        self.assertEqual(group["currency_kind"], "EUR")
        self.assertEqual(group["currency_rate"], Decimal("1.0850"))

    def test_currency_rate_falls_back_to_one_when_unknown(self):
        group = _build_check_group(
            self._template(), [_category("100", SimpleNamespace())],
            check_date=date(2026, 1, 1),
        )
        self.assertEqual(group["currency_rate"], Decimal("1"))


class BuildEstimateGroupTests(TestCase):
    """DB-backed: currency is resolved from the company's rate table."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _template(self, **overrides):
        defaults = dict(
            customer=SimpleNamespace(uid="cus", display_name="Acme"),
            supplier=None,
            tax_kind=None,
            expiry_days=None,
            warehouse=None,
            currency_code="USD",
            company=self.company,
            mailing_address="1 Market St",
            memo="Monthly retainer",
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_non_posting_fields_and_totals(self):
        product = SimpleNamespace(uid="prod")
        account = SimpleNamespace(uid="income")
        template = self._template()
        lines = [_item("2000", product, 1, 2000, tax=_tax(8)), _category("100", account)]

        group = _build_estimate_group(template, lines, estimate_date=date(2026, 8, 1))

        self.assertIs(group["customer"], template.customer)
        self.assertEqual(group["estimate_number"], "")  # assigned by EST sequence
        self.assertIsNone(group["term"])                 # estimates carry no terms
        self.assertIsNone(group["expiry_date"])          # not on the template (Phase 1)
        self.assertEqual(group["estimate_date"], date(2026, 8, 1))
        self.assertEqual(group["total"], Decimal("2100"))
        self.assertEqual(group["total_tax"], Decimal("160"))  # 2000 * 8%
        self.assertEqual(group["full_billing_address"], "1 Market St")

    def test_item_and_category_line_shapes(self):
        product = SimpleNamespace(uid="prod")
        account = SimpleNamespace(uid="income")
        lines = [_item("50", product, 5, 10, tax=_tax(10)), _category("100", account)]

        group = _build_estimate_group(self._template(), lines, estimate_date=date(2026, 8, 1))

        item = group["lines"][0]
        self.assertIs(item["product"], product)
        self.assertIsNone(item["income_account"])
        self.assertEqual(item["sale_price"], Decimal("10"))
        self.assertEqual(item["quantity"], Decimal("5"))
        self.assertTrue(item["is_tax"])

        category = group["lines"][1]
        self.assertIsNone(category["product"])
        self.assertIs(category["income_account"], account)
        self.assertEqual(category["sale_price"], Decimal("100"))
        self.assertFalse(category["is_tax"])


class DueDateTests(SimpleTestCase):
    def test_due_date_adds_term_days(self):
        template = SimpleNamespace(terms=SimpleNamespace(days=15))
        self.assertEqual(
            _due_date_from_terms(template, date(2026, 1, 1)), date(2026, 1, 16)
        )

    def test_no_terms_returns_none(self):
        self.assertIsNone(_due_date_from_terms(SimpleNamespace(terms=None), date(2026, 1, 1)))

    def test_bad_term_days_returns_none(self):
        template = SimpleNamespace(terms=SimpleNamespace(days="oops"))
        self.assertIsNone(_due_date_from_terms(template, date(2026, 1, 1)))


class EstimateExpiryAndStoreTests(TestCase):
    """§12 Q1/Q2: expiry is a duration, and the store must reach the estimate."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _template(self, **overrides):
        defaults = dict(
            customer=SimpleNamespace(uid="cus", display_name="Acme"),
            supplier=None, tax_kind=None, expiry_days=None, warehouse=None,
            currency_code="USD", company=self.company,
            mailing_address="1 Market St", memo="quote", auto_email=False,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_expiry_is_relative_to_each_occurrence(self):
        # A frozen absolute date would be meaningless on a template that fires
        # for years -- every occurrence expires N days after its own date.
        template = self._template(expiry_days=30)
        lines = [_item("100", SimpleNamespace(), 1, 100)]

        july = _build_estimate_group(template, lines, estimate_date=date(2026, 7, 1))
        august = _build_estimate_group(template, lines, estimate_date=date(2026, 8, 1))

        self.assertEqual(july["expiry_date"], date(2026, 7, 31))
        self.assertEqual(august["expiry_date"], date(2026, 8, 31))

    def test_no_expiry_days_leaves_the_estimate_open_ended(self):
        group = _build_estimate_group(
            self._template(), [_item("100", SimpleNamespace(), 1, 100)],
            estimate_date=date(2026, 7, 1),
        )
        self.assertIsNone(group["expiry_date"])

    def test_store_reaches_the_generated_estimate(self):
        store = SimpleNamespace(uid="wh")
        group = _build_estimate_group(
            self._template(warehouse=store), [_item("100", SimpleNamespace(), 1, 100)],
            estimate_date=date(2026, 7, 1),
        )
        self.assertIs(group["warehouse"], store)


class DispatchTests(SimpleTestCase):
    """An unwired txn_type must fail loudly, not silently post a bill."""

    def test_unknown_txn_type_raises_instead_of_generating_a_bill(self):
        from recurringio.services.generation import generate_from_template

        template = SimpleNamespace(txn_type="NOT_A_REAL_TYPE")
        with self.assertRaises(ValueError) as ctx:
            generate_from_template(template, None, None)
        self.assertIn("No generator", str(ctx.exception))


class BuildInvoiceGroupTests(TestCase):
    """INVOICE: money inputs reach the document; due date derives from terms."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")

    def _template(self, **overrides):
        defaults = dict(
            customer=SimpleNamespace(uid="cus", display_name="Acme"),
            supplier=None, tax_kind=None, expiry_days=None,
            warehouse=SimpleNamespace(uid="wh"),
            terms=SimpleNamespace(uid="term", days=30),
            payment_account=SimpleNamespace(uid="ar"),
            discount=Decimal("150"), discount_kind="PERCENTAGE",
            shipping_fee=Decimal("25"), deposit=Decimal("100"),
            include_unbilled_charges=False,
            currency_code="USD", company=self.company,
            mailing_address="12 Main St", memo="Thanks", auto_email=False,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _lines(self):
        return [_item("900", SimpleNamespace(), 2, 450, tax=_tax(10))]

    def test_money_inputs_reach_the_invoice(self):
        group = _build_invoice_group(
            self._template(), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )
        self.assertEqual(group["discount"], Decimal("150"))
        self.assertEqual(group["shipping_fee"], Decimal("25"))
        self.assertEqual(group["deposit"], Decimal("100"))
        self.assertIsNotNone(group["receivable_account"])
        self.assertIs(group["warehouse"].uid, "wh")

    def test_receivable_falls_back_to_the_ar_control_account(self):
        """The bug that corrupted production nightly for weeks.

        `receivable_account` is the DEBIT destination for `due_total`. It used
        to be filled from `template.payment_account` -- a different thing
        entirely, which the model documents as "the account money is paid FROM
        ... required for EXPENSE and CHEQUE". An INVOICE template has no reason
        to carry one, and production's single invoice template did not: it
        arrived as None, `invoice_importer.py:323` skipped the whole A/R leg
        behind `if receivable_account:`, and every firing wrote a journal entry
        short by the entire invoice total.
        """
        ar = ChartOfAccount.objects.create(
            title="Accounts Receivable (A/R)", code="1100", company=self.company,
            kind=ChartOfAccountKindChoices.ASSETS,
            system_key=ChartOfAccountSystemKeyChoices.AR,
        )

        group = _build_invoice_group(
            self._template(payment_account=None), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )

        self.assertEqual(group["receivable_account"], ar)

    def test_receivable_resolves_by_system_key_not_title(self):
        """A renamed A/R account still has to be found.

        Resolving control accounts by title is R1, the root cause the
        `system_key` spine exists to close -- and the CSV importer this path
        shares still does it by title.
        """
        ar = ChartOfAccount.objects.create(
            title="Debtors", code="1100", company=self.company,
            kind=ChartOfAccountKindChoices.ASSETS,
            system_key=ChartOfAccountSystemKeyChoices.AR,
        )

        group = _build_invoice_group(
            self._template(payment_account=None), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )

        self.assertEqual(group["receivable_account"], ar)

    def test_an_explicit_account_still_wins(self):
        """Keeps the importer's Undeposited-Funds branch reachable."""
        ChartOfAccount.objects.create(
            title="Accounts Receivable (A/R)", code="1100", company=self.company,
            kind=ChartOfAccountKindChoices.ASSETS,
            system_key=ChartOfAccountSystemKeyChoices.AR,
        )
        chosen = ChartOfAccount.objects.create(
            title="Undeposited Funds", code="1200", company=self.company,
            kind=ChartOfAccountKindChoices.ASSETS,
        )

        group = _build_invoice_group(
            self._template(payment_account=chosen), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )

        self.assertEqual(group["receivable_account"], chosen)

    def test_is_invoice_is_sent_so_the_receivable_posts(self):
        """The sale serializer gates the whole journal block on this flag.

        Without it the invoice is still created and its income and inventory
        legs post, but the accounts-receivable debit never does, leaving the
        entry short by the invoice total. Production had 24 of 24 recurring
        sales missing their A/R leg.
        """
        group = _build_invoice_group(
            self._template(), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )
        self.assertIs(group["is_invoice"], True)
        # due_total is what lands on A/R, so it has to be non-zero as well --
        # the serializer skips the leg when it is 0.
        self.assertGreater(group["due_total"], Decimal("0"))

    def test_totals_follow_the_client_arithmetic(self):
        # tax on line amounts BEFORE discount and shipping:
        # subtotal 900, tax 90; total(ex-tax) = 900 + 25 - 150 = 775;
        # due = 775 + 90 - 100 deposit = 765.
        group = _build_invoice_group(
            self._template(), self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )
        self.assertEqual(group["total"], Decimal("775"))
        self.assertEqual(group["total_tax"], Decimal("90"))
        self.assertEqual(group["due_total"], Decimal("765"))

    def test_due_date_derives_from_terms_per_occurrence(self):
        template = self._template()
        self.assertEqual(
            _due_date_from_terms(template, date(2026, 8, 1)), date(2026, 8, 31)
        )
        self.assertEqual(
            _due_date_from_terms(template, date(2026, 9, 1)), date(2026, 10, 1)
        )

    def test_zero_money_template_posts_plain_totals(self):
        template = self._template(
            discount=Decimal("0"), shipping_fee=Decimal("0"), deposit=Decimal("0"),
        )
        group = _build_invoice_group(
            template, self._lines(), self.company,
            invoice_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
        )
        self.assertEqual(group["total"], Decimal("900"))
        self.assertEqual(group["due_total"], Decimal("990"))


class PurchaseOrderPostingTests(TestCase):
    """A fired PO must be a COMMITMENT, not a liability.

    The live endpoint gates A/P, inventory, account balances and the journal on
    is_bill, but MigrationBillCreateService posts all four unconditionally --
    so reusing it with only the flag flipped (as the spec suggests) would book
    stock and money owed that do not exist.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="Pack", display_name="PackRight", company=cls.company
        )
        cls.account = ChartOfAccount.objects.create(
            code="6100", title="Freight", company=cls.company
        )

    def _template(self, **overrides):
        from recurringio.models import RecurringTemplate, RecurringTemplateLine

        defaults = dict(
            name="Restock", txn_type="PURCHASE_ORDER", template_type="SCHEDULED",
            company=self.company, supplier=self.supplier,
            frequency="MONTHLY", interval_count=1, start_date=date(2026, 1, 1),
            end_type="NONE", next_run_date=date(2026, 1, 1),
            full_shipping_address="Balanzify Inc\n12 Main St",
            shipping_by="FedEx",
        )
        defaults.update(overrides)
        template = RecurringTemplate.objects.create(**defaults)
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="CATEGORY",
            amount="125.50", charter_account=self.account,
        )
        return template

    def test_fired_purchase_order_posts_no_journal_entry(self):
        from journalio.models import JournalEntry
        from recurringio.services.generation import generate_from_template

        before = JournalEntry.objects.count()
        generate_from_template(self._template(), None, self.company)
        self.assertEqual(JournalEntry.objects.count(), before)

    def test_fired_purchase_order_does_not_move_the_expense_account(self):
        from recurringio.services.generation import generate_from_template

        opening = self.account.opening_balance
        generate_from_template(self._template(), None, self.company)
        self.account.refresh_from_db()
        self.assertEqual(self.account.opening_balance, opening)

    def test_fired_purchase_order_is_an_open_non_bill(self):
        from recurringio.services.generation import generate_from_template

        purchase = generate_from_template(self._template(), None, self.company)
        self.assertFalse(purchase.is_bill)   # this is what makes it a PO
        self.assertEqual(purchase.status, "OPEN")
        self.assertIsNone(purchase.due_date)  # nothing is owed yet

    def test_shipping_lands_on_a_shipping_address(self):
        from addressio.models import AddressConnector
        from recurringio.services.generation import generate_from_template

        purchase = generate_from_template(
            self._template(), None, self.company,
            transaction_date=date(2026, 1, 1),
        )
        shipping = AddressConnector.objects.filter(
            purchase=purchase, address__is_shipping=True
        ).first()
        self.assertIsNotNone(shipping)
        self.assertEqual(shipping.address.shipping_by, "FedEx")
        self.assertEqual(shipping.address.shipping_date, date(2026, 1, 1))


class DepositGenerationTests(TestCase):
    """A fired deposit posts through the SAME serializer the manual screen uses."""

    @classmethod
    def setUpTestData(cls):
        from categoryio.models import Category
        from customerio.models import Customer

        cls.company = Company.objects.create(name="Acme")
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Operating", company=cls.company, status="ACTIVE",
            account_type=Category.objects.create(title="Bank", company=cls.company),
        )
        cls.income = ChartOfAccount.objects.create(
            code="4000", title="Income", company=cls.company, status="ACTIVE",
        )
        cls.petty = ChartOfAccount.objects.create(
            code="1050", title="Petty cash", company=cls.company, status="ACTIVE",
        )
        cls.customer = Customer.objects.create(
            first_name="Dana", display_name="Northgate", company=cls.company
        )

    def _template(self, **overrides):
        from recurringio.models import RecurringTemplate, RecurringTemplateLine

        defaults = dict(
            name="Branch deposit", txn_type="DEPOSIT", template_type="SCHEDULED",
            company=self.company, payment_account=self.bank,
            cash_back_account=self.petty, cash_back_amount=Decimal("150"),
            cash_back_memo="Float", memo="Counter takings",
            frequency="MONTHLY", interval_count=1, start_date=date(2026, 1, 1),
            end_type="NONE", next_run_date=date(2026, 1, 1),
        )
        defaults.update(overrides)
        template = RecurringTemplate.objects.create(**defaults)
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="CATEGORY",
            amount=Decimal("1200"), charter_account=self.income,
            customer=self.customer, reference_number="CHK-1", position=0,
        )
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="CATEGORY",
            amount=Decimal("480.50"), charter_account=self.income, position=1,
        )
        return template

    def _fire(self, template):
        from accounts.models import User
        from recurringio.services.generation import generate_from_template

        user = User.objects.create(email="runner@x.test", password="x")
        # The serializer resolves the company off the acting user.
        user.get_active_company = lambda: self.company
        return generate_from_template(
            template, user, self.company, transaction_date=date(2026, 1, 1)
        )

    def test_fired_deposit_carries_its_fund_rows(self):
        from transactionio.models import BankDeposit

        deposit = self._fire(self._template())
        self.assertIsInstance(deposit, BankDeposit)
        self.assertEqual(deposit.bank_chart_of_account, self.bank)
        self.assertEqual(deposit.date, date(2026, 1, 1))
        self.assertEqual(deposit.deposit_items.count(), 2)

    def test_line_payer_and_reference_reach_the_deposit_item(self):
        deposit = self._fire(self._template())
        item = deposit.deposit_items.order_by("reference_number").last()
        self.assertEqual(item.customer, self.customer)
        self.assertEqual(item.reference_number, "CHK-1")

    def test_cash_back_is_carried_onto_the_deposit(self):
        deposit = self._fire(self._template())
        self.assertEqual(deposit.cash_back_amount, Decimal("150.000"))
        self.assertEqual(deposit.cash_back_account, self.petty)

    def test_undeposited_funds_are_not_swept(self):
        # Only the template's own lines are generated (spec 7.3, option a).
        deposit = self._fire(self._template())
        self.assertEqual(deposit.deposit_items.count(), 2)


class RefundReceiptGenerationTests(TestCase):
    """A fired refund posts through the SAME serializer the manual screen uses.

    A refund pays real money OUT of an account, so the spec forbids opening a
    second GL path for it.
    """

    @classmethod
    def setUpTestData(cls):
        from categoryio.models import Category
        from customerio.models import Customer
        from productio.models import Product

        cls.company = Company.objects.create(name="Acme")
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Operating", company=cls.company, status="ACTIVE",
            account_type=Category.objects.create(title="Bank", company=cls.company),
        )
        cls.customer = Customer.objects.create(
            first_name="Dana", display_name="Northgate", company=cls.company
        )
        cls.product = Product.objects.create(
            title="Gold plan", sku="GP-9", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )
        # The live sales path posts against the company's standard accounts;
        # a real company has these seeded.
        for code, title in (
            ("1200", "Accounts Receivable (A/R)"),
            ("2200", "Sales Tax Payable"),
            ("1100", "Undeposited Funds"),
            ("1300", "Inventory Asset"),
        ):
            ChartOfAccount.objects.create(
                code=code, title=title, company=cls.company, status="ACTIVE"
            )

    def _template(self, **overrides):
        from recurringio.models import RecurringTemplate, RecurringTemplateLine

        defaults = dict(
            name="Monthly refund", txn_type="REFUND_RECEIPT",
            template_type="SCHEDULED", company=self.company,
            customer=self.customer, payment_account=self.bank,
            reference_number="CHQ-88", tracking_number="RR-2026-01",
            memo="Refund for the cancelled plan",
            email_to="dana@northgate.example",
            frequency="MONTHLY", interval_count=1, start_date=date(2026, 1, 1),
            end_type="NONE", next_run_date=date(2026, 1, 1),
        )
        defaults.update(overrides)
        template = RecurringTemplate.objects.create(**defaults)
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="ITEM",
            product=self.product, quantity=Decimal("2"), rate=Decimal("50"),
            amount=Decimal("100"), position=0,
        )
        return template

    def _fire(self, template, user=None):
        from accounts.models import User
        from recurringio.services.generation import generate_from_template

        if user is None:
            user = User.objects.create(email="runner@x.test", password="x")
            user.get_active_company = lambda: self.company
            user.get_employee = lambda: None
        return generate_from_template(
            template, user, self.company, transaction_date=date(2026, 1, 1)
        )

    def test_fired_refund_is_a_refund_kind_sale(self):
        sale = self._fire(self._template())
        self.assertEqual(sale.kind, "REFUND")
        self.assertTrue(sale.is_sale_receipt)
        self.assertEqual(sale.customer, self.customer)
        self.assertEqual(sale.date, date(2026, 1, 1))

    def test_money_leaves_the_refund_from_account(self):
        # payable, not receivable -- the opposite direction from a receipt.
        sale = self._fire(self._template())
        self.assertEqual(sale.payable_charter_account, self.bank)

    def test_reference_number_and_memo_carry_over(self):
        sale = self._fire(self._template())
        self.assertEqual(sale.reference_number, "CHQ-88")   # the cheque number
        self.assertEqual(sale.description, "Refund for the cancelled plan")

    def test_receipt_number_is_backend_generated_not_the_templates(self):
        # No sales-side document number is client-supplied in this product, so
        # each occurrence gets its own number rather than reusing the
        # template's -- twelve refunds cannot all be RR-2026-01.
        sale = self._fire(self._template())
        self.assertNotEqual(sale.tracking_number, "RR-2026-01")
        self.assertTrue(sale.tracking_number)

    def test_refund_is_settled_in_full(self):
        sale = self._fire(self._template())
        self.assertEqual(sale.total, Decimal("100.000"))
        self.assertEqual(sale.deposit, Decimal("100.000"))

    def test_fired_refund_has_a_downloadable_pdf(self):
        """The PDF must be attached to the sale, not orphaned in storage.

        The Download action lists files linked by FileItemConnector; a
        generated-but-unlinked PDF is invisible to it (345 of 349 stored PDFs
        were in that state).
        """
        from fileroomio.choices import FileItemConnectorModelKindChoices
        from fileroomio.models import FileItemConnector

        sale = self._fire(self._template())
        linked = FileItemConnector.objects.filter(
            sale=sale, model_kind=FileItemConnectorModelKindChoices.SALE
        ).select_related("file_item")
        self.assertTrue(linked.exists(), "no PDF attached to the fired refund")
        self.assertTrue(linked.first().file_item.file)

    def test_pdf_url_is_not_double_prefixed(self):
        """`.url` is already absolute on S3; prefixing the host mangles it."""
        from common.django_rest.helpers.file_helpers import file_url
        from types import SimpleNamespace

        s3 = SimpleNamespace(url="https://bucket.s3.amazonaws.com/media/x.pdf")
        self.assertEqual(file_url(s3), "https://bucket.s3.amazonaws.com/media/x.pdf")
        self.assertNotIn("https://https", file_url(s3))

    def test_linked_back_to_its_template(self):
        template = self._template()
        sale = self._fire(template)
        self.assertEqual(sale.source_template, template)


class CreditMemoGenerationTests(TestCase):
    """A fired credit memo posts through the same serializer the screen uses."""

    @classmethod
    def setUpTestData(cls):
        from customerio.models import Customer
        from productio.models import Product
        from wirehouseio.models import Warehouse

        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="Ada", display_name="Northwind", company=cls.company
        )
        cls.warehouse = Warehouse.objects.create(title="Main", company=cls.company)
        # A credited product reverses income and inventory, so it needs both
        # accounts -- the manual screen fails the same way without them.
        cls.product = Product.objects.create(
            title="Gold widget", sku="GW-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
            income_account=ChartOfAccount.objects.create(
                code="4100", title="Product income", company=cls.company,
                status="ACTIVE",
            ),
            asset_account=ChartOfAccount.objects.create(
                code="1310", title="Product asset", company=cls.company,
                status="ACTIVE",
            ),
        )
        # The credit-note path posts against the company's standard accounts.
        for code, title in (
            ("1200", "Accounts Receivable (A/R)"),
            ("2000", "Accounts Payable (A/P)"),
            ("2200", "Sales Tax Payable"),
            ("5000", "Cost of Goods Sold (COGS)"),
            ("1300", "Inventory Asset"),
            ("1100", "Undeposited Funds"),
        ):
            ChartOfAccount.objects.create(
                code=code, title=title, company=cls.company, status="ACTIVE"
            )
        # A credited product needs a cost account to reverse COGS against;
        # the manual screen fails the same way without one.
        from productio.models import ProductAdditionalCost

        ProductAdditionalCost.objects.create(
            product=cls.product,
            expense_account=ChartOfAccount.objects.create(
                code="5100", title="COGS - widgets", company=cls.company,
                status="ACTIVE",
            ),
        )

    def _template(self, **overrides):
        from recurringio.models import RecurringTemplate, RecurringTemplateLine

        defaults = dict(
            name="Loyalty credit", txn_type="CREDIT_MEMO",
            template_type="SCHEDULED", company=self.company,
            customer=self.customer, warehouse=self.warehouse,
            memo="Loyalty credit applied", email_to="ada@northwind.co",
            frequency="MONTHLY", interval_count=1, start_date=date(2026, 1, 1),
            end_type="NONE", next_run_date=date(2026, 1, 1),
        )
        defaults.update(overrides)
        template = RecurringTemplate.objects.create(**defaults)
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="ITEM",
            product=self.product, quantity=Decimal("2"), rate=Decimal("150"),
            amount=Decimal("300"), position=0,
        )
        return template

    def _fire(self, template, email="runner@x.test"):
        from accounts.models import User
        from recurringio.services.generation import generate_from_template

        user = User.objects.create(email=email, password="x")
        user.get_active_company = lambda: self.company
        user.get_employee = lambda: None
        return generate_from_template(
            template, user, self.company, transaction_date=date(2026, 1, 1)
        )

    def test_fired_credit_memo_is_a_credit_note(self):
        from creditnoteio.models import CreditNote

        note = self._fire(self._template())
        self.assertIsInstance(note, CreditNote)
        self.assertEqual(note.customer, self.customer)
        self.assertEqual(note.date, date(2026, 1, 1))

    def test_amounts_are_stored_positive(self):
        # Positive on the record, negative in the ledger -- same as the manual
        # screen, which renders money(-total).
        note = self._fire(self._template())
        self.assertEqual(note.total, Decimal("300.000"))
        self.assertGreater(note.total, 0)

    def test_number_is_backend_generated_from_the_shared_sequence(self):
        note = self._fire(self._template())
        self.assertTrue(note.credit_note_number)
        self.assertIn("CN", note.credit_note_number)

    def test_two_occurrences_get_different_numbers(self):
        # Twelve monthly credits cannot share one document number.
        first = self._fire(self._template())
        second = self._fire(self._template(name="Second"), email="runner2@x.test")
        self.assertNotEqual(first.credit_note_number, second.credit_note_number)
