"""Enable PostgreSQL Row-Level Security on the core tenant data tables.

Phased rollout (see common/db/rls.py for the policy and rationale): we start
with the high-volume business-data tables that are only ever read within a
single company's scope. We deliberately exclude the membership/identity tables
(companyuser, companyinvitation, employee) because the workspace
select/switch/join flows legitimately read another company's rows while the
request is still scoped to the previous company; RLS there would break them.
Those can be added once their cross-company reads run with the GUC cleared.

This migration is a no-op on non-PostgreSQL backends (e.g. the sqlite test DB),
so the policy SQL never runs where RLS is unsupported.

NOTE: RLS only takes effect once the application connects as a non-superuser,
non-BYPASSRLS role (a Postgres superuser bypasses RLS). See scripts/rls/.
"""

from django.db import migrations

from common.db.rls import disable_rls_for_tables, enable_rls_for_tables

# Pure tenant data tables (each has a company_id column) safe for RLS today.
RLS_TABLES = [
    "customerio_customer",
    "productio_product",
    "salesio_sale",
    "purchaseio_purchase",
    "accounts_chartofaccount",
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
        ("companyio", "0022_companyinvitation"),
        ("customerio", "0008_customer_charter_account"),
        ("productio", "0010_alter_productadditionalcost_prefferred_supplier_and_more"),
        ("salesio", "0037_alter_saleitem_is_tax"),
        ("purchaseio", "0023_alter_paybill_email_alter_purchase_email_and_more"),
        ("accounts", "0041_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(apply_rls, remove_rls),
    ]
