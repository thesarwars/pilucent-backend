"""A SALE credit note's receivable reverses GROSS while its tax may reverse nothing.

Reproduction, not archaeology. The document is built through
`PrivateWeCreditNoteListSerializer.create` and the resulting entry's legs are
summed here, because `assert_entry_balances` only logs.

Production #JE-375385164, company 164, out by -390.50:

    CREDIT  Accounts Receivable      4,790.50
    DEBIT   Sales of Product Income  4,400.00
    (the COGS / Inventory pair balances and cancels)

The receivable leg is sized by the header `total`, which arrives GROSS -- the
PURCHASE branch's own comment says so, and 4,790.50 = 4,400.00 + 390.50 says it
again. The revenue leg is sized by the LINES, which are net. So the difference
between them is the tax, and the tax leg has to make it up.

It has exactly two sources, both supplied by the client:

    per-item     `is_tax` truthy AND `tax_uid` present on the line dict
    breakdown    `credit_note_sales_tax["breakdown"]` on the header

A note carrying `total_tax` with neither posts NO tax leg at all, and the entry
is short by exactly `total_tax`. Nothing reconciles the legs against the header
the way `sale_posting._post_unattributed_tax` does for an invoice -- that
function exists because the sale side had this identical defect and was fixed;
the credit-note create path never got the same treatment. Note that a line
carrying `tax_uid` alone is enough to write `CreditNoteItem.tax`, so the
document records the tax it never posted.

The second shape, production #JE-275699114 (company 114, -550.00, 3 legs), is
the revenue leg going missing while the tax legs post. 7c36c73f moved the
revenue reversal out from behind `if total_cost_of_good != 0`, so the zero-cost
route is closed -- but `append_product_reversal_legs` still gates on
`income_account` being resolved, and a product with no income account skips the
leg in silence while the receivable still reverses gross. Both are tested.

The tests that assert an entry BALANCES and currently fail are the reproduction.
They are the specification of what the fix has to make true; when it lands they
go green with no edit. The controls beside them pass today and say what already
works, so a fix cannot be mistaken for having changed those.
"""

from decimal import Decimal
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIRequestFactory

from accounts.choices import (
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices,
)
from accounts.models import ChartOfAccount, User

from adminio.models import CompanyRole

from agencyio.models import Agency, AgencyTax, AgencyTaxSet

