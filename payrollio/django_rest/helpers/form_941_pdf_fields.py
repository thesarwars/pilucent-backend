"""
AcroForm layout for ``docs/payroll/f941.pdf`` (2025/2026 revision).

Field names are shared across pages for some widgets (``f1_1[0]`` appears on pages
1–3). Header fields on page 1 use different semantics than the old ``f1_1`` = EIN
digit 1 mapping — see ``resolve_f941_acroform_values``.
"""

from payrollio.django_rest.helpers.form_941_common import money_parts, pdf_field

# Widgets that share a name on multiple pages — only fill page 1 for Part 1 header.
PAGE1_ONLY_FIELD_NAMES = frozenset({"f1_1[0]", "f1_2[0]", "f1_3[0]"})

# Page 1 header (top of form, y >= 550 in PDF coordinates).
HEADER_NAME_LINE1 = pdf_field("f1_3")
HEADER_NAME_LINE2 = pdf_field("f1_4")
HEADER_STREET = pdf_field("f1_5")
HEADER_CITY = pdf_field("f1_6")
HEADER_STATE = pdf_field("f1_7")
HEADER_ZIP = pdf_field("f1_8")
FOREIGN_ADDRESS_FIELDS = (
    pdf_field("f1_9"),
    pdf_field("f1_10"),
    pdf_field("f1_11"),
)

# Part 1 lines 1 and 4 on page 1.
# Line 1 (y=484) is a single wide box with no cents companion.
LINE_1_EMPLOYEE_COUNT = pdf_field("f1_12")
LINE_4_NO_SS_MEDICARE = pdf_field("c1_3")

# Part 1 money fields (page 1, 2026 template).
# For lines 5a-5d each row has TWO column pairs: col1 (wages) at x=216/288, col2 (tax) at x=352.8/424.8.
# For lines 5e+ each row has a single wide dollars box (x=446) and a narrow cents box (x=554).
MONEY_FIELD_PAIRS = {
    "line_2_wages": (pdf_field("f1_13"), pdf_field("f1_14")),
    "line_3_fit": (pdf_field("f1_15"), pdf_field("f1_16")),
    "line_5a_ss_wages": (pdf_field("f1_17"), pdf_field("f1_18")),
    "line_5a_ss_tax": (pdf_field("f1_19"), pdf_field("f1_20")),
    "line_5b_ss_tips_wages": (pdf_field("f1_21"), pdf_field("f1_22")),
    "line_5b_ss_tips_tax": (pdf_field("f1_23"), pdf_field("f1_24")),
    "line_5c_medicare_wages": (pdf_field("f1_25"), pdf_field("f1_26")),
    "line_5c_medicare_tax": (pdf_field("f1_27"), pdf_field("f1_28")),
    "line_5d_add_medicare_wages": (pdf_field("f1_29"), pdf_field("f1_30")),
    "line_5d_add_medicare_tax": (pdf_field("f1_31"), pdf_field("f1_32")),
    "line_5e_ss_med_tax_total": (pdf_field("f1_33"), pdf_field("f1_34")),
    "line_5f_unreported_tips": (pdf_field("f1_35"), pdf_field("f1_36")),
    "line_6_total_before_adj": (pdf_field("f1_37"), pdf_field("f1_38")),
    "line_10_total": (pdf_field("f1_45"), pdf_field("f1_46")),
    "line_12_total_after_credits": (pdf_field("f1_49"), pdf_field("f1_50")),
    "line_14_balance_due": (pdf_field("f1_53"), pdf_field("f1_54")),
    "part2_total_tax": (pdf_field("f2_1"), pdf_field("f2_2")),
}

EIN_DIGITS_META_KEY = "__ein_digits__"

# EIN sub-box layout on page 1 (derived from template field rects).
EIN_PAGE1_LAYOUT = {
    "prefix_boxes": {"field": pdf_field("f1_1"), "count": 2},
    "suffix_boxes": {"field": pdf_field("f1_2"), "count": 7},
}

# Legacy aliases intentionally empty — old client field IDs no longer match the
# 2026 layout. Builder writes directly to the correct AcroForm names.
LEGACY_FIELD_ALIASES = {}
LEGACY_CENTS_ALIASES = {}

EIN_DIGIT_KEYS = tuple(pdf_field(f"f1_{index}") for index in range(1, 10))


