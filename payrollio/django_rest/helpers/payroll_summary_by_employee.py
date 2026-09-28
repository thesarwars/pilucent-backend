"""Build the "Payroll summary by employee" grid.

This report is a **pivot**, which is what separates it from the existing payroll
summary: rows are named line items (Federal Income Tax, FUTA Employer, ...) and
columns are a Total plus one per employee. The existing
`PayrollSummaryReportView` sums components into five category buckets and throws
`payroll_type` away, so its response cannot produce these rows.

Shape returned::

    {
      "columns":  [{"key": "total", ...}, {"key": <employee uid>, ...}],
      "sections": [{"key": "hours", "rows": [{..., "values": {<col key>: str}}]}],
    }

Every row carries a value for every column, including zeros -- the reference
report prints `$0.00` for taxes that did not apply rather than omitting them, so
that a column stays comparable down its whole length.

Sign convention follows the printed report: employee taxes and deductions are
**negated** (they reduce the employee), employer costs stay positive. Storage is
positive for both, since `net_pay = gross_pay - employee_taxes_deductions`.
"""

from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_report_common import (
    EMPLOYEE_TAX_ORDER,
    EMPLOYER_TAX_ORDER,
    ZERO,
    Bucket,
    employee_label,
    is_pretax,
    ordered_types,
    resolve_pretax_deduction_names,  # re-exported: callers import it from here
)


TOTAL_COLUMN_KEY = "total"


class _GridWriter:
    """Collects rows, filling each one across every column."""

    def __init__(self, column_keys, buckets):
        self.column_keys = column_keys
        self.buckets = buckets

    def row(self, key, label, depth, reader, *, fmt="money", negate=False,
            is_empty=False):
        # Values go out as plain 2dp strings; `format` tells the renderer
        # whether to dress them as currency or an hours figure, so nothing has
        # to parse "$1,234.56" back into a number.
        values = {}
        for column_key in self.column_keys:
            amount = reader(self.buckets[column_key])
            if negate and amount:
                amount = -amount
            values[column_key] = f"{amount:.2f}"
        return {
            "key": key,
            "label": label,
            "depth": depth,
            "format": fmt,
            "is_empty": is_empty,
            "values": values,
        }


