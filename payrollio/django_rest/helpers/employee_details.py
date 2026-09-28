"""Build the "Employee details" report.

The odd one out among the payroll reports: it describes **employee master data**,
not a pay run, so it takes no date range -- the reference subtitle reads "For all
employees from all locations" with no From/To.

It is also the only one carrying PII, so masking is not cosmetic here:

* **SSN** shows the last four digits only.
* **Date of birth** shows month and day; the year is withheld.
* **Bank accounts** show the last four digits only.

Nothing in the payload contains a full SSN, birth year or account number, so a
cached response or a shared PDF cannot leak them.

Two things the reference shows that this data model does not hold, both surfaced
rather than faked:

* **Hire date** -- there is no such field on ``Employee``. ``confirmation_date``
  is the closest (the employee-create serializer defaults it to the day the
  record was made) with ``offer_date`` behind it. `hire_date_source` on each row
  says which one was used, so a reader can tell a real hire date from a proxy.
* **Time-off categories** -- ``LeaveType.leave_type`` is only ``DAILY``/
  ``HOURLY``; there is no Paid/Sick/Unpaid/Vacation field. Categories are
  inferred from the policy name and left ``null`` when the name does not say,
  because guessing "Paid" for an unpaid policy misstates someone's benefits.
"""

from payrollio.django_rest.helpers.payroll_report_common import (
    ZERO,
    employee_label,
    money,
)


COLUMNS = [
    {"key": "personal_info", "label": "Personal info", "align": "left"},
    {"key": "hire_date", "label": "Hire date", "align": "left"},
    {"key": "work_location", "label": "Work location", "align": "left"},
    {"key": "pay_info", "label": "Pay info", "align": "left"},
    {"key": "tax_info", "label": "Tax info", "align": "left"},
    {"key": "notes", "label": "Notes", "align": "left"},
]

MASK = "...."

# The stored choice labels are misspelled ("Separatley") and predate the IRS
# renaming of "Qualifying Widow" to "Qualifying Surviving Spouse", so the report
# carries its own wording rather than printing a typo on a tax document.
_FILING_STATUS_LABELS = {
    "SINGLE_OR_MARRIED_FILING_SEPARATLEY": "Single or Married Filing Separately",
    "MARRIED_FILING_JOINTLY_OR_QUALIYING_WIDOW": (
        "Married Filing Jointly or Qualifying Surviving Spouse"
    ),
    "HEAD_OF_HOUSHOLD": "Head of household",
    "EXEMPT": "Exempt",
}

_MARITAL_LABELS = {
    "MARRIED": "Married",
    "UN_MARRIED": "Single",
    "UNMARRIED": "Single",
    "DIVORCED": "Divorced",
    "WIDOWED": "Widowed",
}

_FREQUENCY_SUFFIX = {
    "PER_YEAR": "/yr",
    "PER_MONTH": "/mo",
    "PER_WEEK": "/wk",
}

# Only unambiguous names are categorised -- see the module docstring.
_TIME_OFF_CATEGORIES = (
    (("unpaid", "no paid", "non paid", "nonpaid"), "Unpaid"),
    (("sick",), "Sick"),
    (("vacation", "annual"), "Vacation"),
    (("holiday",), "Holiday"),
)


def display_money(value):
    """`"$50,000.00"`.

    Unlike the numeric payroll reports, this one composes display strings
    ("Salary $50,000.00/yr") rather than shipping bare decimals, so the
    grouping belongs here rather than in the renderer.
    """
    return f"${value:,.2f}"


def mask_tail(value, keep=4):
    """`"473497764"` -> `"....7764"`. Empty for anything too short to mask."""
    digits = "".join(character for character in str(value or "") if character.isalnum())
    if len(digits) < keep:
        return ""
    return f"{MASK}{digits[-keep:]}"