def extract_ein_digits(form_data):
    """Collect nine EIN digits for PDF box rendering.

    Primary source: ``__ein_digits__`` set by ``build_form_941_pdf_payload`` from
    ``PayrollGeneralTaxSetting.ein_number``. Legacy fallbacks support old client keys.
    """
    if isinstance(form_data.get(EIN_DIGITS_META_KEY), (list, tuple)):
        digits = [
            str(digit) if digit not in (None, "") else ""
            for digit in form_data[EIN_DIGITS_META_KEY]
        ]
        while len(digits) < 9:
            digits.append("")
        return digits[:9]

    legacy = [str(form_data.get(key) or "").strip() for key in EIN_DIGIT_KEYS]
    # Older clients sent one digit per f1_1…f1_9 key.
    if legacy and all(len(digit) <= 1 for digit in legacy) and sum(
        1 for digit in legacy if digit.isdigit()
    ) >= 7:
        while len(legacy) < 9:
            legacy.append("")
        return legacy[:9]

    prefix = str(form_data.get(pdf_field("f1_1")) or "").strip()
    suffix = str(form_data.get(pdf_field("f1_2")) or "").strip()
    combined = "".join(character for character in prefix + suffix if character.isdigit())
    if combined:
        digits = list(combined[:9])
        while len(digits) < 9:
            digits.append("")
        return digits

    return [""] * 9


def _legacy_ein_keys_used(form_data):
    legacy = [str(form_data.get(key) or "").strip() for key in EIN_DIGIT_KEYS]
    return bool(legacy) and all(len(digit) <= 1 for digit in legacy) and sum(
        1 for digit in legacy if digit.isdigit()
    ) >= 7


def _merge_address_lines(*values):
    parts = []
    for value in values:
        text = str(value or "").strip().strip(",")
        if text and text not in parts:
            parts.append(text)
    return ", ".join(parts)


def remap_legacy_f941_fields(form_data):
    """Translate outdated field keys to the template's real layout."""
    if not form_data:
        return {}

    remapped = dict(form_data)
    ein_digits = extract_ein_digits(remapped)
    remapped[EIN_DIGITS_META_KEY] = ein_digits

    if _legacy_ein_keys_used(form_data):
        for legacy_key in EIN_DIGIT_KEYS:
            remapped.pop(legacy_key, None)

    # Leave page-1 EIN widgets empty; digits are drawn per box at flatten time.
    remapped[pdf_field("f1_1")] = ""
    remapped[pdf_field("f1_2")] = ""

    for legacy_key, target_key in LEGACY_FIELD_ALIASES.items():
        if legacy_key == target_key:
            continue
        if legacy_key in remapped and remapped[legacy_key] not in (None, ""):
            existing = str(remapped.get(target_key) or "").strip()
            incoming = str(remapped[legacy_key]).strip()
            if target_key == HEADER_STREET:
                remapped[target_key] = _merge_address_lines(existing, incoming)
            elif not existing:
                remapped[target_key] = incoming
            remapped.pop(legacy_key, None)

    for legacy_key, target_key in LEGACY_CENTS_ALIASES.items():
        if legacy_key == target_key:
            continue
        if legacy_key in remapped and remapped[legacy_key] not in (None, ""):
            remapped[target_key] = str(remapped[legacy_key]).strip()
            remapped.pop(legacy_key, None)

    # Drop display-only ".00" whole keys when cents sibling exists.
    for _label, (dollars_key, cents_key) in MONEY_FIELD_PAIRS.items():
        dollars = str(remapped.get(dollars_key) or "").strip()
        if "." in dollars:
            whole, _, cents = dollars.partition(".")
            remapped[dollars_key] = whole
            if cents and not remapped.get(cents_key):
                remapped[cents_key] = cents[:2].ljust(2, "0")

    return remapped


def resolve_f941_acroform_values(data):
    """Prepare + remap to values keyed by actual AcroForm names."""
    from payrollio.django_rest.helpers.form_941_builder import prepare_f941_form_data

    prepared = prepare_f941_form_data(data)
    return remap_legacy_f941_fields(prepared)


def clear_foreign_address_fields(payload):
    for field_name in FOREIGN_ADDRESS_FIELDS:
        payload[field_name] = ""


def assign_header_address(payload, address):
    """Map street / city / state / ZIP to page-1 header widgets."""
    city = (address.get("city") or "").strip()
    lines = []
    for part in address.get("lines") or []:
        line = (part or "").strip().rstrip(",")
        if city and line.lower().endswith(city.lower()):
            line = line[: -len(city)].strip().rstrip(",")
        if line:
            lines.append(line)
    payload[HEADER_STREET] = ", ".join(lines)
    payload[HEADER_CITY] = city
    payload[HEADER_STATE] = (address.get("state") or "").strip()[:2]
    payload[HEADER_ZIP] = (address.get("zip") or "").strip()
    clear_foreign_address_fields(payload)


def assign_money_pair(payload, amount, pair_key):
    dollars_key, cents_key = MONEY_FIELD_PAIRS[pair_key]
    whole, cents = money_parts(amount)
    payload[dollars_key] = whole
    payload[cents_key] = cents
