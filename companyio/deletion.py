"""Permanently deleting a tenant, ledger and all.

WHAT STOPS AN ORDINARY DELETE
-----------------------------

`Company` is the CASCADE root for 77 models, so deleting one reaches the chart
of accounts, sales, purchases and credit notes. Every ledger leg hanging off
those raises, because all four `PROTECT` foreign keys in this schema live on
`JournalEntryConnector`::

    account            -> accounts.ChartOfAccount
    saleitem           -> salesio.SaleItem
    purchase_item      -> purchaseio.PurchaseItem
    credit_note_item   -> creditnoteio.CreditNoteItem

PROTECT fires even when the protecting rows are inside the same cascade, which
is deliberate (journalio/models.py:161) -- it is what keeps a company delete
from silently taking the books with it. That is the "Cannot delete Companiess"
wall in the Django admin, and it is doing its job.

WHY THIS EXISTS ANYWAY
----------------------

Soft-remove is the product's answer. `AdminCompanyRetrieve.perform_destroy` was
changed from a hard delete to `status = REMOVED` for exactly this reason, and
the workspace switcher, console totals and company list all treat REMOVED as
gone. Anything reachable by a tenant should keep going through that path.

The Django admin is not that path. It stands in for a database GUI, where a
delete is expected to be final -- clearing out test signups and junk fixtures
that should never have had books in the first place. This module is what makes
that possible, by tearing the ledger down explicitly and in order rather than
letting a cascade do it: connectors first, so nothing is left half-deleted, then
the companies themselves.

The distinction matters. A cascade into `JournalEntryConnector` deletes some
legs and leaves `JournalEntry` -- which has no FK to an account or a line item --
holding the rest, so the books end up permanently unbalanced with nothing
recording why. Deleting whole connectors first, then letting the entries go with
their company, leaves nothing behind to be inconsistent.

**This is irreversible and it destroys accounting records.** Callers dry-run
first; `purge_companies` prints the leg count before it will write.
"""

from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import Collector

from common.deletion import do_nothing_as_cascade

from journalio.models import JournalEntryConnector


# Every route from a company to a ledger leg. `JournalEntryConnector` carries no
# company FK of its own, so each PROTECT relation is reached through its own
# parent. `journal` and `account` cover ordinary posting; the three line-item
# paths catch legs whose journal was already detached.
LEDGER_PATHS = (
    "journal__company__in",
    "account__company__in",
    "saleitem__sale__company__in",
    "purchase_item__purchase__company__in",
    "credit_note_item__credit_note__company__in",
)


def ledger_legs(companies):
    """Every `JournalEntryConnector` belonging to `companies`, by any route."""
    lookup = Q()
    for path in LEDGER_PATHS:
        lookup |= Q(**{path: companies})
    return JournalEntryConnector.objects.filter(lookup).distinct()


def count_ledger_legs(companies):
    return ledger_legs(companies).count()


def purge_companies(companies):
    """Delete `companies` permanently, ledger included.

    Returns `(total_deleted, per_model_counts)` the way `QuerySet.delete()`
    does. Runs in one transaction: either the whole tenant goes or none of it.
    """
    with transaction.atomic():
        # Whole connectors, never a cascade into them -- a partial delete leaves
        # JournalEntry holding the remaining legs, permanently unbalanced.
        # `.distinct()` cannot be deleted directly, hence the pk round-trip.
        leg_ids = list(ledger_legs(companies).values_list("pk", flat=True))
        deleted = {}
        if leg_ids:
            _, per_model = JournalEntryConnector.objects.filter(
                pk__in=leg_ids
            ).delete()
            deleted.update(per_model)

        targets = list(companies)
        if not targets:
            return sum(deleted.values()), deleted

        # DO_NOTHING edges are made traversable so the cascade does not die at
        # COMMIT on a constraint Django declined to walk. LEDGER_GUARDED still
        # holds -- the connectors are already gone, deleted outright above.
        with do_nothing_as_cascade():
            collector = Collector(using="default", origin=targets)
            collector.collect(targets)
            total, per_model = collector.delete()

        for label, count in per_model.items():
            deleted[label] = deleted.get(label, 0) + count
        return sum(deleted.values()), deleted
