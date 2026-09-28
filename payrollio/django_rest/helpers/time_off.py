"""Build the "Time off" report.

A snapshot, not a period: the reference subtitle is "Current balance for active
employees", with no date range. One row per active employee, and four category
slots -- Vacation, Sick leave, Paid time off, Unpaid time off -- each showing the
policy name with its balance and days used.

**The four categories are not a field.** `LeaveType` records
`is_leave_without_pay` and `is_partially_paid`, but nothing that says "this is
the vacation policy". So:

* **Unpaid time off** is definitive -- it reads `is_leave_without_pay`.
* **Sick leave** and **Vacation** are matched on the policy name, and only on
  unambiguous words.
* Everything else paid falls into **Paid time off**, which is the honest default:
  a policy the company has not named after a purpose is simply paid leave.

The consequence, worth knowing when comparing against the reference: a policy
called "Leave policy" lands in Paid time off rather than Vacation, because
nothing about it says vacation. Assigning it would be a guess about someone's
entitlement. Giving these four slots a real home on `LeaveType` is the fix.

Balances come from `EmployeeLeaveAllocation.available_balance`, which already
encodes ``opening + allocated + adjusted - used - encashed`` clamped at zero --
this report does not re-derive that arithmetic.
"""

from payrollio.django_rest.helpers.payroll_report_common import employee_label


VACATION = "vacation"
SICK = "sick"
PAID = "paid"
UNPAID = "unpaid"

CATEGORIES = [
    {"key": VACATION, "label": "Vacation"},
    {"key": SICK, "label": "Sick leave"},
    {"key": PAID, "label": "Paid time off"},
    {"key": UNPAID, "label": "Unpaid time off"},
]

# The reference prints two tables, pairing the categories two at a time. Shipping
# the pairing keeps the renderer from hard-coding it.
TABLES = [[VACATION, SICK], [PAID, UNPAID]]

_SICK_WORDS = ("sick", "medical", "illness")
_VACATION_WORDS = ("vacation", "annual", "holiday")
_UNPAID_WORDS = ("unpaid", "no paid", "non paid", "nonpaid", "without pay")


def _policy_name(leave_type):
    return (
        getattr(leave_type, "display_name", None)
        or getattr(leave_type, "name", None)
        or ""
    ).strip()


def categorise(leave_type):
    """Which of the four slots a policy belongs in.

    `is_leave_without_pay` decides Unpaid outright; the rest is name matching,
    defaulting to Paid.
    """
    if leave_type is None:
        return PAID

    name = _policy_name(leave_type).lower()

    if getattr(leave_type, "is_leave_without_pay", False):
        return UNPAID
    if any(word in name for word in _UNPAID_WORDS):
        return UNPAID
    if any(word in name for word in _SICK_WORDS):
        return SICK
    if any(word in name for word in _VACATION_WORDS):
        return VACATION
    return PAID


def format_balance(value):
    """`Decimal("90.000")` -> `"90.0"`, `Decimal("87.440")` -> `"87.44"`.

    The reference trims trailing zeros rather than printing a fixed 2dp, so a
    whole-day balance reads "90.0" and not "90.00". Days are not money and do
    not want money's formatting.
    """
    if value is None:
        return "0"
    number = float(value)
    if number == int(number):
        return f"{int(number)}.0"
    return f"{round(number, 2):g}"


def format_used(value):
    """Days used is a whole number on the reference -- `0`, not `0.0`."""
    if value is None:
        return "0"
    return str(int(value))


EMPTY_CELL = {"policy": None, "balance": "0", "used": "0"}


def build_time_off(employees, allocations_by_employee=None):
    """One row per employee, four category slots each.

    `allocations_by_employee` maps an employee id to their
    `EmployeeLeaveAllocation` rows, prefetched with `leave_type`.
    """
    allocations_by_employee = allocations_by_employee or {}
    rows = []

    for employee in employees:
        cells = {category["key"]: dict(EMPTY_CELL) for category in CATEGORIES}

        for allocation in allocations_by_employee.get(employee.id, []):
            leave_type = allocation.leave_type
            name = _policy_name(leave_type)
            if not name:
                continue
            category = categorise(leave_type)
            cell = cells[category]
            if cell["policy"] is not None:
                # Two policies in one slot: the report has room for one name, so
                # the balances add and the first name stands. Dropping the
                # second would understate what the employee is owed.
                cell["balance"] = format_balance(
                    float(cell["balance"]) + float(allocation.available_balance)
                )
                cell["used"] = format_used(
                    int(cell["used"]) + int(allocation.used_days or 0)
                )
                continue
            cell["policy"] = name
            cell["balance"] = format_balance(allocation.available_balance)
            cell["used"] = format_used(allocation.used_days)

        rows.append(
            {
                "key": str(employee.uid),
                "employee_uid": str(employee.uid),
                "name": employee_label(employee),
                "categories": cells,
            }
        )

    rows.sort(key=lambda row: (row["name"].lower(), row["key"]))
    return {"categories": CATEGORIES, "tables": TABLES, "rows": rows}