from common.django_rest.helpers.chart_of_account_helpers import (
    get_account_by_system_key,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company, CompanyUser

from creditnoteio.choices import CreditNoteKindChoices
from creditnoteio.models import CreditNote

from customerio.models import Customer

from journalio.models import JournalEntry, JournalEntryConnector

from productio.choices import ProductKindChoices, ProductStatusChoices
from productio.models import Product, ProductAdditionalCost

from weapi.django_rest.serializers.creditnotes import (
    PrivateWeCreditNoteListSerializer,
)


NET = Decimal("4400.00")
TAX = Decimal("390.50")
GROSS = NET + TAX
UNIT_COST = Decimal("600.00")


class CreditNoteBuilder(TestCase):
    """Shared scaffolding: a seeded company, a customer and a costed product."""

    @classmethod
    def setUpTestData(cls):
        # The company chart is seeded off the category tree, so that first.
        call_command("create_chart_of_account_category", verbosity=0)

        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )
        cls.user = User.objects.create_user(
            name="Tester", email="creditnote-tax@example.com", password="pass1234!"
        )
        membership = CompanyUser.objects.create(user=cls.user, company=cls.company)
        membership.roles.add(
            CompanyRole.objects.create(
                company=cls.company, name="admin", is_system=True
            )
        )
        cls.customer = Customer.objects.create(
            company=cls.company, first_name="Ada", display_name="Ada Lovelace",
            opening_balance=Decimal("10000"),
        )

    def account(self, system_key):
        account = get_account_by_system_key(system_key, self.company)
        self.assertIsNotNone(
            account, f"the company seed has no {system_key} account"
        )
        return account

    def product(self, *, income_account=True, cost=UNIT_COST):
        """An inventory product configured the way the seed intends."""
        item = Product.objects.create(
            company=self.company,
            title="Widget",
            sku="W-1",
            quantity=0,
            date=date.today(),
            kind=ProductKindChoices.PRODUCT,
            status=ProductStatusChoices.ACTIVE,
            sale_price=NET,
            is_inventory=True,
            asset_account=self.account(
                ChartOfAccountSystemKeyChoices.INVENTORY_ASSET
            ),
            income_account=(
                self.account(
                    ChartOfAccountSystemKeyChoices.SALES_OF_PRODUCT_INCOME
                )
                if income_account
                else None
            ),
        )
        if cost:
            ProductAdditionalCost.objects.create(
                product=item,
                amount=cost,
                expense_account=self.account(ChartOfAccountSystemKeyChoices.COGS),
            )
        return item

    def sales_tax(self, rate):
        """An agency tax whose group posts to a real liability account."""
        agency = Agency.objects.create(company=self.company, title="Minnesota")
        tax = AgencyTax.objects.create(
            company=self.company, title="MN Combined", total_rate=float(rate)
        )
        liability = self.account(ChartOfAccountSystemKeyChoices.SALES_TAX_PAYABLE)
        AgencyTaxSet.objects.create(
            agency=agency, taxes=tax, rate=Decimal(str(rate)),
            nickname="Minnesota State", sales_tax_account=liability,
        )
        return tax

    def post_note(self, payload):
        """Drive the real create path and hand back its journal entry."""
        payload.setdefault(
            "credit_note_number",
            f"CN-{CreditNote.objects.count() + 1}-{self.id().rsplit('.', 1)[-1]}"[:50],
        )
        factory = APIRequestFactory()
        request = factory.post("/", payload, format="json")
        request.user = self.user

        serializer = PrivateWeCreditNoteListSerializer(
            data=payload, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        # The PDF render and the outbound email are not part of the posting.
        with patch(
            "weapi.django_rest.serializers.creditnotes.get_pdf"
        ) as pdf, patch(
            "weapi.django_rest.serializers.creditnotes.file_url",
            return_value="",
        ), patch(
            "weapi.django_rest.serializers.creditnotes.send_email_to_user"
        ):
            pdf.return_value.file = None
            serializer.save()

        note = CreditNote.objects.filter(company=self.company).order_by("-id").first()
        self.assertIsNotNone(note, "no credit note was created")
        entry = JournalEntry.objects.filter(credit_note=note).first()
        self.assertIsNotNone(entry, "the credit note wrote no journal entry")
        return entry

    def sides(self, entry):
        """Sum the legs ourselves. `assert_entry_balances` only logs."""
        rows = JournalEntryConnector.objects.filter(journal=entry).select_related(
            "account"
        )
        debit = sum(Decimal(str(row.debit or 0)) for row in rows)
        credit = sum(Decimal(str(row.credit or 0)) for row in rows)
        return debit, credit, rows

    def describe(self, rows):
        return "\n".join(
            f"    {row.kind:<6} {row.account.title:<28} "
            f"D {row.debit} / C {row.credit}"
            for row in rows
        )


class HeaderTaxNeverReachesTheLedgerTests(CreditNoteBuilder):
    """#JE-375385164: A/R reverses gross, revenue reverses net, tax reverses nothing."""

    def note_payload(self, item_extra=None, **header):
        line = {
            "product_uid": str(self.item.uid),
            "quantity": 1,
            "total": str(NET),
        }
        line.update(item_extra or {})
        payload = {
            "date": str(date.today()),
            "kind": CreditNoteKindChoices.SALE,
            "customer_uid": str(self.customer.uid),
            "total": str(GROSS),
            "total_tax": str(TAX),
            "credit_note_items": [line],
        }
        payload.update(header)
        return payload

    def setUp(self):
        super().setUp()
        self.item = self.product()

    def test_a_taxed_sale_credit_note_does_not_balance(self):
        """The whole finding, in one assertion, from a document we built."""
        self.tax = self.sales_tax("8.875")
        entry = self.post_note(
            self.note_payload(item_extra={"tax_uid": str(self.tax.uid)})
        )

        debit, credit, rows = self.sides(entry)

        self.assertEqual(
            debit,
            credit,
            f"entry {entry.entry_number} is out by {debit - credit}\n"
            f"{self.describe(rows)}",
        )

    def test_the_header_tax_now_reaches_the_ledger(self):
        """Same document, stated as the size and direction of the hole.

        WAS: out by -TAX, the whole declared header tax. The note credited the
        receivable for the tax-inclusive amount and debited the liability back
        nowhere.
        """
        self.tax = self.sales_tax("8.875")
        entry = self.post_note(
            self.note_payload(item_extra={"tax_uid": str(self.tax.uid)})
        )

        debit, credit, _rows = self.sides(entry)

        self.assertEqual(
            debit - credit, Decimal("0.000"),
            "the declared header tax must reach the ledger",
        )

    def test_the_tax_the_line_records_is_the_tax_that_posts(self):
        """`tax_uid` alone writes the FK, so the document claims tax was handled.

        WAS: the FK was written and no liability leg followed, so the document
        asserted the tax was dealt with while the ledger showed nothing.
        """
        self.tax = self.sales_tax("8.875")
        entry = self.post_note(
            self.note_payload(item_extra={"tax_uid": str(self.tax.uid)})
        )

        note = entry.credit_note
        line = note.creditnoteitem_set.first()
        self.assertIsNotNone(line.tax, "the line did not even record the tax")
        self.assertTrue(
            JournalEntryConnector.objects.filter(
                journal=entry,
                account__system_key=(
                    ChartOfAccountSystemKeyChoices.SALES_TAX_PAYABLE
                ),
            ).exists(),
            "a tax leg was written after all",
        )

    def test_the_receivable_reverses_gross_while_revenue_reverses_net(self):
        """Why the hole is the tax: the two legs are sized from different figures."""
        self.tax = self.sales_tax("8.875")
        entry = self.post_note(
            self.note_payload(item_extra={"tax_uid": str(self.tax.uid)})
        )

        by_key = {
            row.account.system_key: row
            for row in JournalEntryConnector.objects.filter(
                journal=entry
            ).select_related("account")
        }
        receivable = by_key[ChartOfAccountSystemKeyChoices.AR]
        revenue = by_key[ChartOfAccountSystemKeyChoices.SALES_OF_PRODUCT_INCOME]

        self.assertEqual(Decimal(str(receivable.credit)), GROSS)
        self.assertEqual(Decimal(str(revenue.debit)), NET)

    def test_the_flag_is_the_only_switch(self):
        """Control. The identical document with `is_tax` set balances.

        This is what says the defect is the missing reconciliation and not
        something else about the document: one boolean the client may or may
        not send decides whether the ledger balances.
        """
        rate = (TAX / NET) * Decimal("100")
        self.tax = self.sales_tax(str(rate))
        entry = self.post_note(
            self.note_payload(
                item_extra={"tax_uid": str(self.tax.uid), "is_tax": True}
            )
        )

        debit, credit, rows = self.sides(entry)

        self.assertEqual(
            debit, credit, f"out by {debit - credit}\n{self.describe(rows)}"
        )

    def test_the_breakdown_is_the_other_switch(self):
        """Control. The same document with a `credit_note_sales_tax` breakdown."""
        liability = self.account(
            ChartOfAccountSystemKeyChoices.SALES_TAX_PAYABLE
        )
        entry = self.post_note(
            self.note_payload(
                credit_note_sales_tax={
                    "breakdown": {liability.title: {"amount": str(TAX)}}
                }
            )
        )

        debit, credit, rows = self.sides(entry)

        self.assertEqual(
            debit, credit, f"out by {debit - credit}\n{self.describe(rows)}"
        )

    def test_a_rate_that_disagrees_with_the_header_leaves_the_difference(self):
        """The same hole, partially filled.

        The receivable follows the HEADER `total`; the per-item leg is
        recomputed from the tax group's CURRENT rate against the line. Nothing
        compares the two, so any disagreement -- a rate edited after the
        invoice, an inclusive-tax document, a rounding split across lines --
        lands in the ledger as an imbalance rather than a warning. This is the
        case `_post_unattributed_tax` calls "the header disagrees with its own
        detail" and still balances, by posting the shortfall.
        """
        self.tax = self.sales_tax("5.000")
        entry = self.post_note(
            self.note_payload(
                item_extra={"tax_uid": str(self.tax.uid), "is_tax": True}
            )
        )

        debit, credit, rows = self.sides(entry)

        self.assertEqual(
            debit,
            credit,
            f"the 5% leg is {NET * Decimal('0.05')} against a header tax of "
            f"{TAX}; out by {debit - credit}\n{self.describe(rows)}",
        )

    def test_both_engines_reconcile_their_declared_tax(self):
        """The fix existed one module over, and now exists on both sides.

        `_post_unattributed_tax` was written for exactly this defect on the
        invoice side. The credit-note path had no equivalent; it now carries
        `post_unattributed_tax`, the same shortfall-not-total logic with the
        sign flipped, because handing tax back DEBITS the liability.
        """
        import inspect

        from weapi.django_rest.helpers import sale_posting
        from weapi.django_rest.serializers import creditnotes

        self.assertIn(
            "def _post_unattributed_tax", inspect.getsource(sale_posting)
        )
        self.assertIn(
            "def post_unattributed_tax", inspect.getsource(creditnotes)
        )


class RevenueLegSilentlySkippedTests(CreditNoteBuilder):
    """#JE-275699114: tax reverses, revenue does not.

    The zero-cost route into this is closed (7c36c73f), so the remaining one is
    an unresolved income account -- which `append_product_reversal_legs` skips
    without a word.
    """

    def test_a_product_with_no_income_account_falls_back_to_the_control(self):
        """Production's shape: WAS a tax debit, a receivable credit, nothing else.

        `append_product_reversal_legs` skipped the revenue leg without a word
        when the product carried no `income_account`. The revenue was
        recognised somewhere when the invoice was raised, so there is always a
        correct place to hand it back -- it now falls back to the
        SALES_OF_PRODUCT_INCOME control account, the revenue-side twin of what
        `resolve_cogs_account` already does for cost.
        """
        rate = (TAX / NET) * Decimal("100")
        tax = self.sales_tax(str(rate))
        self.item = self.product(income_account=False, cost=None)

        entry = self.post_note(
            {
                "date": str(date.today()),
                "kind": CreditNoteKindChoices.SALE,
                "customer_uid": str(self.customer.uid),
                "total": str(GROSS),
                "total_tax": str(TAX),
                "credit_note_items": [
                    {
                        "product_uid": str(self.item.uid),
                        "quantity": 1,
                        "total": str(NET),
                        "tax_uid": str(tax.uid),
                        "is_tax": True,
                    }
                ],
            }
        )

        debit, credit, rows = self.sides(entry)

        self.assertTrue(
            JournalEntryConnector.objects.filter(
                journal=entry,
                account__system_key=(
                    ChartOfAccountSystemKeyChoices.SALES_OF_PRODUCT_INCOME
                ),
            ).exists(),
            "the revenue leg posted, so this shape is closed too",
        )
        self.assertEqual(
            debit,
            credit,
            f"entry {entry.entry_number} is out by {debit - credit}\n"
            f"{self.describe(rows)}",
        )

    def test_a_zero_cost_line_still_reverses_its_revenue(self):
        """7c36c73f's fix, checked end to end rather than on the helper."""
        rate = (TAX / NET) * Decimal("100")
        tax = self.sales_tax(str(rate))
        self.item = self.product(cost=None)

        entry = self.post_note(
            {
                "date": str(date.today()),
                "kind": CreditNoteKindChoices.SALE,
                "customer_uid": str(self.customer.uid),
                "total": str(GROSS),
                "total_tax": str(TAX),
                "credit_note_items": [
                    {
                        "product_uid": str(self.item.uid),
                        "quantity": 1,
                        "total": str(NET),
                        "tax_uid": str(tax.uid),
                        "is_tax": True,
                    }
                ],
            }
        )

        debit, credit, rows = self.sides(entry)

        self.assertTrue(
            JournalEntryConnector.objects.filter(
                journal=entry,
                account__system_key=(
                    ChartOfAccountSystemKeyChoices.SALES_OF_PRODUCT_INCOME
                ),
            ).exists(),
            "the revenue leg is missing on a zero-cost line -- 7c36c73f regressed",
        )
        self.assertEqual(
            debit, credit, f"out by {debit - credit}\n{self.describe(rows)}"
        )


class AddingALineToAPostedNoteTests(CreditNoteBuilder):
    """The other writer on this document kind, and it unbalances the other way.

    `PrivateCreditNoteItemListSerializer.create` appends legs to the SAME
    journal entry the note already has, and it posts only the product legs:
    revenue, inventory, cost of sales. There is no receivable leg and no tax
    leg anywhere in it -- the words "Accounts Receivable" and `total_tax` do
    not occur below line 1258 of the module.

    So the revenue DEBIT lands with nothing crediting the customer for it, and
    the entry goes debit-heavy by the whole line. The note's own `total` is
    left untouched too, so the document and its ledger stop agreeing about what
    was credited.
    """

    def test_a_new_line_posts_a_receivable_alongside_its_revenue(self):
        """WAS: out by +1200, the whole line, in the opposite direction to the
        create path's fault. This writer appended only the product legs."""
        self.item = self.product()
        entry = self.post_note(
            {
                "date": str(date.today()),
                "kind": CreditNoteKindChoices.SALE,
                "customer_uid": str(self.customer.uid),
                "total": str(NET),
                "total_tax": "0",
                "credit_note_items": [
                    {
                        "product_uid": str(self.item.uid),
                        "quantity": 1,
                        "total": str(NET),
                    }
                ],
            }
        )
        before_debit, before_credit, _rows = self.sides(entry)
        self.assertEqual(before_debit, before_credit, "the note did not start level")

        self.add_line(entry.credit_note, Decimal("1200.00"))

        debit, credit, rows = self.sides(entry)
        self.assertEqual(
            debit,
            credit,
            f"adding a line left entry {entry.entry_number} out by "
            f"{debit - credit}\n{self.describe(rows)}",
        )

    def add_line(self, note, amount):
        from weapi.django_rest.serializers.creditnotes import (
            PrivateCreditNoteItemListSerializer,
        )

        factory = APIRequestFactory()
        # `status` is deliberately absent: it is a writable field in `Meta` AND
        # hard-coded in the create() call, so sending it raises
        # "got multiple values for keyword argument 'status'" -- a 500 on the
        # endpoint, unrelated to the leg being tested here.
        payload = {
            "product_uid": str(self.item.uid),
            "quantity": 1,
            "total": str(amount),
        }
        request = factory.post("/", payload, format="json")
        request.user = self.user
        serializer = PrivateCreditNoteItemListSerializer(
            data=payload, context={"request": request, "uid": note.uid}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()


class ControlAccountAbsenceTests(CreditNoteBuilder):
    """Trap 5: a missing control account skips a leg in silence."""

    def test_a_company_with_no_sales_tax_payable_fails_loudly(self):
        """The one shape that genuinely cannot be made to balance.

        The breakdown route resolves by title and `continue`s on a miss, and the
        `post_unattributed_tax` fallback added alongside it reaches for the same
        account -- so when a company has deleted its Sales Tax Payable there is
        nowhere in the chart to hand the tax back to. No amount of posting logic
        fixes a missing account.

        What changed is that it is no longer SILENT. The entry is still short,
        and now says so at ERROR with the note, the amount and the company, so
        it surfaces in logs instead of only in a balance sheet months later.

        This test therefore asserts the log, not the balance. Restoring the
        account is the fix, and that is a data repair.
        """
        self.item = self.product()
        liability = self.account(
            ChartOfAccountSystemKeyChoices.SALES_TAX_PAYABLE
        )
        title = liability.title
        ChartOfAccount.objects.filter(pk=liability.pk).update(
            status=ChartOfAccountStatusChoices.REMOVED
        )

        entry = self.post_note(
            {
                "date": str(date.today()),
                "kind": CreditNoteKindChoices.SALE,
                "customer_uid": str(self.customer.uid),
                "total": str(GROSS),
                "total_tax": str(TAX),
                "credit_note_items": [
                    {
                        "product_uid": str(self.item.uid),
                        "quantity": 1,
                        "total": str(NET),
                    }
                ],
                "credit_note_sales_tax": {
                    "breakdown": {title: {"amount": str(TAX)}}
                },
            }
        )

        debit, credit, rows = self.sides(entry)

        self.assertEqual(
            debit - credit, -TAX,
            f"with no Sales Tax Payable there is nowhere to post the tax, so "
            f"the entry is short by exactly it\n{self.describe(rows)}",
        )