def masked_birth_date(date_of_birth):
    """Month and day only -- the year is PII and is withheld.

    Rendered with a literal `yyyy` so the field reads as deliberately masked
    rather than as missing data.
    """
    if not date_of_birth:
        return ""
    return f"{date_of_birth.strftime('%m/%d')}/yyyy"


def _address_line(address):
    if address is None:
        return ""
    street = (address.full_address or address.street or "").strip()
    city = (address.city or "").strip()
    province = (address.province or "").strip()
    postal = (address.postal_code or "").strip()
    locality = ", ".join(part for part in (city, province) if part)
    if postal:
        locality = f"{locality} {postal}".strip()
    return ", ".join(part for part in (street, locality) if part)


def _work_location_line(work_location):
    if work_location is None:
        return ""
    street = (work_location.location_address or "").strip()
    city = (work_location.location_city or "").strip()
    state = (work_location.location_state or "").strip()
    zip_code = (work_location.location_zip or "").strip()
    locality = ", ".join(part for part in (city, state) if part)
    if zip_code:
        locality = f"{locality} {zip_code}".strip()
    return ", ".join(part for part in (street, locality) if part)


def _pair(label, value):
    """A label with its lines.

    `value` is **always a list of strings**, even for a single line. A field
    that is one line today ("Pay method") is several tomorrow, and a payload
    that sometimes types it as a string forces every consumer to branch.
    """
    if isinstance(value, (list, tuple)):
        return {"label": label, "value": [str(line) for line in value]}
    return {"label": label, "value": [str(value)]}


def _pay_rate(employee):
    """"Salary $50,000.00/yr" or "Hourly rate $40.00/hr", or nothing.

    There is no pay-kind field: an hourly employee is one carrying a non-zero
    `total_rate_per_hour`. The reference omits the line entirely for an employee
    with neither, which production also has.
    """
    hourly = money(getattr(employee, "total_rate_per_hour", 0) or 0)
    if hourly > ZERO:
        return _pair("Hourly rate", f"{display_money(hourly)}/hr")

    salary = money(getattr(employee, "total_salary", 0) or 0)
    if salary > ZERO:
        suffix = _FREQUENCY_SUFFIX.get(employee.salary_frequency, "")
        return _pair("Salary", f"{display_money(salary)}{suffix}")
    return None


def _pay_method(banking):
    """Direct deposit with a masked account, else a cheque."""
    if banking is None:
        return _pair("Pay method", "Check")
    tail = mask_tail(banking.bank_account_number)
    return _pair("Pay method", f"DD, {tail}" if tail else "Direct deposit")


