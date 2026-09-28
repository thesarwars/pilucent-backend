"""Build the "Total pay" report.

The narrowest employee-facing report: one row per employee, one column per pay
type, and a Total column beside a Total row. It answers "who was paid what, and
by what kind of pay" without any of the tax detail its siblings carry.

Effectively the Gross section of the by-employee summary stood on its side, so
it shares that report's bucketing rather than re-deriving it.
"""

from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_report_common import (
    ZERO,
    Bucket,
    amount_string,
    employee_label,
    ordered_types,
)


TOTAL_ROW_KEY = "total"
TOTAL_COLUMN_KEY = "total"


def build_total_pay(payrolls):
    """One row per employee, plus a trailing Total row.

    `payrolls` must have `payroll_components` prefetched.
    """
    buckets = {}
    employees = {}
    totals = Bucket()

    for payroll in payrolls:
        employee = payroll.employee
        key = str(employee.uid)
        if key not in buckets:
            buckets[key] = Bucket()
            employees[key] = employee
        for component in payroll.payroll_components.all():
            # Pay only -- taxes and deductions are somebody else's report.
            buckets[key].add_component(component, is_pretax=False)
            totals.add_component(component, is_pretax=False)

    # Columns are the union of pay types across everyone, so an employee who
    # was not paid a given kind shows 0.00 rather than leaving a ragged row.
    pay_types = ordered_types(set(totals.pay_by_type), ())

    columns = [{"key": "name", "label": "Name", "align": "left"}]
    for payroll_type in pay_types:
        columns.append(
            {
                "key": payroll_type,
                "label": component_label(payroll_type),
                "align": "right",
            }
        )
    columns.append({"key": TOTAL_COLUMN_KEY, "label": "Total", "align": "right"})

    def amounts(bucket):
        values = {
            payroll_type: amount_string(bucket.pay_by_type.get(payroll_type, ZERO))
            for payroll_type in pay_types
        }
        values[TOTAL_COLUMN_KEY] = amount_string(bucket.gross)
        return values

    rows = []
    for key in sorted(
        employees, key=lambda k: (employee_label(employees[k]).lower(), k)
    ):
        rows.append(
            {
                "key": key,
                "employee_uid": key,
                "name": employee_label(employees[key]),
                "is_total": False,
                "values": amounts(buckets[key]),
            }
        )

    rows.append(
        {
            "key": TOTAL_ROW_KEY,
            "employee_uid": None,
            "name": "Total",
            "is_total": True,
            "values": amounts(totals),
        }
    )

    return {"columns": columns, "rows": rows}
