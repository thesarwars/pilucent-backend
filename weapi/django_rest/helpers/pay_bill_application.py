"""Applying a Pay Bills payment to the bills it pays, and taking it back off.

`SUPPLIER_GAPS.md` D6. `pay_bills.py` contained no reference to `Purchase` or
`due_total` anywhere: it relieved the A/P control account and the vendor balance
and never touched a bill. So the balance sheet fell while the A/P ageing report
kept showing every bill at full value, and nothing reconciled the two again.

Our own report docstring already admitted it, which is the part worth noticing:
`reports/ap_aging_detail.py` documents the divergence as expected behaviour
rather than as a defect.

**Which bills a payment pays** was the open product question. The answer here is
oldest-first by default, with an explicit allocation accepted when the caller
sends one. Oldest-first because the current request carries no bill selection at
all -- the fix has to work for the payload that exists -- and explicit because
partial payments and vendor credits eventually need a person to decide, and the
serializer should not have to change again when the UI grows checkboxes.

Every function here is paired. A payment that can be made can be amended and
deleted, and each of those has to leave the bills owing exactly what they owed
before -- the standing posting-leg mirror rule, applied to a subledger column
rather than a journal leg.
"""

import logging
from decimal import Decimal

from django.db.models.functions import Coalesce

from purchaseio.models import PayBillApplication

from weapi.django_rest.helpers.dashboard.finance import open_bills_qs

logger = logging.getLogger(__name__)


def open_bills_for(supplier, company):
    """That vendor's unpaid bills, oldest first.

    Built on the same `open_bills_qs` the A/P ageing report and the dashboard
    card use, so "open" means one thing across the product. A payment that
    allocates against a different definition than the report displays would
    reproduce D6 in a subtler form.

    Ordered by the date a bill ages from -- due date, else bill date, else
    document date -- which is the fallback `ap_aging_detail` applies, with the
    row id breaking ties so the order is total and repeatable.
    """
    return (
        open_bills_qs(company)
        .filter(supplier=supplier)
        .annotate(_ages_from=Coalesce("due_date", "bill_date", "date"))
        .order_by("_ages_from", "id")
    )


def resolve_bill_allocations(payload, supplier, company):
    """Read an explicit `bills` allocation off a payee payload, if it sent one.

    Shape: `"bills": [{"purchase_uid": "...", "amount": "500.00"}]`. Omitted, the
    result is empty and `apply_pay_bill_item` falls to oldest-first -- which is
    what every request sends today, because there is no bill picker yet.

    **Scoped to this company AND this vendor.** A `purchase_uid` arrives from the
    client like any other, and an unscoped lookup here would let a payment to one
    vendor pay down another tenant's bill -- the same shape as the supplier
    picker hole `a7a07817` closed. Unknown or out-of-scope uids are dropped
    rather than raising: they fall through to oldest-first, and the payment still
    balances.
    """
    rows = (payload or {}).get("bills") or []
    if not rows:
        return []

    wanted = {}
    for row in rows:
        uid = (row or {}).get("purchase_uid")
        if uid:
            wanted[str(uid)] = row.get("amount")

    if not wanted:
        return []

    bills = {
        str(purchase.uid): purchase
        for purchase in open_bills_for(supplier, company).filter(
            uid__in=list(wanted)
        )
    }

    allocations = []
    for uid, amount in wanted.items():
        purchase = bills.get(uid)
        if purchase is None:
            logger.warning(
                "pay bills: bill %s is not an open bill for supplier %s in "
                "company %s; falling back to oldest-first for that amount",
                uid, getattr(supplier, "pk", None), getattr(company, "pk", None),
            )
            continue
        allocations.append(
            (purchase, amount if amount is not None else purchase.due_total)
        )
    return allocations


def apply_pay_bill_item(item, amount, *, allocations=None):
    """Pay `amount` down against this payee's bills, and record what was paid.

    `allocations` is an optional `[(purchase, amount)]` from the caller. What it
    does not cover falls to oldest-first.

    Returns `(applied, unapplied)`. **Unapplied is not an error.** Paying a
    vendor more than their open bills is a prepayment, and the vendor's own
    balance already carries it; there is simply no bill for that part to name.
    Returning it rather than swallowing it is what lets a caller say so.
    """
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        return Decimal("0"), Decimal("0")

    supplier = item.supplier
    # `PayBillItem` carries no company of its own; the payment does.
    company = item.pay_bill.company
    remaining = amount
    applied = Decimal("0")

    def take(purchase, requested):
        nonlocal remaining, applied
        requested = min(Decimal(str(requested)), remaining)
        if requested <= 0:
            return
        paid = purchase.apply_purchase_payment(requested)
        if not paid:
            return
        PayBillApplication.objects.create(
            company=purchase.company, pay_bill_item=item, purchase=purchase,
            amount=paid,
        )
        # The bill is settled, so say so. Left OPEN, a fully paid bill still
        # reads as outstanding everywhere that filters on status rather than on
        # `due_total`.
        if Decimal(purchase.due_total) <= 0:
            from purchaseio.choices import PurchaseStatus

            purchase.status = PurchaseStatus.COMPLETED
            purchase.save(update_fields=["status"])
        remaining -= paid
        applied += paid

    for purchase, requested in allocations or []:
        if remaining <= 0:
            break
        take(purchase, requested)

    if remaining > 0:
        already = {purchase.pk for purchase, _ in (allocations or [])}
        for purchase in open_bills_for(supplier, company):
            if remaining <= 0:
                break
            if purchase.pk in already:
                continue
            take(purchase, purchase.due_total)

    return applied, remaining


def unapply_pay_bill_item(item):
    """Put back everything this payee line paid down, and forget it did.

    Exact rather than proportional: the applications name the bills and the
    amounts, so an unwind restores what was actually taken even if other
    payments have moved those bills since.
    """
    restored = Decimal("0")
    applications = PayBillApplication.objects.filter(
        pay_bill_item=item
    ).select_related("purchase")

    for application in applications:
        try:
            restored += application.purchase.unapply_purchase_payment(
                application.amount
            )
        except Exception:
            logger.exception(
                "pay bills: failed to unapply %s from purchase %s",
                application.amount, application.purchase_id,
            )

    applications.delete()
    return restored
