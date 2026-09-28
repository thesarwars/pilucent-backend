"""Session integrity, part 1: make the two identifying FKs required. BR-16.

`BankReconciliation` had no `Meta` at all, so nothing in the schema stopped:

- two sessions on the same account and the same statement date, each ticking a
  different half of the same activity and each closing at a difference of zero;
- a row reading `is_closed=True` with `reconciled_on` NULL, indistinguishable
  from one somebody closed by hand;
- a forced close with no reason and no recorded difference, indistinguishable
  from a clean one after the fact -- which is the entire point of recording it.

`bank_account` and `company` were both nullable, and `__str__` dereferenced
`bank_account.title` unguarded, so a row missing it crashed the admin
changelist. A reconciliation without an account or a company is not a
partially-filled record; it is a row nothing can interpret.

The three constraints that go with this are in 0016, generated from the model so
their expressions cannot drift from it.

**Safe to tighten without a backfill or a one-off default: the table is empty.**
Measured read-only on production 2026-08-25 after the database cleanup --
`BankReconciliation` 0 rows. Written by hand rather than generated because
`makemigrations` prompts interactively for a default when a nullable FK becomes
non-nullable, and there is no row that needs one.

Reversible: the constraints drop and the columns go back to nullable.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0047_backfill_is_money_account"),
        ("companyio", "0025_enable_rls_supplier"),
        ("transactionio", "0014_bankreconciliation_forced_difference_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bankreconciliation",
            name="bank_account",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reconciliations",
                to="accounts.chartofaccount",
            ),
        ),
        migrations.AlterField(
            model_name="bankreconciliation",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="companyio.company",
            ),
        ),
    ]