def build_payroll_summary_by_employee(payrolls, *, pretax_names=frozenset()):
    """Pivot `PayrollSalaryProcess` rows into the report grid.

    `payrolls` must have `payroll_components` available -- prefetch it, or this
    walks the components table once per run.

    `pretax_names` is a set of normalized deduction names treated as pre-tax
    when computing "Adjusted gross". Components carry no pre-tax flag of their
    own (see `resolve_pretax_deduction_names`), so anything unmatched counts as
    post-tax and adjusted gross falls back to gross -- understating deductions
    rather than inventing them. Pass an empty set to disable the adjustment
    entirely, making adjusted gross equal gross.
    """
    buckets = {TOTAL_COLUMN_KEY: Bucket()}
    employees = {}

    for payroll in payrolls:
        employee = payroll.employee
        column_key = str(employee.uid)
        if column_key not in buckets:
            buckets[column_key] = Bucket()
            employees[column_key] = employee

        for component in payroll.payroll_components.all():
            pretax = is_pretax(component.payroll_type, pretax_names)
            buckets[column_key].add_component(component, is_pretax=pretax)
            buckets[TOTAL_COLUMN_KEY].add_component(component, is_pretax=pretax)

    employee_keys = sorted(
        employees, key=lambda key: (employee_label(employees[key]).lower(), key)
    )
    column_keys = [TOTAL_COLUMN_KEY] + employee_keys

    columns = [{"key": TOTAL_COLUMN_KEY, "label": "Total", "is_total": True}]
    for key in employee_keys:
        columns.append(
            {
                "key": key,
                "label": employee_label(employees[key]),
                "employee_uid": key,
                "is_total": False,
            }
        )

    writer = _GridWriter(column_keys, buckets)
    totals = buckets[TOTAL_COLUMN_KEY]

    # Row sets are the union across employees so every column has the same
    # rows; an employee who lacks a tax shows 0.00 rather than a ragged column.
    pay_types = ordered_types(set(totals.pay_by_type), ())
    hour_types = ordered_types(set(totals.hours_by_type), ())
    employee_tax_types = ordered_types(
        set(totals.employee_taxes), EMPLOYEE_TAX_ORDER
    )
    employee_deduction_types = ordered_types(set(totals.employee_deductions), ())
    employer_tax_types = ordered_types(set(totals.employer_taxes), EMPLOYER_TAX_ORDER)
    employer_contribution_types = ordered_types(
        set(totals.employer_contributions), ()
    )

    sections = []

    # --- Hours -------------------------------------------------------------
    hours_rows = [
        writer.row("hours", "Hours", 0, lambda b: b.total_hours, fmt="hours")
    ]
    for payroll_type in hour_types:
        hours_rows.append(
            writer.row(
                f"hours.{payroll_type}",
                component_label(payroll_type),
                1,
                lambda b, t=payroll_type: b.hours_by_type.get(t, ZERO),
                fmt="hours",
            )
        )
    sections.append({"key": "hours", "rows": hours_rows})

    # --- Gross -------------------------------------------------------------
    gross_rows = [writer.row("gross", "Gross", 0, lambda b: b.gross)]
    for payroll_type in pay_types:
        gross_rows.append(
            writer.row(
                f"gross.{payroll_type}",
                component_label(payroll_type),
                1,
                lambda b, t=payroll_type: b.pay_by_type.get(t, ZERO),
            )
        )
    gross_rows.append(
        writer.row("adjusted_gross", "Adjusted gross", 1, lambda b: b.adjusted_gross)
    )
    sections.append({"key": "gross", "rows": gross_rows})

    # --- Other pay ---------------------------------------------------------
    # Reserved to match the reference layout. Every PAY component already rolls
    # into Gross, and nothing in the model marks a non-gross earning (a
    # reimbursement, say), so this prints as a dash until such a type exists.
    sections.append(
        {
            "key": "other_pay",
            "rows": [
                writer.row(
                    "other_pay", "Other pay", 0, lambda b: ZERO, is_empty=True
                )
            ],
        }
    )

    # --- Employee taxes & deductions ---------------------------------------
    withheld_rows = [
        writer.row(
            "employee_taxes_deductions",
            "Employee taxes & deductions",
            0,
            lambda b: b.employee_withheld_total,
            negate=True,
        )
    ]
    if employee_tax_types:
        withheld_rows.append(
            writer.row(
                "employee_taxes",
                "Employee taxes",
                1,
                lambda b: b.employee_tax_total,
                negate=True,
            )
        )
        for payroll_type in employee_tax_types:
            withheld_rows.append(
                writer.row(
                    f"employee_taxes.{payroll_type}",
                    component_label(payroll_type),
                    2,
                    lambda b, t=payroll_type: b.employee_taxes.get(t, ZERO),
                    negate=True,
                )
            )
    if employee_deduction_types:
        withheld_rows.append(
            writer.row(
                "employee_deductions",
                "Employee deductions",
                1,
                lambda b: b.employee_deduction_total,
                negate=True,
            )
        )
        for payroll_type in employee_deduction_types:
            withheld_rows.append(
                writer.row(
                    f"employee_deductions.{payroll_type}",
                    component_label(payroll_type),
                    2,
                    lambda b, t=payroll_type: b.employee_deductions.get(t, ZERO),
                    negate=True,
                )
            )
    sections.append({"key": "employee_taxes_deductions", "rows": withheld_rows})

    # --- Net pay -----------------------------------------------------------
    sections.append(
        {
            "key": "net_pay",
            "rows": [writer.row("net_pay", "Net pay", 0, lambda b: b.net_pay)],
        }
    )

    # --- Employer taxes & contributions ------------------------------------
    employer_rows = [
        writer.row(
            "employer_taxes_contributions",
            "Employer taxes & contributions",
            0,
            lambda b: b.employer_cost_total,
        )
    ]
    if employer_tax_types:
        employer_rows.append(
            writer.row(
                "employer_taxes", "Employer taxes", 1, lambda b: b.employer_tax_total
            )
        )
        for payroll_type in employer_tax_types:
            employer_rows.append(
                writer.row(
                    f"employer_taxes.{payroll_type}",
                    component_label(payroll_type),
                    2,
                    lambda b, t=payroll_type: b.employer_taxes.get(t, ZERO),
                )
            )
    if employer_contribution_types:
        employer_rows.append(
            writer.row(
                "employer_contributions",
                "Company contributions",
                1,
                lambda b: b.employer_contribution_total,
            )
        )
        for payroll_type in employer_contribution_types:
            employer_rows.append(
                writer.row(
                    f"employer_contributions.{payroll_type}",
                    component_label(payroll_type),
                    2,
                    lambda b, t=payroll_type: b.employer_contributions.get(t, ZERO),
                )
            )
    sections.append({"key": "employer_taxes_contributions", "rows": employer_rows})

    # --- Total payroll cost -------------------------------------------------
    sections.append(
        {
            "key": "total_payroll_cost",
            "rows": [
                writer.row(
                    "total_payroll_cost",
                    "Total payroll cost",
                    0,
                    lambda b: b.total_payroll_cost,
                )
            ],
        }
    )

    return {"columns": columns, "sections": sections}


