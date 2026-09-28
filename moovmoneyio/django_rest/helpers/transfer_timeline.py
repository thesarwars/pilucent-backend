"""Build a Moov-dashboard-style status timeline for a transfer.

The Moov transfer object exposes everything the dashboard renders:
``createdOn``/``completedOn`` on the transfer, and per-leg ACH status timestamps
under ``source``/``destination`` -> ``achDetails`` -> ``statusUpdates``
(``initiatedOn`` / ``originatedOn`` / ``correctedOn`` / ``returnedOn`` /
``completedOn``). The **source** leg is the ACH debit; the **destination** leg is
the ACH credit.

``build_transfer_timeline`` turns that into an ordered list of steps, each with a
timestamp (``at``) and a ``done`` flag, so the frontend can render future steps
grayed-out like the dashboard. Keys are matched in both camelCase (raw Moov body)
and snake_case (converted), since callers may pass either.
"""


from decimal import Decimal


def _get(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _leg_status_updates(leg):
    ach = _get(leg or {}, "achDetails", "ach_details") or {}
    return _get(ach, "statusUpdates", "status_updates") or {}


def build_transfer_timeline(transfer):
    """Return an ordered list of {key, label, at, done} steps for a transfer."""
    transfer = transfer or {}
    source_updates = _leg_status_updates(_get(transfer, "source"))
    dest_updates = _leg_status_updates(_get(transfer, "destination"))

    def step(key, label, at):
        at = _iso(at)
        return {"key": key, "label": label, "at": at, "done": at is not None}

    timeline = [
        step("created", "Transfer created", _get(transfer, "createdOn", "created_on")),
    ]

    # ACH debit = source leg.
    timeline.append(
        step("debit_initiated", "ACH debit initiated",
             _get(source_updates, "initiatedOn", "initiated_on"))
    )
    timeline.append(
        step("debit_originated", "ACH debit originated",
             _get(source_updates, "originatedOn", "originated_on"))
    )
    corrected = _get(source_updates, "correctedOn", "corrected_on")
    if corrected:
        timeline.append(step("debit_corrected", "ACH debit corrected", corrected))
    returned = _get(source_updates, "returnedOn", "returned_on")
    if returned:
        timeline.append(step("debit_returned", "ACH debit returned", returned))

    # ACH credit = destination leg.
    timeline.append(
        step("credit_initiated", "ACH credit initiated",
             _get(dest_updates, "initiatedOn", "initiated_on"))
    )
    timeline.append(
        step("credit_originated", "ACH credit originated",
             _get(dest_updates, "originatedOn", "originated_on"))
    )
    d_corrected = _get(dest_updates, "correctedOn", "corrected_on")
    if d_corrected:
        timeline.append(step("credit_corrected", "ACH credit corrected", d_corrected))
    d_returned = _get(dest_updates, "returnedOn", "returned_on")
    if d_returned:
        timeline.append(step("credit_returned", "ACH credit returned", d_returned))

    timeline.append(
        step("completed", "Completed",
             _get(transfer, "completedOn", "completed_on"))
    )
    return timeline


def _money(amount_obj):
    """Moov amount {currency, value(minor units)} -> {value, currency, decimal}.

    Moov sends amounts as integer minor units (cents for USD); expose both the
    raw value and a 2-dp decimal string for display.
    """
    if not isinstance(amount_obj, dict):
        return None
    value = _get(amount_obj, "value")
    currency = _get(amount_obj, "currency") or "USD"
    decimal = None
    if value is not None:
        try:
            decimal = str((Decimal(str(value)) / 100).quantize(Decimal("0.01")))
        except Exception:
            decimal = None
    return {"value": value, "currency": currency, "decimal": decimal}


def _leg(leg, label):
    """One side (source/destination) as {leg, name, last_four, account_type, bank_name}."""
    leg = leg or {}
    bank = _get(leg, "bankAccount", "bank_account") or {}
    account = _get(leg, "account") or {}
    return {
        "leg": label,
        "name": (
            _get(account, "displayName", "display_name")
            or _get(bank, "holderName", "holder_name")
            or _get(bank, "bankName", "bank_name")
        ),
        "last_four": _get(bank, "lastFourAccountNumber", "last_four_account_number"),
        "account_type": _get(bank, "bankAccountType", "bank_account_type"),
        "bank_name": _get(bank, "bankName", "bank_name"),
    }


def _ach_debit(source):
    """The source leg's ACH debit block (company name, hold, SEC code, trace)."""
    ach = _get(source or {}, "achDetails", "ach_details") or {}
    return {
        "company_name": _get(
            ach,
            "companyEntryDescription", "company_entry_description",
            "originatingCompanyName", "originating_company_name",
        ),
        "ach_hold": _get(ach, "debitHoldPeriod", "debit_hold_period"),
        "sec_code": _get(ach, "secCode", "sec_code"),
        "trace_number": _get(ach, "traceNumber", "trace_number"),
    }


def build_transfer_details(transfer):
    """Shape a Moov transfer into the detail screen's blocks (payment summary,
    From/To, ACH debit, metadata). Defensive to missing fields and key style."""
    transfer = transfer or {}
    amount = _money(_get(transfer, "amount"))
    fee = _money(_get(transfer, "facilitatorFee", "facilitator_fee"))
    fee_decimal = fee["decimal"] if (fee and fee.get("decimal")) else "0.00"

    net_amount = None
    if amount and amount.get("decimal") is not None:
        try:
            net = Decimal(amount["decimal"]) - Decimal(fee_decimal)
            net_amount = str(net.quantize(Decimal("0.01")))
        except Exception:
            net_amount = amount["decimal"]

    return {
        "transfer_uid": _get(transfer, "transferID", "transfer_id"),
        "status": _get(transfer, "status"),
        "description": _get(transfer, "description"),
        "created_on": _iso(_get(transfer, "createdOn", "created_on")),
        "completed_on": _iso(_get(transfer, "completedOn", "completed_on")),
        "amount": amount,
        "payment_summary": {
            "amount": amount["decimal"] if amount else None,
            "fees": fee_decimal,
            "net_amount": net_amount,
            "currency": amount["currency"] if amount else "USD",
        },
        "source": _leg(_get(transfer, "source"), "ACH debit"),
        "destination": _leg(_get(transfer, "destination"), "ACH credit"),
        "ach_debit": _ach_debit(_get(transfer, "source")),
        "metadata": _get(transfer, "metadata") or {},
    }
