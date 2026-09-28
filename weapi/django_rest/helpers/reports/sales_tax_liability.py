"""Sales Tax Liability report builder.

Builds the report described in
``docs/updated-prompts/Sales_Tax_Liability_Report_Documentation.md``: sales tax
collected/owed, grouped by **tax agency**, broken into the **rate components**
that make up each agency (state / county / city / district), with Gross total,
Non-taxable, Taxable amount, and Tax amount per component. The agency total sums
the **Tax Amount only** (the same sales are taxed by several overlapping
components, so summing Gross/Taxable would multi-count them).

Model chain (agencyio): ``SaleItem.tax`` -> ``AgencyTax``; an ``AgencyTax`` has
many ``AgencyTaxSet`` rate components (reverse ``tax_groups``), each with a
percent ``rate``, a ``nickname``, and an ``agency`` FK. For a component, the
Gross/Non-taxable/Taxable base is its parent ``AgencyTax``'s sales in the period
(``SaleItem.total`` split by ``is_tax``), and Tax = Taxable x rate/100.

Documented choices (the spec only gives final figures; the *pure* assembler is
unit-tested against them):
  * Accrual basis only (``Sale.date`` / ``CreditNote.date``); cash basis is not
    cleanly derivable and is out of scope.
  * Refund receipts (``Sale.kind=REFUND``) and sales credit memos
    (``CreditNoteItem`` on a kind=SALE ``CreditNote``) net **negative** into the
    base and tax.
  * Tax = Taxable x rate/100 computed from the period base. The filed return can
    differ by a cent or two because tax is rounded per transaction at sale time
    (doc section 5.2); this report does not re-derive per-transaction rounding.
  * A credit-memo line is treated as taxable when it carries a tax FK
    (``CreditNoteItem`` has no ``is_tax`` flag).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from agencyio.models import AgencyTaxSet

from creditnoteio.choices import CreditNoteItemStatusChoices, CreditNoteKindChoices, CreditNoteStatusChoices
from creditnoteio.models import CreditNoteItem

from django.db.models import Q

from salesio.choices import SaleItemStatusChoices, SaleReceptKindChoices
from salesio.models import SaleItem

from weapi.django_rest.helpers.dashboard.finance import LIVE_SALE_STATUSES

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def _money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _agencytax_overview(company, start_date, end_date):
    """Return ``{agencytax_id: {gross, taxable, non_taxable}}`` (Decimals) for the
    period, netting invoices/sales-receipts (+) and refund receipts + sales credit
    memos (-)."""
    overview = defaultdict(
        lambda: {"gross": ZERO, "taxable": ZERO, "non_taxable": ZERO}
    )

    sale_items = (
        SaleItem.objects.filter(
            sale__company=company,
            tax__isnull=False,
            sale__status__in=LIVE_SALE_STATUSES,
        )
        .filter(Q(sale__is_invoice=True) | Q(sale__is_sale_receipt=True))
        .exclude(status=SaleItemStatusChoices.REMOVED)
        .select_related("sale")
    )
    if start_date:
        sale_items = sale_items.filter(sale__date__gte=start_date)
    if end_date:
        sale_items = sale_items.filter(sale__date__lte=end_date)
    for item in sale_items:
        sign = -1 if item.sale.kind == SaleReceptKindChoices.REFUND else 1
        amount = _money(item.total) * sign
        entry = overview[item.tax_id]
        entry["gross"] += amount
        if item.is_tax:
            entry["taxable"] += amount
        else:
            entry["non_taxable"] += amount

    credit_items = (
        CreditNoteItem.objects.filter(
            credit_note__company=company,
            credit_note__kind=CreditNoteKindChoices.SALE,
            tax__isnull=False,
        )
        .exclude(credit_note__status=CreditNoteStatusChoices.REMOVED)
        .exclude(status=CreditNoteItemStatusChoices.REMOVED)
    )
    if start_date:
        credit_items = credit_items.filter(credit_note__date__gte=start_date)
    if end_date:
        credit_items = credit_items.filter(credit_note__date__lte=end_date)
    for item in credit_items:
        amount = -_money(item.total)
        entry = overview[item.tax_id]
        entry["gross"] += amount
        entry["taxable"] += amount  # credit-memo line with a tax FK => taxable
    return overview


def assemble_liability(component_rows, as_of):
    """Pure: group component rate rows by agency; the agency total sums Tax only
    (Gross/Non-taxable/Taxable are intentionally not summed -- they would
    multi-count the shared base across overlapping rates). Kept ORM-free so the
    agency totals are unit-testable against the worked example."""
    agencies = {}
    grand_total = ZERO
    for row in component_rows:
        agency = agencies.setdefault(
            row["agency_uid"],
            {"agency_uid": row["agency_uid"], "agency": row["agency"], "rows": [], "_tax": ZERO},
        )
        tax = _money(row["tax"])
        agency["rows"].append(
            {
                "name": row["name"],
                "gross_total": float(_money(row["gross"])),
                "non_taxable": float(_money(row["non_taxable"])),
                "taxable_amount": float(_money(row["taxable"])),
                "tax_amount": float(tax),
            }
        )
        agency["_tax"] += tax
        grand_total += tax

    out = []
    for agency in sorted(agencies.values(), key=lambda a: (a["agency"] or "").lower()):
        out.append(
            {
                "agency_uid": agency["agency_uid"],
                "agency": agency["agency"],
                "rows": agency["rows"],
                "tax_total": float(agency["_tax"]),
            }
        )
    return {"as_of": as_of.isoformat(), "agencies": out, "total": float(grand_total)}


def sales_tax_liability(company, as_of=None, start_date=None, end_date=None):
    """Build the full Sales Tax Liability report for ``company`` (accrual basis)."""
    as_of = as_of or date.today()
    overview = _agencytax_overview(company, start_date, end_date)

    components = AgencyTaxSet.objects.filter(
        agency__company=company
    ).select_related("agency", "taxes")

    rows = []
    for component in components:
        base = overview.get(component.taxes_id)
        if base is None:
            continue  # this AgencyTax had no activity in the period
        if base["gross"] == ZERO and base["taxable"] == ZERO and base["non_taxable"] == ZERO:
            continue
        rate = Decimal(component.rate or 0)
        rows.append(
            {
                "agency_uid": str(component.agency.uid),
                "agency": component.agency.title or component.agency.state or "",
                "name": component.nickname or "",
                "gross": base["gross"],
                "non_taxable": base["non_taxable"],
                "taxable": base["taxable"],
                "tax": _money(base["taxable"] * rate / HUNDRED),
            }
        )
    return assemble_liability(rows, as_of)
