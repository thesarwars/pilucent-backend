"""Server-side payroll payment receipt (WeasyPrint via the shared get_pdf helper).

Replaces the frontend's jsPDF receipt that showed ``$0`` — the amount here comes
straight from the persisted ``MoovTransfers`` row, so it always reflects what was
actually paid.
"""

from common.django_rest.helpers.file_helpers import get_pdf


def _employee_name(employee):
    if employee is None:
        return ""
    user = getattr(employee, "user", None)
    name = getattr(user, "name", None) if user else None
    return name or str(employee)


def _bank_label(bank):
    if bank is None:
        return ""
    name = getattr(bank, "bank_name", None) or "Bank"
    last4 = getattr(bank, "account_number", None)
    return f"{name} ****{last4}" if last4 else name


def generate_transfer_receipt(view, company, run, transfer):
    """Render + persist a receipt PDF for a payroll payout. Returns
    ``{"file_uid", "url"}`` (absolute URL when a request is available)."""
    amount_display = f"${transfer.amount:,.2f}"

    context = {
        "label": f"payroll-receipt-{transfer.moov_transfer_uid}",
        "template": "reports/payrolls/transfer_receipt.html",
        "title": "PAYROLL PAYMENT RECEIPT",
        # Keep is_report False so it isn't purged when report PDFs regenerate.
        "is_report": False,
        "data": {
            "recipient": _employee_name(run.employee),
            "amount_display": amount_display,
            "currency": transfer.currency,
            "reference_number": transfer.moov_transfer_uid,
            "status": transfer.status,
            "pay_period": run.pay_period or "",
            "pay_date": str(run.pay_date) if run.pay_date else "",
            "description": transfer.description or "",
            "bank_label": _bank_label(transfer.destination_bank_account),
        },
    }

    file_item = get_pdf(view, True, context)

    url = file_item.file.url
    request = getattr(view, "request", None)
    if request is not None:
        url = request.build_absolute_uri(file_item.file.url)
    return {"file_uid": str(file_item.uid), "url": url}
