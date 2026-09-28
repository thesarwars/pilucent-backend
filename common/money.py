"""Money for the BD modules: `Decimal` in, `Decimal` through, string out.

`docs/employee-profile.md` §9 and §10.1:

* money is an integer paisa or a decimal string on the wire -- never a float;
* rounding happens at **named points only**, documented per computation, and
  never to an intermediate value in a chain.

So there is no general-purpose "round" here. There are two rounding points,
each named for what it produces, and a computation calls one of them at the
step its trace names. Everything between those points is exact `Decimal`.

Stored money uses the house column, `Decimal(19, 3)` (`MONEY_FIELD`).
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_FIELD = {"max_digits": 19, "decimal_places": 3}

ZERO = Decimal("0")
_TAKA = Decimal("1")
_PAISA = Decimal("0.01")


def to_decimal(value):
    """Exact conversion. Floats are refused: by the time a float arrives here
    the damage is already done, and accepting it hides where it came from.

    Accepts `int`, `Decimal`, and strings, including a fraction such as
    `"1/3"` (as a 28-digit `Decimal`; use `apply_rate` to apply one exactly).
    """
    if isinstance(value, bool):
        raise TypeError("A boolean is not an amount.")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError(
            f"Refusing float {value!r}: pass a string or Decimal so no binary "
            "rounding reaches a statutory figure."
        )
    if isinstance(value, str):
        text = value.strip()
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            return to_decimal(numerator) / to_decimal(denominator)
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ValueError(f"Not an amount: {value!r}") from None
    raise TypeError(f"Not an amount: {value!r}")


def apply_rate(amount, rate):
    """`amount × rate`, exactly when the rate is a fraction.

    The rule book states one third as `"1/3"`, not `0.3333`. Multiplying first
    and dividing last keeps a whole-taka amount exact: Tk 900,000 × 1/3 is
    300,000, where 0.3333 gives 299,970.
    """
    amount = to_decimal(amount)
    if isinstance(rate, str) and "/" in rate:
        numerator, denominator = rate.split("/", 1)
        return amount * to_decimal(numerator) / to_decimal(denominator)
    return amount * to_decimal(rate)


def round_to_taka(value):
    """Rounding point: a whole-taka statutory figure (tax, exemption, rebate).

    Half rounds away from zero, which for the non-negative figures it is used
    on matches the front end's `Math.round`.
    """
    return to_decimal(value).quantize(_TAKA, rounding=ROUND_HALF_UP)


def round_to_paisa(value):
    """Rounding point: an amount paid or deducted to the paisa."""
    return to_decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


def money_str(value):
    """Wire format: a decimal string with two places. `None` stays `None`."""
    if value is None:
        return None
    return str(to_decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP))
