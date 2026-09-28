"""Helpers to build PostgreSQL Row-Level Security (RLS) statements.

The tenant policy is intentionally **permissive when no company is in context**:

    USING (
        current_setting('app.company_id', true) IS NULL
        OR current_setting('app.company_id', true) = ''
        OR company_id = NULLIF(current_setting('app.company_id', true), '')::int
    )

Rationale (phased rollout):
  * Inside a company-scoped request the tenant middleware sets
    ``app.company_id``, so the DB hard-restricts every row to that company --
    even if an application query forgets its ``.filter(company=...)``. This is
    the belt-and-suspenders guarantee.
  * Outside a scoped request (login, company selection/switch, management
    commands, migrations) the GUC is unset and the policy is permissive, so
    those flows keep working and rely on the existing application-level
    filtering. This avoids breaking cross-company reads that legitimately
    happen while no single company is selected.

We ``ENABLE`` *and* ``FORCE`` RLS so the policy also applies to the table owner;
note a Postgres superuser still bypasses RLS entirely, which is why the app must
connect as the restricted, non-BYPASSRLS role documented in scripts/rls/.

These builders only emit SQL for the ``company_id`` column convention; tables
whose tenant key is named differently need a bespoke policy.
"""

TENANT_GUC = "app.company_id"
POLICY_NAME = "tenant_isolation"

_PREDICATE = (
    "current_setting('{guc}', true) IS NULL "
    "OR current_setting('{guc}', true) = '' "
    "OR {col} = NULLIF(current_setting('{guc}', true), '')::int"
).format(guc=TENANT_GUC, col="company_id")


def enable_rls_sql(table):
    """SQL to enable+force RLS and (re)create the tenant policy on ``table``."""
    return (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table};\n"
        f"CREATE POLICY {POLICY_NAME} ON {table}\n"
        f"    USING ({_PREDICATE})\n"
        f"    WITH CHECK ({_PREDICATE});\n"
    )


def disable_rls_sql(table):
    """SQL to drop the tenant policy and disable RLS on ``table`` (reverse)."""
    return (
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table};\n"
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;\n"
    )


def enable_rls_for_tables(tables):
    return "\n".join(enable_rls_sql(t) for t in tables)


def disable_rls_for_tables(tables):
    return "\n".join(disable_rls_sql(t) for t in tables)
