"""Human labels for `PayrollSalaryComponent.payroll_type`.

Components store an engine code (`FEDERAL_INCOME_TAX`, `SOCIAL_SECURITY_EMPLOYER`,
`NY_RSF`), while reports have to print what a payroll clerk recognizes
("Federal Income Tax", "NY SUI Employer"). Deduction and contribution rows are
different again — those are free text a user typed ("Vision Plan"), so they pass
through untouched.

`tax_center_rollup._employment_line_label` does a narrower version of this for
employer employment taxes only. This module covers every category; the two
should converge, but the Tax Center's wording is load-bearing for filings, so
that one is deliberately left alone for now.
"""

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    normalize_us_state,
)


# Codes whose wording is not derivable from the code itself.
_EXPLICIT_LABELS = {
    # Federal
    "FEDERAL_INCOME_TAX": "Federal Income Tax",
    "SOCIAL_SECURITY": "Social Security",
    "SOCIAL_SECURITY_EMPLOYER": "Social Security Employer",
    "MEDICARE": "Medicare",
    "MEDICARE_EMPLOYER": "Medicare Employer",
    "MEDICARE_ADDITIONAL": "Medicare Additional",
    "FUTA_EMPLOYER": "FUTA Employer",
    # New York. RSF *is* the Re-employment Service Fund -- the report prints the
    # plain-English name, which is why the code alone can't produce it.
    "NY_RSF": "NY Re-employment",
    "NY_REEMPLOYMENT_TAX": "NY Re-employment",
    "NY_SUI_EMPLOYER": "NY SUI Employer",
    "NYS_UI_EMPLOYER": "NY SUI Employer",
    "NYS_EMPLOYMENT_TAXES": "NY Employment Taxes",
    "NYS_INCOME_TAX": "NY Income Tax",
    # Minnesota
    "MN_UI_EMPLOYER": "MN UI Employer",
    "MN_WORKFORCE_DEVELOPMENT_FEE": "MN Workforce Development Fee",
    "MN_ADDITIONAL_ASSESSMENT": "MN Additional Assessment",
    "MN_PAID_LEAVE": "MN Paid Leave",
    "MN_PAID_LEAVE_EMPLOYER": "MN Paid Leave Employer",
    # Seen in production with the state prefix missing -- the generic
    # "{ST}_INCOME_TAX" builder ran without a resolvable state. Labelling it
    # generically beats printing a leading underscore on a customer's report.
    "_INCOME_TAX": "State Income Tax",
}

# Tokens that must not be title-cased back down to "Sui" / "Futa".
_ACRONYMS = {
    "FUTA",
    "SUTA",
    "SUI",
    "UI",
    "SDI",
    "FLI",
    "PFL",
    "HSA",
    "FSA",
    "RSF",
    "EE",
    "ER",
    "SS",
    "401K",
}


def component_label(payroll_type):
    """Return the printable name for a component's `payroll_type`.

    Unknown codes fall back to a title-cased expansion that keeps state codes
    and payroll acronyms upper-case, so a state added tomorrow still reads
    correctly without a code change here.
    """
    if not payroll_type:
        return ""

    raw = str(payroll_type).strip()
    if raw in _EXPLICIT_LABELS:
        return _EXPLICIT_LABELS[raw]

    # Free-text deduction/contribution names ("Vision Plan", "Loan On Land")
    # are already display strings -- only engine codes are SCREAMING_SNAKE.
    if "_" not in raw and raw != raw.upper():
        return raw

    words = []
    for index, token in enumerate(raw.split("_")):
        if not token:
            continue
        upper = token.upper()
        if upper in _ACRONYMS:
            words.append(upper)
        elif index == 0 and normalize_us_state(upper):
            words.append(upper)
        else:
            words.append(token.capitalize())
    return " ".join(words)


# Abbreviations for the details report, whose per-run rows sit in narrow cells.
# Its Total row still spells names out in full, so both forms are needed.
_SHORT_LABELS = {
    "FEDERAL_INCOME_TAX": "FIT",
    "SOCIAL_SECURITY": "SS",
    "SOCIAL_SECURITY_EMPLOYER": "SS",
    "MEDICARE": "Med",
    "MEDICARE_EMPLOYER": "Med",
    "MEDICARE_ADDITIONAL": "Med Addl",
    "FUTA_EMPLOYER": "FUTA",
    "NY_RSF": "NY Re-emp",
    "NY_REEMPLOYMENT_TAX": "NY Re-emp",
    "NY_SUI_EMPLOYER": "NY SUI",
    "NYS_UI_EMPLOYER": "NY SUI",
    "NYS_INCOME_TAX": "NY IT",
    "NYS_EMPLOYMENT_TAXES": "NY Emp",
    "MN_UI_EMPLOYER": "MN UI",
    "MN_WORKFORCE_DEVELOPMENT_FEE": "MN WDF",
    "MN_ADDITIONAL_ASSESSMENT": "MN Addl",
    "MN_PAID_LEAVE": "MN PL",
    "MN_PAID_LEAVE_EMPLOYER": "MN PL",
    "_INCOME_TAX": "State IT",
    "Salary": "Sal",
}

# Suffixes dropped in the short form: the column already says whose cost it is,
# so "Social Security Employer" in the employer column is just "SS".
_SHORT_SUFFIXES = (("_INCOME_TAX", " IT"), ("_UI_EMPLOYER", " SUI"))


def component_short_label(payroll_type):
    """A compact label for the details report's per-run rows.

    Falls back to the full label rather than truncating -- a clipped name is
    worse than a long one, and an unrecognized code is usually a company's own
    deduction name that is already short.
    """
    if not payroll_type:
        return ""

    raw = str(payroll_type).strip()
    if raw in _SHORT_LABELS:
        return _SHORT_LABELS[raw]

    # "{ST}_INCOME_TAX" -> "{ST} IT", "{ST}_UI_EMPLOYER" -> "{ST} SUI", for any
    # state not spelled out above.
    for suffix, short in _SHORT_SUFFIXES:
        if raw.endswith(suffix):
            state = raw[: -len(suffix)]
            if normalize_us_state(state):
                return f"{state.upper()}{short}"

    return component_label(raw)
