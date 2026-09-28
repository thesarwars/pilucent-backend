from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


def _as_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter
def report_money(value):
    """Render a report figure as currency: `-$16,847.87`.

    The minus sits outside the symbol, the way payroll reports print a
    withholding. Values arrive as plain 2dp strings from the report builder --
    `floatformat` would drop the thousands separators and `intcomma` is not
    installed, so the grouping is done here.
    """
    amount = _as_decimal(value)
    if amount is None:
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


@register.filter
def report_number(value):
    """Render a report figure with grouping but no symbol: `-1,300.00`.

    Line-level cells (quantity, price, amount) print bare; only total rows
    carry the currency symbol -- see the sales detail references.
    """
    amount = _as_decimal(value)
    if amount is None:
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,.2f}"


@register.filter
def report_hours(value):
    """Render an hours figure: `173.33h`."""
    amount = _as_decimal(value)
    if amount is None:
        return value
    return f"{amount:,.2f}h"