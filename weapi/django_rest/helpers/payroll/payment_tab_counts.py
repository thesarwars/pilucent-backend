"""Badge counts for the payroll payment screen's Pending/Cancel tabs.

Those tabs render **live Moov data** — ``MoovTransferListView`` calls
``moov.transfers.list`` and never reads the database — so their badges have to be
counted from Moov as well. Counting local ``MoovTransfers`` rows instead drifts
the moment a status webhook is missed: the row sits at PENDING while Moov already
reports the transfer canceled, and the screen then lists 3 canceled rows above a
badge reading 0.

The local mirror is still used as a fallback when Moov is unreachable, so an
outage degrades the badges rather than breaking the whole payment screen.
"""

import logging

from moovmoneyio.choices import MoovTransferStatusChoices
from moovmoneyio.django_rest.helpers.moov_connection import moov_call, moov_client
from moovmoneyio.models import MoovAccountSettings, MoovTransfers

logger = logging.getLogger(__name__)

# Moov's transfer list is paginated, so page through it to get a real count
# rather than just the first page. Capped so a company with a long transfer
# history can't turn one badge request into unbounded API calls.
MOOV_COUNT_PAGE_SIZE = 200
MOOV_COUNT_MAX_PAGES = 5


def count_moov_transfers(moov_account_uid, transfer_status):
    """Count one Moov account's transfers in a given status, straight from Moov."""
    total = 0
    with moov_client() as moov:
        for page in range(MOOV_COUNT_MAX_PAGES):
            skip = page * MOOV_COUNT_PAGE_SIZE

            # skip bound as a default arg: the lambda is called before the next
            # loop iteration, but binding it explicitly keeps that guaranteed.
            batch = moov_call(
                lambda skip=skip: moov.transfers.list(
                    account_id=moov_account_uid,
                    skip=skip,
                    count=MOOV_COUNT_PAGE_SIZE,
                    status=transfer_status,
                )
            )

            if not isinstance(batch, list):
                break
            total += len(batch)
            if len(batch) < MOOV_COUNT_PAGE_SIZE:
                return total

    logger.warning(
        "Moov transfer count for status=%s hit the %s-page cap; reporting %s "
        "(the true total may be higher).",
        transfer_status,
        MOOV_COUNT_MAX_PAGES,
        total,
    )
    return total


def payment_tab_transfer_counts(company):
    """Return ``(pending, canceled)`` for a company's Moov-backed payment tabs.

    Falls back to the local mirror when Moov is unreachable, so a Moov outage
    degrades the badges instead of breaking the whole payment screen.
    """
    moov_account = MoovAccountSettings.objects.filter(company=company).first()
    if moov_account is None or not moov_account.moov_account_uid:
        return 0, 0

    try:
        return (
            count_moov_transfers(moov_account.moov_account_uid, "pending"),
            count_moov_transfers(moov_account.moov_account_uid, "canceled"),
        )
    except Exception:
        logger.warning(
            "Moov transfer counts unavailable for company %s; falling back "
            "to the local mirror (counts may lag Moov).",
            getattr(company, "uid", company),
            exc_info=True,
        )
        local = MoovTransfers.objects.filter(company=company)
        return (
            local.filter(status=MoovTransferStatusChoices.PENDING).count(),
            local.filter(status=MoovTransferStatusChoices.CANCELED).count(),
        )
