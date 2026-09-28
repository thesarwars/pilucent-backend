"""
AcroForm layout for ``docs/payroll/f940.pdf`` (2025/2026 revision).

Field positions verified against the blank template and
``docs/940_fillup_quickbooks.pdf``.
"""

from payrollio.django_rest.helpers.form_941_common import money_parts, pdf_field
from payrollio.django_rest.helpers.form_941_pdf_fields import (
    EIN_DIGITS_META_KEY,
    assign_header_address,
    extract_ein_digits,
)

PAGE1_ONLY_FIELD_NAMES = frozenset({"f1_1[0]", "f1_2[0]", "f1_3[0]"})

HEADER_NAME_LINE1 = pdf_field("f1_3")
HEADER_NAME_LINE2 = pdf_field("f1_4")
HEADER_STREET = pdf_field("f1_5")
HEADER_CITY = pdf_field("f1_6")
HEADER_STATE = pdf_field("f1_7")
HEADER_ZIP = pdf_field("f1_8")

LINE_1A_STATE_FIRST = pdf_field("f1_12")
LINE_1A_STATE_SECOND = pdf_field("f1_13")
LINE_1B_MULTI_STATE = pdf_field("c1_6")
LINE_2_CREDIT_REDUCTION = pdf_field("c1_7")

PART6_DESIGNEE_NO = pdf_field("c2_2")

# Part 2–4 money rows: dollars at x≈453.6, cents at x≈554.4 (page 1).
MONEY_FIELD_PAIRS = {
    "line_3_total_payments": (pdf_field("f1_14"), pdf_field("f1_15")),
    "line_4_exempt_payments": (pdf_field("f1_16"), pdf_field("f1_17")),
    "line_5_excess_wages": (pdf_field("f1_18"), pdf_field("f1_19")),
    "line_6_subtotal": (pdf_field("f1_20"), pdf_field("f1_21")),
    "line_7_taxable_futa_wages": (pdf_field("f1_22"), pdf_field("f1_23")),
    "line_8_futa_before_adj": (pdf_field("f1_24"), pdf_field("f1_25")),
    "line_9_adjustment_all_excluded": (pdf_field("f1_26"), pdf_field("f1_27")),
    "line_10_adjustment_some_excluded": (pdf_field("f1_28"), pdf_field("f1_29")),
    "line_11_credit_reduction": (pdf_field("f1_30"), pdf_field("f1_31")),
    "line_12_total_futa_tax": (pdf_field("f1_32"), pdf_field("f1_33")),
    "line_13_deposits": (pdf_field("f1_34"), pdf_field("f1_35")),
    "line_14_balance_due": (pdf_field("f1_36"), pdf_field("f1_37")),
    "line_15a_overpayment": (pdf_field("f1_48"), pdf_field("f1_49")),
}

# Part 5 quarterly liability (page 2).
QUARTER_LIABILITY_PAIRS = {
    "Q1": (pdf_field("f2_1"), pdf_field("f2_2")),
    "Q2": (pdf_field("f2_3"), pdf_field("f2_4")),
    "Q3": (pdf_field("f2_5"), pdf_field("f2_6")),
    "Q4": (pdf_field("f2_7"), pdf_field("f2_8")),
    "line_17_total": (pdf_field("f2_9"), pdf_field("f2_10")),
}


def assign_money_pair(payload, amount, pair_key):
    dollars_key, cents_key = MONEY_FIELD_PAIRS[pair_key]
    whole, cents = money_parts(amount)
    payload[dollars_key] = whole
    payload[cents_key] = cents


def assign_quarter_liability(payload, amount, quarter_key):
    dollars_key, cents_key = QUARTER_LIABILITY_PAIRS[quarter_key]
    whole, cents = money_parts(amount)
    payload[dollars_key] = whole
    payload[cents_key] = cents


def assign_state_abbreviation(payload, state_code):
    state = (state_code or "").strip().upper()[:2]
    payload[LINE_1A_STATE_FIRST] = state[:1]
    payload[LINE_1A_STATE_SECOND] = state[1:2] if len(state) > 1 else ""


def prepare_f940_form_data(data):
    """Normalize payload keys for ``fill_f940_pdf``."""
    if not isinstance(data, dict):
        return {}

    if isinstance(data.get("form_940_fields"), dict):
        data = {**data, **data["form_940_fields"]}

    form_data = {}
    ein_digits_meta = data.get(EIN_DIGITS_META_KEY)

    skip_keys = {
        EIN_DIGITS_META_KEY,
        "summary",
        "form_type",
        "form_940_fields",
        "year",
        "futa_quarters",
        "futa_total",
    }

    for key, value in data.items():
        if key in skip_keys:
            continue
        if key.endswith("[0]") or "[" in key:
            form_data[key] = value
        elif key.startswith(("f1_", "f2_", "c1_", "c2_")):
            form_data[pdf_field(key)] = value
        else:
            form_data[key] = value

    if ein_digits_meta is not None:
        digits = [
            str(digit) if digit not in (None, "") else ""
            for digit in ein_digits_meta
        ]
        while len(digits) < 9:
            digits.append("")
        form_data[EIN_DIGITS_META_KEY] = digits[:9]
    elif EIN_DIGITS_META_KEY not in form_data:
        form_data[EIN_DIGITS_META_KEY] = extract_ein_digits(form_data)

    form_data[pdf_field("f1_1")] = ""
    form_data[pdf_field("f1_2")] = ""
    return form_data