def _setup_name(setup):
    """The specific plan name, not its category.

    `title` holds what the user named the plan ("Vision Plan", "HSA"), while
    `deduction_type` is the category it sits under ("Health Insurance"). Reading
    the category labelled three of one employee's plans identically in
    production, so `title` leads and the category is only a fallback.
    """
    if setup is None:
        return ""
    for candidate in (
        getattr(setup, "title", None),
        getattr(setup, "sub_type", None),
        getattr(setup, "deduction_type", None),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return ""


def _amount_lines(rows, amount_field):
    """"<name>: $<amount>" for each row carrying a non-zero amount."""
    lines = []
    for row in rows:
        amount = money(getattr(row, amount_field, 0) or 0)
        if amount <= ZERO:
            continue
        name = _setup_name(row.deduction_and_contribution)
        lines.append(f"{name}: {display_money(amount)}" if name
                     else display_money(amount))
    return lines


def time_off_category(policy_name):
    lowered = (policy_name or "").lower()
    for keywords, category in _TIME_OFF_CATEGORIES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def _time_off_lines(allocations):
    """"<Category>: <policy>", or the bare policy when the name does not say."""
    lines = []
    seen = set()
    for allocation in allocations:
        leave_type = allocation.leave_type
        name = (
            getattr(leave_type, "display_name", None)
            or getattr(leave_type, "name", None)
            or ""
        ).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        category = time_off_category(name)
        lines.append(f"{category}: {name}" if category else name)
    return lines


def _pay_info(employee, *, banking, deductions, contributions, allocations):
    pairs = []
    rate = _pay_rate(employee)
    if rate is not None:
        pairs.append(rate)
    pairs.append(_pay_method(banking))

    deduction_lines = _amount_lines(
        deductions, "total_employee_deduction_per_pay_check"
    )
    pairs.append(_pair("Deductions", deduction_lines or ["None"]))

    contribution_lines = _amount_lines(
        contributions, "total_company_contribution_per_pay_check"
    )
    pairs.append(_pair("Contributions", contribution_lines or ["None"]))

    time_off = _time_off_lines(allocations)
    pairs.append(_pair("Time off", time_off or ["None"]))
    return pairs


def _filing_status(tax_row):
    """The printable withholding status for one `EmployeeTax` row."""
    status = _FILING_STATUS_LABELS.get(tax_row.holding_status or "")
    if not status:
        status = _MARITAL_LABELS.get(tax_row.martial_status or "", "")
    if not status:
        return ""
    if getattr(tax_row, "is_multiple_jobs_or_spouse_works", False):
        status = f"{status} Multiple jobs"
    return status


def _tax_info(employee, tax_rows):
    """SSN, then the federal line, then one line per state.

    An employee can carry several rows for the same state -- production has a
    duplicate with every field blank -- so rows without a resolvable status are
    dropped rather than printed as an empty line.
    """
    pairs = [_pair("SSN", mask_tail(employee.ssn))]

    federal = [row for row in tax_rows if not (row.state or "").strip()]
    for row in federal[:1]:
        status = _filing_status(row)
        if status:
            pairs.append(_pair("Fed", status))

    seen_states = set()
    for row in tax_rows:
        state = (row.state or "").strip().upper()
        if not state or state in seen_states:
            continue
        status = _filing_status(row)
        if not status:
            continue
        seen_states.add(state)
        pairs.append(_pair(state, status))
    return pairs


def _hire_date(employee):
    """(date, which field it came from). No dedicated hire-date field exists."""
    confirmation = getattr(employee, "confirmation_date", None)
    if confirmation:
        return confirmation, "confirmation_date"
    offer = getattr(employee, "offer_date", None)
    if offer:
        return offer, "offer_date"
    return None, ""


def build_employee_details(employees, *, related=None):
    """One row per employee.

    `related` maps an employee id to its prefetched satellites::

        {employee_id: {"address":…, "banking":…, "deductions": [...],
                       "contributions": [...], "allocations": [...],
                       "tax_rows": [...]}}

    Passing it keeps this function free of queries; the view assembles it in a
    fixed number of round trips rather than one per employee per relation.
    """
    related = related or {}
    rows = []

    for employee in employees:
        facts = related.get(employee.id, {})
        hire_date, hire_date_source = _hire_date(employee)
        address = facts.get("address")
        tax_rows = facts.get("tax_rows", [])

        rows.append(
            {
                "key": str(employee.uid),
                "employee_uid": str(employee.uid),
                "name": employee_label(employee),
                "address": _address_line(address),
                "date_of_birth": masked_birth_date(employee.date_of_birth),
                "gender": (employee.gender or "").replace("_", " ").title(),
                "hire_date": hire_date,
                "hire_date_source": hire_date_source,
                "work_location": _work_location_line(employee.work_locations),
                "pay_info": _pay_info(
                    employee,
                    banking=facts.get("banking"),
                    deductions=facts.get("deductions", []),
                    contributions=facts.get("contributions", []),
                    allocations=facts.get("allocations", []),
                ),
                "tax_info": _tax_info(employee, tax_rows),
                "notes": (employee.description or "").strip(),
            }
        )

    rows.sort(key=lambda row: (row["name"].lower(), row["key"]))
    return {"columns": COLUMNS, "rows": rows}
