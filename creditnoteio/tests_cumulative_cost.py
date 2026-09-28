"""A multi-line sale credit note relieved the cost of every line before it.

`PrivateWeCreditNoteListSerializer.create` accumulated `total_cost_of_good`
across the item loop and passed that running total to
`append_product_reversal_legs` *inside the same loop*. So:

    line 1  posts  cost(1)
    line 2  posts  cost(1) + cost(2)
    line n  posts  cost(1) + ... + cost(n)

A three-line note with line costs 10, 20 and 30 relieved 100 of inventory and
recognised 100 of cost reversal, where the true figure is 60.

The entry balanced the whole time. `append_product_reversal_legs` posts the cost
as a PAIR -- an inventory debit against a cost-of-sales credit of the same figure
-- so both sides were overstated identically and `assert_entry_balances` had
nothing to report. Inventory and cost of sales were both wrong on the face of the
books while every consistency check passed.

The item-level path (`PrivateCreditNoteItemListSerializer.create`) was already
correct: it assigns rather than accumulates, because it handles one line.

The accumulator had no other consumer, so it is gone rather than left looking
purposeful.
"""

from decimal import Decimal

from django.test import TestCase


class CumulativeCostTests(TestCase):
    LINE_COSTS = [Decimal("10"), Decimal("20"), Decimal("30")]

    def test_the_bug_arithmetic(self):
        """What the running total produced, stated once so the fix has a target."""
        running = Decimal("0")
        posted = []
        for cost in self.LINE_COSTS:
            running += cost
            posted.append(running)

        self.assertEqual(posted, [Decimal("10"), Decimal("30"), Decimal("60")])
        self.assertEqual(sum(posted), Decimal("100"))
        self.assertEqual(sum(self.LINE_COSTS), Decimal("60"))

    def test_the_overstatement_grows_with_line_count(self):
        """Two lines overstate by one line; ten lines by far more."""
        def posted_total(costs):
            running, total = Decimal("0"), Decimal("0")
            for c in costs:
                running += c
                total += running
            return total

        flat = [Decimal("10")] * 10
        self.assertEqual(posted_total(flat[:1]), Decimal("10"))
        self.assertEqual(posted_total(flat[:2]), Decimal("30"))
        self.assertEqual(posted_total(flat), Decimal("550"))
        self.assertEqual(sum(flat), Decimal("100"))

    def test_a_single_line_note_was_unaffected(self):
        """Which is why this survived: the common case is correct."""
        running = Decimal("0")
        running += self.LINE_COSTS[0]

        self.assertEqual(running, self.LINE_COSTS[0])

    def test_the_overstated_entry_still_balances(self):
        """Why no check caught it: the cost posts as a matched pair.

        Each line's cost is an inventory DEBIT against a cost-of-sales CREDIT of
        the same figure, so an inflated figure inflates both sides equally.
        """
        for cost in [Decimal("10"), Decimal("30"), Decimal("60")]:
            with self.subTest(cost=cost):
                inventory_debit = cost
                cogs_credit = cost
                self.assertEqual(inventory_debit - cogs_credit, Decimal("0"))


class CallSiteTests(TestCase):
    def source(self):
        import inspect

        from weapi.django_rest.serializers import creditnotes

        return inspect.getsource(creditnotes)

    def test_the_document_path_posts_the_line_cost(self):
        source = self.source()

        self.assertIn("total_cost=credit_cost,", source)

    def test_no_running_total_is_accumulated_in_the_item_loop(self):
        """The accumulator is gone, not merely unused."""
        source = self.source()

        self.assertNotIn("total_cost_of_good += credit_cost", source)
        self.assertNotIn("total_cost=total_cost_of_good,\n                        item=new_item", source)

    def test_the_item_level_path_still_assigns_its_single_line_cost(self):
        """It was already right; the fix must not disturb it."""
        source = self.source()

        self.assertIn("total_cost_of_good = credit_cost", source)
