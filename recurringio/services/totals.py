"""Money helpers shared by the template serializer and the document generators.

Tax defaults to **exclusive** — added on top of the line amount, summed across
the tax code's groups — which is the rule the importers use, so a generated
document's tax matches a manually-entered one.

When the template says ``tax_kind = INCLUSIVE`` the line amount **already
contains** the tax, so it has to be backed out instead of added on top.
Computing it exclusively there inflates the document: a 100.00 line at 10%
inclusive is 90.91 + 9.09, not 100.00 + 10.00.
"""

from decimal import Decimal

INCLUSIVE = "INCLUSIVE"


def _line_tax_rate(line):
    """Combined percentage across the tax code's groups, as a Decimal."""
    total = Decimal("0")
    for group in line.tax.tax_groups.all():
        total += Decimal(str(group.rate))
    return total


def line_tax_amount(line, tax_kind=None):
    """Tax owed on a single template line, or 0 when the line has no tax code.

    ``tax_kind`` is the **document-level** setting from the template. Only
    ``INCLUSIVE`` changes the arithmetic; every other value (including ``None``
    and ``NO_TAX``) keeps the historical exclusive behaviour so existing
    templates are unaffected.
    """
    if not line.tax:
        return Decimal("0")

    base = Decimal(str(line.amount or "0"))
    rate = _line_tax_rate(line)

    if tax_kind == INCLUSIVE:
        # The amount already includes the tax: extract it rather than add it.
        return base * rate / (Decimal("100") + rate)
    return base * rate / Decimal("100")


def compute_totals(lines, tax_kind=None):
    """Return ``(subtotal, tax)`` across ``lines`` as Decimals.

    ``subtotal`` is always the **ex-tax** base, so ``subtotal + tax`` is the
    document total under either tax kind. Under ``INCLUSIVE`` that means the
    line's own amount is split into base and tax rather than grossed up.
    """
    subtotal = Decimal("0")
    tax = Decimal("0")
    for line in lines:
        amount = Decimal(str(line.amount or "0"))
        line_tax = line_tax_amount(line, tax_kind)
        tax += line_tax
        subtotal += amount - line_tax if tax_kind == INCLUSIVE else amount
    return subtotal, tax
