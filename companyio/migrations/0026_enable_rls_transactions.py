"""Bring the five tenant-owning `transactionio` tables under Row-Level Security.

BR-27. `0023_enable_rls_core_tables` covered customer, product, sale, purchase
and chart of account; `0025` added supplier. The banking tables were on neither
list, and they hold the material the reconciliation work has spent this phase
making authoritative: imported statement lines, reconciliation sessions,
deposits, and the rules that categorise a feed.

Five of the eight tables in the app carry `company_id` and are covered here:

    transactionio_transactioninformation    imported statement lines
    transactionio_bankreconciliation        reconciliation sessions
    transactionio_bankdeposit               deposits
    transactionio_transactionrules          feed categorisation rules
    transactionio_transactionmethod         payment methods

The other three do not carry a tenant key and are deliberately left out:
`bankdeposititem`, `transactionruleparams` and `transactionruleassign` are
reached through their parent, so a join inherits the parent's policy. Giving
them a bespoke policy through a join would be a different and much more
expensive predicate; the builders in `common/db/rls.py` only emit SQL for the
`company_id` convention, and that is the right boundary.

**This is a backstop, not the guard.** The policy is deliberately permissive
whenever `app.company_id` is unset -- login, company switching, management
commands, migrations -- so it cannot substitute for application-level scoping,
and the serializer-layer fixes shipped through Phases 0-4 remain the primary
defence. Each covers the other's gap: a scoping mixin can be forgotten on the
next serializer someone writes, and RLS is inert outside a company-scoped
request.

Worth recording why this is worth doing anyway, given that: `TransactionRules`
was written to by uid with no company predicate until `8c957acb`, and the
reconciliation endpoints resolved another tenant's account until `7f4ee89c`.
Both were application-layer holes on tables that had no database-layer policy
behind them.

Additive and reversible, using the same builders as the other six tables so
there is one definition of tenant isolation in the schema rather than several.
"""

from django.db import migrations

from common.db.rls import disable_rls_for_tables, enable_rls_for_tables

RLS_TABLES = [
    "transactionio_transactioninformation",
    "transactionio_bankreconciliation",
    "transactionio_bankdeposit",
    "transactionio_transactionrules",
    "transactionio_transactionmethod",
]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(enable_rls_for_tables(RLS_TABLES))


def remove_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(disable_rls_for_tables(RLS_TABLES))


class Migration(migrations.Migration):

    dependencies = [
        ("companyio", "0025_enable_rls_supplier"),
        ("transactionio", "0017_bankreconciliation_closed_by"),
    ]

    operations = [
        migrations.RunPython(apply_rls, remove_rls),
    ]
