"""Build the "Total payroll cost" report.

The narrowest of the payroll reports: one column, and a short ladder of
subtotals adding up to what a pay run actually cost the company --

    total pay + company contributions + employer taxes

Rows come back flat with a `kind` saying how each one reads, so the renderer
does not have to infer structure from indentation.
"""

from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_report_common import (
    ZERO,
    Bucket,
    amount_string,
    is_pretax,
    ordered_types,
)


COLUMNS = [
    {"key": "item", "label": "Item", "align": "left"},
    {"key": "amount", "label": "Amount", "align": "right"},
]

# This report leads with the employee/employer pair rather than FUTA, unlike
# the by-employee summary. Matching the reference matters more than matching
# the sibling, since the two are read side by side by different people.
_EMPLOYER_TAX_ORDER = (
    "SOCIAL_SECURITY_EMPLOYER",
    "MEDICARE_EMPLOYER",
    "FUTA_EMPLOYER",
)


def _row(key, label, kind, amount=None):
    return {
        "key": key,
        "label": label,
        "kind": kind,  # group | item | subtotal | total
        "amount": None if amount is None else amount_string(amount),
    }


def build_total_payroll_cost(payrolls, *, pretax_names=frozenset()):
    """Sum every run in range into the cost ladder.

    `payrolls` must have `payroll_components` prefetched.
    """
    totals = Bucket()
    for payroll in payrolls:
        for component in payroll.payroll_components.all():
            totals.add_component(
                component,
                is_pretax=is_pretax(component.payroll_type, pretax_names),
            )

    rows = []

    # --- Total pay ---------------------------------------------------------
    # Every PAY component is a paycheck wage. "Non-paycheck wages" and
    # "Reimbursements" are reserved to match the reference layout -- nothing in
    # the model marks an earning as either, the same gap "Other pay" has on the
    # by-employee report.
    rows.append(_row("total_pay", "Total pay", "group"))
    rows.append(_row("paycheck_wages", "Paycheck wages", "item", totals.gross))
    rows.append(_row("non_paycheck_wages", "Non-paycheck wages", "item", ZERO))
    rows.append(_row("reimbursements", "Reimbursements", "item", ZERO))
    rows.append(_row("total_pay.subtotal", "Subtotal", "subtotal", totals.gross))

    # --- Company contributions ---------------------------------------------
    rows.append(_row("company_contributions", "Company contributions", "group"))
    for payroll_type in ordered_types(set(totals.employer_contributions), ()):
        rows.append(
            _row(
                f"company_contributions.{payroll_type}",
                component_label(payroll_type),
                "item",
                totals.employer_contributions[payroll_type],
            )
        )
    rows.append(
        _row(
            "company_contributions.subtotal",
            "Subtotal",
            "subtotal",
            totals.employer_contribution_total,
        )
    )

    # --- Employer taxes ----------------------------------------------------
    rows.append(_row("employer_taxes", "Employer taxes", "group"))
    for payroll_type in ordered_types(set(totals.employer_taxes), _EMPLOYER_TAX_ORDER):
        rows.append(
            _row(
                f"employer_taxes.{payroll_type}",
                component_label(payroll_type),
                "item",
                totals.employer_taxes[payroll_type],
            )
        )
    rows.append(
        _row(
            "employer_taxes.subtotal",
            "Subtotal",
            "subtotal",
            totals.employer_tax_total,
        )
    )

    # --- Total -------------------------------------------------------------
    rows.append(
        _row(
            "total_payroll_cost",
            "Total payroll cost",
            "total",
            totals.total_payroll_cost,
        )
    )

    return {"columns": COLUMNS, "rows": rows}
