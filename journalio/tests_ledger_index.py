"""The composite index the register's balance column depends on.

`ledger_balance_subquery` computes each row's balance as a correlated subquery:
for every row, sum every leg of the same account up to and including it, ordered
by `(date, id)`. That is the right answer under any filter -- a window function
is evaluated after WHERE and restarts when the view filters -- but it costs one
lookup per row instead of one pass per page.

`JournalEntryConnector` declared no `Meta` at all and carried no index beyond the
implicit FK ones, so each of those lookups scanned the account's whole history:
ten full scans for a ten-row page. The index is what makes the correct answer
affordable.

Two things here are drift guards rather than assertions about behaviour, because
both failure modes are silent:

* the index disappearing, which costs performance and nothing else visible
* `Meta` being rewritten as a bare `class Meta`, which would drop the inherited
  `ordering` and change the default order of every unordered query on the ledger
"""

from django.test import TestCase

from common.models import BaseModelWithUID

from journalio.models import JournalEntryConnector


class LedgerIndexTests(TestCase):
    def test_the_account_date_id_index_exists(self):
        names = {index.name for index in JournalEntryConnector._meta.indexes}
        self.assertIn("jec_account_date_id_idx", names)

    def test_it_covers_account_then_date_then_id_in_that_order(self):
        """Order matters: the subquery filters `account`, then ranges on
        `(date, id)`. Any other column order stops serving it."""
        index = next(
            i
            for i in JournalEntryConnector._meta.indexes
            if i.name == "jec_account_date_id_idx"
        )
        self.assertEqual(index.fields, ["account", "date", "id"])

    def test_the_tie_break_column_is_in_the_index(self):
        """`id` is not decoration. Two legs sharing a date have no other stable
        order, and a running balance without one is undefined."""
        index = next(
            i
            for i in JournalEntryConnector._meta.indexes
            if i.name == "jec_account_date_id_idx"
        )
        self.assertEqual(index.fields[-1], "id")


class MetaInheritanceTests(TestCase):
    """Adding `Meta` to this model is a trap, so it is guarded.

    The model had no `Meta` and inherited one from `BaseModelWithUID`. A bare
    `class Meta:` added for the index would have silently dropped
    `ordering = ("-created_at",)` -- Django only inherits a parent's Meta when
    the child does not declare its own. Nothing would have failed; every
    unordered query on the ledger would just have started coming back in a
    different order, including inside the register's sibling prefetch, which
    overrides that ordering on purpose.
    """

    def test_the_inherited_ordering_survived(self):
        self.assertEqual(
            JournalEntryConnector._meta.ordering,
            BaseModelWithUID.Meta.ordering,
        )
        self.assertEqual(JournalEntryConnector._meta.ordering, ("-created_at",))

    def test_the_model_is_still_concrete(self):
        """Django sets `abstract = False` on an inherited Meta. If that ever
        stopped being true the table would vanish, so it is worth stating."""
        self.assertFalse(JournalEntryConnector._meta.abstract)
