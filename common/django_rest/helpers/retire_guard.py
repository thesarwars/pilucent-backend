"""Retiring a document is a DELETE. It must not be reachable through PATCH.

Every document delete fixed in this codebase does four things: refuse when a
closed reconciliation covers it, reverse the ledger, unwind the allocation
children, and only then set the status to REMOVED. All of that lives in
`perform_destroy`.

None of it runs on a `PATCH`. `status` is in `fields` on all six detail
serializers and in `read_only_fields` on none of them, so
`PATCH {"status": "REMOVED"}` retires the document by writing the column
directly -- skipping the reconciliation guard, the per-document refusals, the
ledger reversal, the inventory restore and the allocation unwind. The document
disappears from every list while its legs stay PUBLISHED and its balances stay
moved, which is the exact defect the delete paths were written to fix.

So the guards that shipped were not protecting anything a determined client
could not walk around. This closes the door: a transition to REMOVED through a
PATCH is refused and names DELETE instead.

Deliberately narrow. It refuses only the transition INTO the retired state, and
only when the document is not already there -- so a payload that echoes back an
already-REMOVED status (a client replaying a GET) is not an error, and every
other status change is untouched.
"""

from rest_framework.serializers import ValidationError


# Every document status enum in this codebase spells the retired state with
# this exact value -- Purchase, PurchasePayment, Sale, SalePaymentReceive,
# CreditNote and StockAdjustment all use `REMOVED = "REMOVED"`. Compared as a
# string so one helper covers all six without importing six enums, which would
# make this module depend on nearly every app.
RETIRED = "REMOVED"


class RetireViaPatchRefused(ValidationError):
    """409-shaped refusal: retire through DELETE, where the unwind lives."""


def assert_not_retiring_by_patch(instance, validated_data, *, document, field="status"):
    """Refuse a PATCH that would retire `instance`.

    `document` is the noun used in the message, and the endpoint named in it is
    always the DELETE for that same document.
    """
    incoming = validated_data.get(field)
    if incoming is None:
        return
    if str(incoming).upper() != RETIRED:
        return
    if str(getattr(instance, field, "") or "").upper() == RETIRED:
        # Already retired; the payload is echoing state back, not changing it.
        return

    raise RetireViaPatchRefused(
        {
            "code": "RETIRE-VIA-DELETE",
            "message": (
                f"A {document} cannot be removed by changing its status. Use "
                "DELETE instead — that is where the ledger reversal, the "
                "reconciliation check and the allocation unwind happen. "
                "Setting the status here would hide the document while leaving "
                "everything it posted on the books."
            ),
            "field": field,
        }
    )
