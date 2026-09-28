"""Build the "Payroll details" report.

Same figures as the by-employee summary, transposed: there, line items are rows
and employees are columns; here, each **payroll run** is a row and the line
items are nested inside its cells. A employee paid twice in the range gets two
rows, where the summary would have folded them into one column.

Shape returned::

    {
      "columns": [{"key": "pay_date", "label": "Pay date", ...}],
      "rows": [{"key": "total", "is_total": true, "cells": {...}}, ...]
    }

The Total row leads, then one row per run ordered by employee then pay date.

Cells holding a breakdown are lists of `{label, hours, amount, depth}`; the two
scalar cells (`net_pay`, `total_payroll_cost`) are bare strings. Amounts follow
the printed report's signs -- employee withholdings negative, employer costs
positive.

The Total row spells labels out in full ("Federal Income Tax") while per-run
rows abbreviate ("FIT"), matching the reference report: the total is read on its
own, a run is read against its neighbours in a narrow column.
"""

from payrollio.django_rest.helpers.component_labels import (
    component_label,
    component_short_label,
)
from payrollio.django_rest.helpers.payroll_report_common import (
    EMPLOYEE_TAX_ORDER,
    EMPLOYER_TAX_ORDER,
    ZERO,
    Bucket,
    amount_string,
    employee_label,
    is_pretax,
    ordered_types,
    resolve_pretax_deduction_names,  # re-exported: callers import it from here
)


TOTAL_ROW_KEY = "total"

COLUMNS = [
    {"key": "pay_date", "label": "Pay date", "align": "left"},
    {"key": "name", "label": "Name", "align": "left"},
    {"key": "hours", "label": "Hours", "align": "right"},
    {"key": "gross_pay", "label": "Gross pay", "align": "right"},
    {"key": "other_pay", "label": "Other pay", "align": "right"},
    {
        "key": "employee_taxes_deductions",
        "label": "Employee taxes & deductions",
        "align": "right",
    },
    {"key": "net_pay", "label": "Net pay", "align": "right"},
    {
        "key": "employer_taxes_contributions",
        "label": "Employer taxes & contributions",
        "align": "right",
    },
    {"key": "total_payroll_cost", "label": "Total payroll cost", "align": "right"},
]


def _entry(label, amount, *, depth=0, hours=None, negate=False):
    if negate and amount:
        amount = -amount
    return {
        "label": label,
        "depth": depth,
        "hours": None if hours is None else amount_string(hours),
        "amount": amount_string(amount),
    }


def _gross_entries(bucket, label_for):
    """The Hours / Gross pay cell: a group total, each pay type, then adjusted.

    One list feeds two printed columns -- `hours` is null on the adjusted-gross
    line, which is why that column reads blank there rather than 0.00h.
    """
    entries = [
        _entry("Gross", bucket.gross, hours=bucket.total_hours),
    ]
    for payroll_type in ordered_types(set(bucket.pay_by_type), ()):
        entries.append(
            _entry(
                label_for(payroll_type),
                bucket.pay_by_type.get(payroll_type, ZERO),
                depth=1,
                hours=bucket.hours_by_type.get(payroll_type, ZERO),
            )
        )
    entries.append(_entry("Adjusted gross", bucket.adjusted_gross))
    return entries


def _withheld_entries(bucket, label_for):
    """Employee taxes & deductions.

    A "Total" line appears only when both taxes *and* deductions are present --
    with one subgroup it would restate the line directly beneath it, which is
    how the reference report prints it.
    """
    tax_types = ordered_types(set(bucket.employee_taxes), EMPLOYEE_TAX_ORDER)
    deduction_types = ordered_types(set(bucket.employee_deductions), ())

    entries = []
    if tax_types and deduction_types:
        entries.append(
            _entry("Total", bucket.employee_withheld_total, negate=True)
        )
    if tax_types:
        entries.append(
            _entry("Employee taxes", bucket.employee_tax_total, negate=True)
        )
        for payroll_type in tax_types:
            entries.append(
                _entry(
                    label_for(payroll_type),
                    bucket.employee_taxes.get(payroll_type, ZERO),
                    depth=1,
                    negate=True,
                )
            )
    if deduction_types:
        entries.append(
            _entry("Employee deductions", bucket.employee_deduction_total, negate=True)
        )
        for payroll_type in deduction_types:
            entries.append(
                _entry(
                    label_for(payroll_type),
                    bucket.employee_deductions.get(payroll_type, ZERO),
                    depth=1,
                    negate=True,
                )
            )
    return entries


