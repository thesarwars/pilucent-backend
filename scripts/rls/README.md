# Row-Level Security (RLS) — operations guide

Multi-tenant data isolation is enforced at two layers:

1. **Application** — every tenant query filters by the active company
   (`request.user.get_active_company()`), which is resolved from the JWT
   `company_id` claim by `TenantContextMiddleware`.
2. **Database (RLS)** — PostgreSQL policies restrict each row to the company in
   `current_setting('app.company_id')`, which the same middleware sets per
   request. This is the backstop if an application query ever forgets to filter.

The policies are created by the migration
`companyio/migrations/0023_enable_rls_core_tables.py` (Postgres-only; a no-op on
the sqlite test database). The policy is **permissive when no company is in
context** — see `common/db/rls.py` for the exact predicate and rationale.

## ⚠️ Required ops step: the app must connect as a restricted role

**RLS has no effect while the application connects as a PostgreSQL superuser or
a role with `BYPASSRLS`.** Today the app connects as `postgres_dev`
(`master/settings.py` → `DATABASES`), which on RDS is a superuser — so even with
the policies in place, isolation is **not** enforced until the connection role
is switched.

Create a dedicated, restricted role and point the app at it:

```sql
-- Run once, as an admin/superuser, against each environment's database.
CREATE ROLE balanzify_app LOGIN PASSWORD 'CHANGE_ME';

-- Explicitly ensure it cannot bypass RLS (default, but be explicit):
ALTER ROLE balanzify_app NOBYPASSRLS;

-- It must NOT be a superuser (superusers bypass RLS):
ALTER ROLE balanzify_app NOSUPERUSER;

-- Grant the privileges the app needs.
GRANT CONNECT ON DATABASE balanzify_dev TO balanzify_app;
GRANT USAGE ON SCHEMA public TO balanzify_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO balanzify_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO balanzify_app;

-- Make future tables/sequences (created by later migrations) inherit the grants.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO balanzify_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO balanzify_app;
```

Then set `DATABASES["default"]["USER"]`/`PASSWORD` (ideally via env vars) to
`balanzify_app` and redeploy.

### Verifying isolation

```sql
-- As balanzify_app:
SET app.company_id = '1';
SELECT count(*) FROM customerio_customer;   -- only company 1's rows
SET app.company_id = '2';
SELECT count(*) FROM customerio_customer;   -- only company 2's rows
RESET app.company_id;                        -- permissive (app-level filtering)
```

### Migrations & schema changes

Run `migrate`/`makemigrations` as the **owner/admin** role (not `balanzify_app`),
since DDL and `FORCE ROW LEVEL SECURITY` require ownership. Only the runtime app
connects as the restricted role.

### Expanding coverage

`0023_enable_rls_core_tables.py` covers the core data tables. To extend RLS to
more tables, add their `db_table` names to a follow-up migration using
`common.db.rls.enable_rls_for_tables`. Do **not** add the membership/identity
tables (`companyio_companyuser`, `companyio_companyinvitation`,
`employeeio_employee`) until their cross-company reads in the
select/switch/join-by-code flows are made to run with the GUC cleared —
otherwise switching/joining companies will break.
```
