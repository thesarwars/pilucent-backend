"""Working out when a bill is due.

`SUPPLIER_GAPS.md` D12. Terms exist and are wired end to end on the *vendor* --
`TermConnector` carries a supplier FK and the vendor serializer sets it -- and
nothing read them when a bill was built. `due_date` and `term_uid` arrived as
independent client inputs and `Purchase.due_date` is plain nullable, so a bill
raised without one had no due date at all.

That matters twice over. **Standard §7 and §11.13** require every bill to have a
due date, with absent terms meaning due on receipt rather than null. And the A/P
ageing report buckets by due date: `ap_aging_detail` falls back to the bill date
when there is none, so a null due date silently ages a bill from the wrong day
rather than failing.

Two rules, in order:

1. A bill with no term of its own inherits the **vendor's** term. That is what
   setting a term on a vendor is for, and it was doing nothing.
2. A bill with no due date gets one -- term days from the bill's own date, or the
   bill's own date when there is no term. Never null.

**Out of scope, and named so it is not mistaken for done:** `Term` carries
`days` only, so "2/10 net 30" is inexpressible -- no discount percentage, no
discount days. D12 folds that in as a *gap* rather than a defect, and it is a
schema change plus a discount-taking flow, not a due-date calculation.
"""

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


def supplier_term(supplier):
    """The term set on this vendor, if any.

    Nothing read this before, which is the whole of D12's first half.
    """
    if supplier is None:
        return None
    connector = supplier.termconnector_set.select_related("term").first()
    return connector.term if connector else None


def resolve_due_date(*, supplier, term, base_date, due_date=None):
    """When this bill falls due.

    An explicit `due_date` from the client always wins -- a user overriding the
    terms on one bill is ordinary, and silently recomputing it would be worse
    than the gap this closes.

    Returns `(due_date, term)`. The term comes back because a bill that
    inherited its vendor's term should record that it did; otherwise the vendor
    could change terms later and the bill's own due date would no longer be
    explicable from anything stored.
    """
    if term is None:
        term = supplier_term(supplier)

    if due_date is not None:
        return due_date, term

    if base_date is None:
        return None, term

    days = getattr(term, "days", None)
    if days is None:
        # Due on receipt. Standard §7: absent terms are not an absent date.
        return base_date, term

    try:
        return base_date + timedelta(days=int(days)), term
    except (TypeError, ValueError):
        logger.warning(
            "bill terms: term %s has an unusable days value %r; "
            "falling back to due on receipt",
            getattr(term, "pk", None), days,
        )
        return base_date, term