def _employer_entries(bucket, label_for):
    """Employer taxes & contributions -- always led by a Total line."""
    tax_types = ordered_types(set(bucket.employer_taxes), EMPLOYER_TAX_ORDER)
    contribution_types = ordered_types(set(bucket.employer_contributions), ())
    if not tax_types and not contribution_types:
        return []

    entries = [_entry("Total", bucket.employer_cost_total)]
    if tax_types:
        entries.append(_entry("Employer taxes", bucket.employer_tax_total))
        for payroll_type in tax_types:
            entries.append(
                _entry(
                    label_for(payroll_type),
                    bucket.employer_taxes.get(payroll_type, ZERO),
                    depth=1,
                )
            )
    if contribution_types:
        entries.append(
            _entry("Company contributions", bucket.employer_contribution_total)
        )
        for payroll_type in contribution_types:
            entries.append(
                _entry(
                    label_for(payroll_type),
                    bucket.employer_contributions.get(payroll_type, ZERO),
                    depth=1,
                )
            )
    return entries


def _row(key, bucket, label_for, *, is_total, pay_date=None, pay_period=None,
         name="", employee_uid=None):
    return {
        "key": key,
        "is_total": is_total,
        "pay_date": pay_date,
        "pay_period": pay_period or "",
        "name": name,
        "employee_uid": employee_uid,
        "cells": {
            "gross_pay": _gross_entries(bucket, label_for),
            # Reserved to match the reference layout -- see the note in
            # `payroll_summary_by_employee`. Always empty for now.
            "other_pay": [],
            "employee_taxes_deductions": _withheld_entries(bucket, label_for),
            "net_pay": amount_string(bucket.net_pay),
            "employer_taxes_contributions": _employer_entries(bucket, label_for),
            "total_payroll_cost": amount_string(bucket.total_payroll_cost),
        },
    }


def build_payroll_details(payrolls, *, pretax_names=frozenset()):
    """One row per payroll run, plus a leading Total row.

    `payrolls` must have `payroll_components` available -- prefetch it, or this
    walks the components table once per run. See
    `payroll_report_common.resolve_pretax_deduction_names` for how "Adjusted
    gross" decides what counts as pre-tax.
    """
    totals = Bucket()
    runs = []

    for payroll in payrolls:
        bucket = Bucket()
        for component in payroll.payroll_components.all():
            pretax = is_pretax(component.payroll_type, pretax_names)
            bucket.add_component(component, is_pretax=pretax)
            totals.add_component(component, is_pretax=pretax)
        runs.append((payroll, bucket))

    # Employee first, then chronologically within that employee -- the printed
    # report groups a person's runs together rather than interleaving the
    # whole company by date.
    runs.sort(
        key=lambda pair: (
            employee_label(pair[0].employee).lower(),
            pair[0].pay_date or "",
            str(pair[0].uid),
        )
    )

    rows = [_row(TOTAL_ROW_KEY, totals, component_label, is_total=True)]
    for payroll, bucket in runs:
        rows.append(
            _row(
                str(payroll.uid),
                bucket,
                component_short_label,
                is_total=False,
                pay_date=payroll.pay_date,
                pay_period=payroll.pay_period,
                name=employee_label(payroll.employee),
                employee_uid=str(payroll.employee.uid),
            )
        )

    return {"columns": COLUMNS, "rows": rows}
