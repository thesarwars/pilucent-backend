"""Amounts in words, Bangla numerals and South Asian grouping (doc §10).

Ported from the front end's `words.js` and `i18n.js`, so a figure printed by
the server reads the same as the one on screen.

* Amount in words is generated for **any** amount, in English (South Asian:
  lakh, crore) and in Bangla. The prototype hardcoded two amounts and left
  every other figure blank on a legal document.
* The Bangla 1-99 values are a lookup table, not a composition. Every value
  from 1 to 99 is irregular in Bangla -- 41 is একচল্লিশ, not চল্লিশ + এক.
  The table has not yet been reviewed by a native speaker (`words.js`,
  `verified: false`).
* Bangla numerals are a display transliteration applied after formatting,
  never a separate number path.
* A year is a label, not a quantity: month-year is built from the date, so
  2026 can never come out as 2,026 (§4.5).
"""

from decimal import ROUND_HALF_UP, Decimal

from .money import to_decimal

BN_1_99 = [
    "", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়", "সাত", "আট", "নয়",
    "দশ", "এগারো", "বারো", "তেরো", "চোদ্দ", "পনেরো", "ষোলো", "সতেরো", "আঠারো", "ঊনিশ",
    "বিশ", "একুশ", "বাইশ", "তেইশ", "চব্বিশ", "পঁচিশ", "ছাব্বিশ", "সাতাশ", "আঠাশ", "ঊনত্রিশ",
    "ত্রিশ", "একত্রিশ", "বত্রিশ", "তেত্রিশ", "চৌত্রিশ", "পঁয়ত্রিশ", "ছত্রিশ", "সাঁইত্রিশ", "আটত্রিশ", "ঊনচল্লিশ",
    "চল্লিশ", "একচল্লিশ", "বিয়াল্লিশ", "তেতাল্লিশ", "চুয়াল্লিশ", "পঁয়তাল্লিশ", "ছেচল্লিশ", "সাতচল্লিশ", "আটচল্লিশ", "ঊনপঞ্চাশ",
    "পঞ্চাশ", "একান্ন", "বায়ান্ন", "তিপ্পান্ন", "চুয়ান্ন", "পঞ্চান্ন", "ছাপ্পান্ন", "সাতান্ন", "আটান্ন", "ঊনষাট",
    "ষাট", "একষট্টি", "বাষট্টি", "তেষট্টি", "চৌষট্টি", "পঁয়ষট্টি", "ছেষট্টি", "সাতষট্টি", "আটষট্টি", "ঊনসত্তর",
    "সত্তর", "একাত্তর", "বাহাত্তর", "তিয়াত্তর", "চুয়াত্তর", "পঁচাত্তর", "ছিয়াত্তর", "সাতাত্তর", "আটাত্তর", "ঊনআশি",
    "আশি", "একাশি", "বিরাশি", "তিরাশি", "চুরাশি", "পঁচাশি", "ছিয়াশি", "সাতাশি", "আটাশি", "ঊননব্বই",
    "নব্বই", "একানব্বই", "বিরানব্বই", "তিরানব্বই", "চুরানব্বই", "পঁচানব্বই", "ছিয়ানব্বই", "সাতানব্বই", "আটানব্বই", "নিরানব্বই",
]
EN_1_19 = [
    "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "bn": ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর",
           "অক্টোবর", "নভেম্বর", "ডিসেম্বর"],
}
LANGS = ("en", "bn")
_PAISA = Decimal("0.01")


def _en_under_100(n):
    if n < 20:
        return EN_1_19[n]
    tens, ones = divmod(n, 10)
    return f"{EN_TENS[tens]} {EN_1_19[ones]}" if ones else EN_TENS[tens]


