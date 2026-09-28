from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from .base import DashboardCardView
from weapi.django_rest.helpers.dashboard import finance


class PrivateWeDashboardBankBalancesView(DashboardCardView):
    """Card 13 — Bank Balances.

    Returns just the ``bankAccounts`` list. ``masked`` is derived from the last
    4 of the Plaid ``bank_id`` (there is no stored account number), and ``sync``
    is approximated from the latest bank-feed transaction on the account (no
    real sync timestamp is modeled). Error/restricted states are still emitted
    as envelopes by the base view.
    """

    card_key = "bank_balances"
    action_route = "/banking/accounts"

    @staticmethod
    def _mask(bank_id):
        if not bank_id:
            return None
        return f"•••• {str(bank_id)[-4:]}"

    @staticmethod
    def _relative_sync(dt, now):
        if dt is None:
            return "Synced"
        seconds = (now - dt).total_seconds()
        if seconds < 60:
            return "Just now"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes} min ago"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hour" + ("s" if hours != 1 else "") + " ago"
        days = int(hours // 24)
        if days < 30:
            return f"{days} day" + ("s" if days != 1 else "") + " ago"
        return dt.strftime("%b %d")

    def get_card_data(self, request, filters):
        now = timezone.now()
        accounts = finance.bank_accounts_qs(filters.company).annotate(
            last_txn=Max("transactioninformation__created_at")
        )

        bank_accounts = []
        for account in accounts:
            balance = account.opening_balance or Decimal("0.00")
            bank_accounts.append(
                {
                    "name": account.title,
                    "masked": self._mask(account.bank_id),
                    "amount": f"${float(balance):,.2f}",
                    "sync": self._relative_sync(account.last_txn, now),
                }
            )

        return {"bankAccounts": bank_accounts}
