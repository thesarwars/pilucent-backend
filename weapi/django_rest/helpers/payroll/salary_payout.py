"""Atomic-as-possible payroll payout: move a run's net pay via Moov, record it,
mark the run paid, and generate a receipt — in ONE server-side operation.

Money movement can't be rolled back with ``transaction.atomic`` (once Moov moves
funds, a DB rollback can't un-move them). So the safety comes from ORDERING and
IDEMPOTENCY, not a wrapping transaction:

* All validation runs BEFORE any money moves, so a bad request can never strand
  funds (the split-brain that the two-call frontend flow produced).
* A stable Moov idempotency key (``payroll-<run.uid>``) means a retry — even one
  that lost the DB write after Moov succeeded — returns the SAME transfer instead
  of moving money twice. Combined with ``update_or_create`` on the unique
  ``moov_transfer_uid`` and a DB guard, a run is paid at most once.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction

from moovio_sdk.models import errors as moov_errors

from moovmoneyio.choices import (
    MoovBankAccountKindChoices,
    MoovTransferStatusChoices,
)
from moovmoneyio.models import (
    MoovAccountSettings,
    MoovBankAccountSettings,
    MoovTransfers,
)
from moovmoneyio.django_rest.helpers.moov_connection import moov_client, moov_call

from payrollio.models import PayrollSalaryProcess

from weapi.django_rest.helpers.payroll.transfer_receipt import (
    generate_transfer_receipt,
)

# A run with a transfer in one of these states is considered already paid (or
# in-flight) and must not be paid again.
_LIVE_TRANSFER_STATUSES = (
    MoovTransferStatusChoices.PENDING,
    MoovTransferStatusChoices.COMPLETED,
    MoovTransferStatusChoices.RESERVED,
)


class PayoutError(Exception):
    """A payout precondition failed. ``status_code`` drives the HTTP response.

    Raised only for problems detected BEFORE money moves (400), or for a Moov
    transfer that did not go through (502) — never after funds have moved.
    """

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _amount_to_cents(amount) -> int:
    """Dollars -> integer minor units, without binary-float truncation."""
    return int((Decimal(str(amount)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _resolve_payment_methods(moov, moov_account_uid, source_bank, dest_bank):
    """Return (source_ach_debit_pm_id, dest_ach_credit_pm_id) for the two banks."""
    payment_methods = moov_call(
        lambda: moov.payment_methods.list(account_id=moov_account_uid)
    )

    source_pm = None
    dest_pm = None
    for pm in payment_methods or []:
        bank_id = (pm.get("bank_account") or {}).get("bank_account_id")
        pm_type = pm.get("payment_method_type")
        pm_id = pm.get("payment_method_id")
        if pm_type == "ach-debit-fund" and bank_id == source_bank.bank_account_uid:
            source_pm = pm_id
        elif (
            pm_type == "ach-credit-same-day"
            and bank_id == dest_bank.bank_account_uid
        ):
            dest_pm = pm_id
    return source_pm, dest_pm


def _transfer_payload(transfer):
    return {
        "uid": str(transfer.uid),
        "moov_transfer_uid": transfer.moov_transfer_uid,
        "amount": str(transfer.amount),
        "currency": transfer.currency,
        "status": transfer.status,
    }


def pay_salary_run(view, run: PayrollSalaryProcess, user):
    """Pay ``run``'s net pay to the employee via Moov. Returns a result dict.

    Validation failures raise ``PayoutError`` before any money moves. On success
    the run is marked paid, a ``MoovTransfers`` row is linked to it, and a receipt
    PDF is generated server-side.
    """
    company = user.get_active_company()

    # --- Idempotency guard: never pay the same run twice. ---
    existing = run.moov_transfers.filter(status__in=_LIVE_TRANSFER_STATUSES).first()
    if existing:
        receipt = generate_transfer_receipt(view, company, run, existing)
        return {
            "already_paid": True,
            "transfer": _transfer_payload(existing),
            "receipt": receipt,
        }

    # --- Validate everything BEFORE moving money. ---
    if run.status == "VOIDED":
        raise PayoutError("Cannot pay a voided payroll run.")

    net_pay = run.net_pay or Decimal("0")
    if net_pay <= 0:
        raise PayoutError("Net pay must be greater than zero to pay this run.")

    employee = run.employee
    if employee is None:
        raise PayoutError("This payroll run has no employee.")

    moov_setting = MoovAccountSettings.objects.filter(company=company).first()
    if not moov_setting:
        raise PayoutError("Moov account is not set up for this company.")

    source_bank = MoovBankAccountSettings.objects.filter(
        moov_account_settings=moov_setting,
        bank_account_kind=MoovBankAccountKindChoices.SOURCE,
    ).first()
    if not source_bank:
        raise PayoutError("No Moov source (funding) bank account is configured.")

    dest_bank = MoovBankAccountSettings.objects.filter(
        moov_account_settings=moov_setting,
        bank_account_kind=MoovBankAccountKindChoices.DESTINATION,
        employee=employee,
    ).first()
    if not dest_bank:
        raise PayoutError(
            f"No Moov bank account on file for {employee} to receive the payment."
        )

    # --- Move the money (external; the only irreversible step). ---
    # Moov requires X-Idempotency-Key to be a valid UUID. run.uid IS a UUID and
    # is stable per run, so retries of the same run dedup at Moov (one pay/run).
    idempotency_key = str(run.uid)
    description = run.pay_period or f"Payroll {run.uid}"

    with moov_client() as moov:
        source_pm, dest_pm = _resolve_payment_methods(
            moov, moov_setting.moov_account_uid, source_bank, dest_bank
        )
        if not source_pm:
            raise PayoutError(
                "The company funding account has no ACH debit payment method."
            )
        if not dest_pm:
            raise PayoutError(
                "The employee bank account has no ACH credit payment method."
            )

        try:
            data = moov_call(
                lambda: moov.transfers.create(
                    x_idempotency_key=idempotency_key,
                    # The facilitator/platform account owns the transfer (matches
                    # the working transfer view); payment methods are still listed
                    # on the company's own connected account above.
                    account_id=settings.MOOV_ACCOUNT_UID,
                    source={"payment_method_id": source_pm},
                    destination={"payment_method_id": dest_pm},
                    amount={"currency": "USD", "value": _amount_to_cents(net_pay)},
                    description=description,
                )
            )
        except moov_errors.MoovError as exc:
            # Money did NOT move — surface as a gateway error, run stays unpaid.
            raise PayoutError(
                f"Moov transfer failed; no money was moved: {exc}",
                status_code=502,
            )

    transfer_uid = data.get("transfer_id") or data.get("transferID")
    if not transfer_uid:
        # A 2xx with no transfer id — treat as a gateway failure rather than
        # silently marking the run paid.
        raise PayoutError(
            "Moov did not return a transfer id; treating the payout as failed.",
            status_code=502,
        )

    # --- Record + mark paid, atomically (money already moved). ---
    with transaction.atomic():
        locked_run = PayrollSalaryProcess.objects.select_for_update().get(pk=run.pk)
        transfer, _created = MoovTransfers.objects.update_or_create(
            moov_transfer_uid=transfer_uid,
            defaults={
                "amount": net_pay,
                "currency": "USD",
                "description": description,
                "source_bank_account": source_bank,
                "destination_bank_account": dest_bank,
                "status": MoovTransferStatusChoices.PENDING,
                "employee": employee,
                # The actor (admin/owner or employee-user) — always a User.
                "created_by": user,
                "company": company,
                "payroll_salary_process": locked_run,
            },
        )
        locked_run.is_salary_done = True
        locked_run.save(update_fields=["is_salary_done", "updated_at"])

    receipt = generate_transfer_receipt(view, company, run, transfer)
    return {
        "already_paid": False,
        "transfer": _transfer_payload(transfer),
        "receipt": receipt,
    }
