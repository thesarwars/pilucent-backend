"""Backfill `is_money_account` from the two account types the seed calls money.

`categoryio/management/commands/data/chart_of_accounts.py` defines exactly two
account-type categories that money moves through:

    "Bank"          -> Cash on hand, Checking, Money Market, Rents Held in
                       Trust, Savings, Trust account, Cash & Cash Equivalents
    "Credit Cards"  -> Credit Card

Both are included. The existing de-facto check in the product matches only
`"Bank"` (`weapi/django_rest/views/dashboards/v1/dashboards.py:113`), which
omits credit cards -- a card is a money account by any accounting definition,
and the register spec treats it as one with inverted presentation.

Also flags anything carrying a Plaid `bank_id`. An account linked to a real
institution is a money account whatever its category says, and this is the one
piece of evidence that does not depend on the taxonomy being filled in -- which
matters because the taxonomy is nullable and legacy rows predate it.

Deliberately conservative in three ways:

- Accounts whose `account_type` is NULL and which carry no `bank_id` stay
  False. There is nothing to infer from, and a tenant can set the flag.
- Nothing is un-set. This only ever turns the flag on, so re-running it cannot
  strip a flag somebody set by hand.
- **Existing misuse is not treated as evidence.** Accounts already pointed at by
  a `BankReconciliation` or a `BankDeposit` are NOT flagged: half the
  reconciliations on production target an expense account, and inferring from
  that would launder exactly the mistake this field exists to stop.

The reverse drops every flag, which is correct for a backfill: it restores the
pre-migration state exactly, since the column did not exist before 0046.
"""

from django.db import migrations
from django.db.models import Q

MONEY_ACCOUNT_TYPE_TITLES = ("Bank", "Credit Cards")


def set_money_accounts(apps, schema_editor):
    ChartOfAccount = apps.get_model("accounts", "ChartOfAccount")
    ChartOfAccount.objects.filter(
        Q(account_type__title__in=MONEY_ACCOUNT_TYPE_TITLES)
        | (Q(bank_id__isnull=False) & ~Q(bank_id=""))
    ).update(is_money_account=True)


def clear_money_accounts(apps, schema_editor):
    ChartOfAccount = apps.get_model("accounts", "ChartOfAccount")
    ChartOfAccount.objects.update(is_money_account=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0046_chartofaccount_is_money_account"),
    ]

    operations = [
        migrations.RunPython(set_money_accounts, clear_money_accounts),
    ]