def _en_under_1000(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{EN_1_19[hundreds]} hundred")
    if rest:
        parts.append(_en_under_100(rest))
    return " ".join(parts)


def _bn_under_1000(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(BN_1_99[hundreds] + "শত")
    if rest:
        parts.append(BN_1_99[rest])
    return " ".join(parts)


def integer_words(n, lang="en"):
    """A non-negative whole number in words, grouped crore · lakh · thousand ·
    hundreds. Above 99 crore the crore count is itself spelled out in full."""
    n = int(n)
    if n < 0:
        raise ValueError("integer_words takes a non-negative number; amount_in_words handles the sign.")
    if n == 0:
        return "শূন্য" if lang == "bn" else "zero"
    crore, rest = divmod(n, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1000)
    parts = []
    if lang == "bn":
        if crore:
            parts.append((integer_words(crore, "bn") if crore > 99 else BN_1_99[crore]) + " কোটি")
        if lakh:
            parts.append(BN_1_99[lakh] + " লক্ষ")
        if thousand:
            parts.append(BN_1_99[thousand] + " হাজার")
        if rest:
            parts.append(_bn_under_1000(rest))
        return " ".join(parts)
    if crore:
        parts.append((integer_words(crore, "en") if crore > 99 else _en_under_100(crore)) + " crore")
    if lakh:
        parts.append(_en_under_100(lakh) + " lakh")
    if thousand:
        parts.append(_en_under_100(thousand) + " thousand")
    if rest:
        parts.append(_en_under_1000(rest))
    return " ".join(parts)


def amount_in_words(amount, lang="en"):
    """`Twenty two thousand taka only` / `বাইশ হাজার টাকা মাত্র`.

    The amount is taken to the paisa (half up) first, so 1,234.567 reads as
    one thousand two hundred thirty four taka and fifty seven paisa.
    """
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}.")
    value = to_decimal(amount).quantize(_PAISA, rounding=ROUND_HALF_UP)
    negative = value < 0
    taka, fraction = divmod(abs(value), 1)
    taka, paisa = int(taka), int(fraction * 100)
    if lang == "bn":
        out = integer_words(taka, "bn") + " টাকা"
        if paisa:
            out += f" {BN_1_99[paisa]} পয়সা"
        out += " মাত্র"
        return f"ঋণাত্মক {out}" if negative else out
    out = integer_words(taka, "en") + " taka"
    if paisa:
        out += f" and {_en_under_100(paisa)} paisa"
    out += " only"
    if negative:
        return f"Minus {out}"
    return out[:1].upper() + out[1:]


def both_words(amount):
    """The pair every legal document carries."""
    return {lang: amount_in_words(amount, lang) for lang in LANGS}


def to_bangla_numerals(text):
    """Transliterate ASCII digits. Applied to an already formatted string."""
    return str(text).translate(BN_DIGITS)


def group_south_asian(amount, places=None):
    """`12,34,567` -- the last three digits, then pairs. `places` fixes the
    decimals (half up); by default a whole amount shows none and any other
    shows two, as `words.js` does."""
    value = to_decimal(amount)
    if places is None:
        places = 0 if value == value.to_integral_value() else 2
    value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    text = format(abs(value), "f")
    whole, _, decimals = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        whole = ",".join(pairs + [tail])
    return sign + whole + (f".{decimals}" if decimals else "")


def format_money(amount, lang="en", places=None, symbol=True):
    """`৳ 22,000`, with Bangla digits for `bn`."""
    text = group_south_asian(amount, places)
    if lang == "bn":
        text = to_bangla_numerals(text)
    return f"৳ {text}" if symbol else text


def format_date(value, lang="en"):
    """DD/MM/YYYY (i18n.js), Bangla digits for `bn`. None reads as a dash."""
    if value is None:
        return "—"
    text = f"{value.day:02d}/{value.month:02d}/{value.year:04d}"
    return to_bangla_numerals(text) if lang == "bn" else text


def format_month_year(value, lang="en"):
    """`February 2027` / `ফেব্রুয়ারি ২০২৭` from a date or a `YYYY-MM` string.

    The year is transliterated digit by digit and never grouped (§4.5).
    """
    if isinstance(value, str):
        year, month = value[:4], int(value[5:7])
    else:
        year, month = f"{value.year:04d}", value.month
    if lang == "bn":
        return f"{MONTHS['bn'][month - 1]} {to_bangla_numerals(year)}"
    return f"{MONTHS['en'][month - 1]} {year}"
