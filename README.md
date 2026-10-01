# Pilucent Backend

**Pilucent** is a multi-tenant accounting, ERP, and US payroll SaaS platform. This
repository is the backend — a **Django 5.1 + Django REST Framework** service that
powers a double-entry general ledger, sales/purchasing, inventory, HR & payroll,
US tax compliance, banking, subscriptions, and real-time collaboration behind one
versioned REST API.

`Django 5.1` · `DRF` · `PostgreSQL (Row-Level Security)` · `Celery` · `Channels/WebSockets` · `Redis` · `S3` · `Docker`

---

## Table of Contents

- [Platform Highlights](#platform-highlights)
- [Feature Map](#feature-map)
- [Tech Stack](#tech-stack)
- [Architecture at a Glance](#architecture-at-a-glance)
- [Running with Docker](#running-with-docker)
- [Configuration (`.env`)](#configuration-env)
- [API Documentation](#api-documentation)
- [Background Jobs & Realtime](#background-jobs--realtime)
- [Common Operations](#common-operations)
- [Project Layout](#project-layout)
- [Notes & Gotchas](#notes--gotchas)

---

## Platform Highlights

- **True multi-tenancy via PostgreSQL Row-Level Security.** Every request carries a
  signed `company_id` JWT claim; middleware sets the Postgres `app.company_id` GUC and
  the database itself enforces per-company isolation (the app runs as a restricted,
  non-superuser role so RLS can't be bypassed).
- **Double-entry general ledger.** Every sale, bill, payroll run, tax posting, and bank
  deposit posts balanced debit/credit lines back to a Chart of Accounts, with full
  source-document linkage.
- **Append-only inventory ledger with FIFO costing.** Stock is tracked as immutable
  movements with per-lot FIFO consumption and signed COGS — not mutated-in-place quantities.
- **US payroll & tax compliance built in.** Payroll runs, statutory federal/state tax
  tables, W-4/I-9, Moov ACH payouts, and electronic **Form 940 / 941** filing via TaxBandits.
- **Bank connectivity + AI categorization.** Plaid bank/transaction sync, rules engine,
  reconciliation, and LLM-assisted transaction categorization (Groq).
- **Real-time collaboration.** WebSocket-backed team chat and expense-approval rooms
  over Django Channels.
- **SaaS billing.** Stripe-backed subscription plans, entitlements, trials/dunning,
  coupons, referrals, and add-ons.
- **Versioned API surface** for the web workspace (`/we`), employee self-service (`/me`),
  admin (`/adminio`), and the public marketing site (`/public`).

---

## Feature Map

The backend is composed of ~45 domain apps (`*io` = an "input/output" domain module).
Grouped by capability:

### Accounting & Finance

| Module | Domain | What it does |
|---|---|---|
| `journalio` | General Ledger | Double-entry GL: balanced debit/credit lines, running balances, source-document linkage. |
| `accounts` | Chart of Accounts + Users | Custom email-login `User` model and the GL Chart of Accounts (kinds, balances, currency). |
| `salesio` | Sales & Receivables | Invoices, estimates, sale receipts, cash application, per-agency sales-tax periods. |
| `purchaseio` | Purchases & Payables | Bills, purchase orders, expenses, supplier payments, pay-bill settlement. |
| `paymentio` | Payments | Company payment methods and Stripe payment-intent/invoice records. |
| `creditnoteio` | Credit Notes | Customer/supplier credit notes with balance-consumption tracking. |
| `transactionio` | Banking & Reconciliation | Bank-feed lines, auto-categorization rules engine, bank deposits, statement reconciliation. |
| `recurringio` | Recurring Transactions | Scheduled templates that auto-generate bills, expenses, cheques, estimates, refund receipts. |
| `currencyio` | Multi-currency / FX | Per-company currencies + exchange rates attached across documents. |
| `agencyio` | Sales-Tax Agencies | Tax agencies, filing frequencies/periods, combined-rate tax sets, tax-owed reporting. |

### Inventory & Catalog

| Module | Domain | What it does |
|---|---|---|
| `productio` | Product Catalog | Products/services, bundles/kits, pricing/VAT, landed cost, GL account links. |
| `stockio` | Inventory & Stock Ledger | Append-only stock movements, FIFO lot consumption, adjustments, reorder/expiry alerts. |
| `categoryio` | Categorization | Hierarchical company-scoped category taxonomy. |
| `wirehouseio` | Warehouses | Warehouse/location records referenced by inventory movements. |
| `brandio` | Brands | Product brands and product associations. |
| `supplierio` | Suppliers / Vendors (AP) | Vendor master: contacts, currency, balances, credit-note aggregation. |
| `customerio` | Customers (AR) | Customer master: contacts, opening balances, GL links, issued invoices. |
| `tagio` | Tagging | Polymorphic tags across transactions and catalog entities. |

### HR, Payroll & Workforce

| Module | Domain | What it does |
|---|---|---|
| `employeeio` | Employee Records | Employee master + pay, tax (W-4), banking, deductions, garnishments, expense reports (OCR). |
| `payrollio` | Payroll Processing | Payroll runs, pay schedules, GL mappings, US federal/state statutory tax tables. |
| `attendanceio` | Time & Attendance | Daily attendance, time-tracking sessions, punch data, holiday calendars, batch runs. |
| `leaveio` | Leave Management | Leave policies, balances/allocations, request-approval workflow, encashment. |

### Money Movement & Tax Compliance

| Module | Domain | What it does |
|---|---|---|
| `moovmoneyio` | ACH Payouts (Moov) | Links company/employee bank accounts and executes ACH transfers — primarily payroll payouts. |
| `taxbanditsio` | Payroll Tax E-Filing | Registers the business payer and e-files **Form 940 / 941** via TaxBandits. |
| `nexusio` | Sales-Tax Nexus | Monitors sales vs per-state economic-nexus thresholds; approaching/crossed alerts. |

### Tenancy, Identity & Access

| Module | Domain | What it does |
|---|---|---|
| `companyio` | Company & Org Structure | The `Company` tenant, membership, invitations, departments/sections/designations/shifts, settings. |
| `adminio` | Roles & Permissions | Per-company RBAC roles bundling Django permissions (protected system roles). |
| `subscriptionio` | Subscriptions & Billing | Plans/features, Stripe prices, subscription lifecycle, invoices, coupons, add-ons. |
| `socailauthio` | Social Auth | Google OAuth login/callback (stateless glue, no models). |
| `sessionio` | Audit Trail | Create/update/delete/recover change log for sale & purchase documents. |
| `addressio` | Address Book | Shared address store with a polymorphic connector across entities. |
| `termio` | Payment Terms | Net-days payment terms attached to customers/suppliers/sales/purchases. |

### Platform & Collaboration

| Module | Domain | What it does |
|---|---|---|
| `chatio` | Team Chat | Real-time WebSocket DMs and multi-role rooms with expense-approval workflows. |
| `notificationio` | Notifications | Per-user/company notifications tied to sales, purchases, payments, stock, nexus. |
| `messageio` | Support Ticketing | Ticket inbox with threaded replies and attachments. |
| `attachmentio` | Attachments | Company-scoped image/link attachments. |
| `fileroomio` | Document Store | Central file repository polymorphically linked to any business record. |
| `datamigrationio` | Data Import | Spreadsheet import jobs: mapping, validation, dedupe, accounting-impact preview. |
| `livedemoio` | Demo Requests | Captures prospect live-demo/contact leads with scheduling + email state. |
| `common` | Base / Tenancy | Abstract base models, tenant context, DB routing, shared choices (foundational, no concrete models). |

### API Layers

| Module | Mount | Audience |
|---|---|---|
| `weapi` | `/api/v1/we`, `/api/v2/we` | Primary workspace ERP API — the full accounting/inventory/HR/payroll/tax/billing surface. |
| `meapi` | `/api/v1/me` | Employee self-service: own profile, time tracking, assigned shift, notifications. |
| `adminio` (API) | `/api/v1/adminio`, `/api/v2/adminio` | Admin endpoints. |
| `chatio` (API) | `/api/v1/chat` | Chat room CRUD (message stream over WebSocket). |
| `publicapi` | `/api/v1/public`, `/api/v2/public` | Unauthenticated marketing/catalog data (plans, pricing, demo intake, categories). |

> **Placeholder modules:** `invoiceio` (invoicing lives in `salesio`), `receiptio`, and
> `hris` are scaffolds with no active models yet.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language / Framework | Python 3.12, **Django 5.1.1**, **Django REST Framework 3.15.2** |
| API server | **Gunicorn** managing **Uvicorn ASGI workers** (`master.asgi`), bound to `:5000` |
| Realtime | **Django Channels 4.3** + `channels-redis` (WebSockets for `chatio`) |
| Async jobs | **Celery 5.4** (Redis broker, results in Postgres via `django-celery-results`) |
| Database | **PostgreSQL** with **Row-Level Security** multi-tenancy (`psycopg` 3) |
| Cache / broker / channel layer | **Redis 7** |
| Auth | **SimpleJWT** (Bearer), Google OAuth2, `django-otp` (TOTP 2FA) |
| Object storage | **AWS S3** via `django-storages` + `boto3`; `whitenoise` for static |
| Docs | **drf-spectacular** (OpenAPI/Swagger) + `drf-yasg` |
| Audit / profiling | `django-auditlog`, `django-simple-history`, `django-silk` (DEBUG-only) |
| PDF / OCR | `weasyprint`, `pdfplumber`, `pdf2image`, `pymupdf`, `pytesseract`, `opencv` |
| Integrations | **Plaid** (banking), **Moov** (ACH payouts), **Stripe** (billing), **TaxBandits** (tax filing), **Groq** (AI categorization) |

---

## Architecture at a Glance

- **Request → tenant scoping.** `TenantContextMiddleware` decodes the JWT, reads the
  signed `company_id` claim, and sets the Postgres session variable `app.company_id`.
  RLS policies read `current_setting('app.company_id')`, so isolation is enforced by the
  database, not just the ORM. The GUC is always cleared in `finally`.
- **DB roles matter.** The app connects as the restricted, DML-only role `pilucent_app`
  (a superuser would bypass RLS). Migrations run as a separate owner role — see
  [Notes & Gotchas](#notes--gotchas).
- **ASGI everywhere.** HTTP and WebSockets share the `master.asgi` app via
  `ProtocolTypeRouter`; WebSocket connections are JWT-authenticated by middleware.
- **Worker recycling by design.** Gunicorn `--max-requests` (web) and Celery
  `--max-tasks-per-child` (jobs) recycle workers to reclaim DB connections/memory —
  a deliberate guard given a low RDS `max_connections`.

---

## Running with Docker

> Docker is the supported way to run this project. You only need **Docker** (with the
> Compose plugin).

There are two compose files:

| File | For | Database |
|---|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Local development | Postgres in the stack |
| [`docker-compose.prod.yml`](docker-compose.prod.yml) | Production ([`scripts/deploy.sh`](scripts/deploy.sh)) | Managed Postgres from `.env` |

### Local development

```bash
git clone git@github.com:thesarwars/pilucent-backend.git
cd pilucent-backend
docker compose up --build            # builds, migrates, starts everything
docker compose run --rm app python manage.py seed_bd_rule_book
docker compose run --rm app python manage.py createsuperuser
```

The database name, app role and password come from `.env` (`DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_PORT`); without one, built-in dev defaults apply. Inside the stack the
host is always the `db` service, so `.env` can never point the containers at a remote
database. With `DB_HOST=localhost` in `.env`, `manage.py` run on the host reaches the same
Postgres. Third-party keys (email, Google, Moov, ...) are read from `.env` too.

| Service | Purpose | Host port |
|---|---|---|
| `db` | Postgres 16. Owner role `pilucent` (runs migrations); the app role from `DB_USER` (DML only, so Row-Level Security is enforced) — created by [`docker/postgres/init`](docker/postgres/init) | **`DB_PORT` (5432)** |
| `redis` | Celery broker + Channels layer | **6381** |
| `migrate` | One-off: applies migrations as the owner, then exits | — |
| `app` | `runserver` (ASGI, HTTP + WebSocket) | **8000** |
| `celery` / `celery_beat` | Background worker and scheduler | — |

The API is at **http://127.0.0.1:8000** and docs at **http://127.0.0.1:8000/api/docs/**.
Files are stored under `media/` locally (S3 only when `AWS_STORAGE_BUCKET_NAME` is set).
Ports can be moved with `DB_PORT`, `PILUCENT_APP_PORT`, `PILUCENT_REDIS_PORT`. The app
role is created when the database volume is first made, so after changing `DB_USER` or
`DB_PASSWORD` run `docker compose down -v` (this wipes the local database).

### Production

```bash
cp env_sample.txt .env      # fill in DB_*, SECRET_KEY, AWS_STORAGE_BUCKET_NAME, domains
docker compose -f docker-compose.prod.yml up --build -d
```

`app` runs Gunicorn + Uvicorn ASGI workers on **5000**, with `celery`, `celery_beat` and
`redis`. Migrations are run by `scripts/deploy.sh` as the database owner.

---

## Configuration (`.env`)

`env_sample.txt` is intentionally minimal. The settings module reads more variables than
the sample lists — the important ones are called out below.

**Core**
```
DEBUG=True
SECRET_KEY=...
```

**Brand and public endpoints** (all optional; pilucent.com defaults)
```
PRODUCT_NAME=Pilucent
PUBLIC_API_URL=https://api.pilucent.com
APP_URL=https://app.pilucent.com
SELF_SERVICE_URL=https://me.pilucent.com
SUPPORT_EMAIL=support@pilucent.com
DEFAULT_FROM_EMAIL=no-reply@pilucent.com
BRAND_LOGO_URL=... / BRAND_ICON_URL=...
CORS_ALLOWED_ORIGINS=... / CSRF_TRUSTED_ORIGINS=...   # comma-separated
```

**Database (PostgreSQL)**
```
DB_NAME=pilucent
DB_USER=pilucent_app   # the restricted runtime role
DB_PASSWORD=...
DB_HOST=...            # no default host: it must be set
DB_PORT=5432
DB_SSLMODE=require     # 'disable' for a local Postgres without TLS
```

**Redis / Celery** (needed for the `celery` worker and Channels)
```
CELERY_BROKER_URL=redis://redis:6379/0   # (older name: redis_local_server)
REDIS_HOST=redis / REDIS_PORT=6379       # Channels layer
```

**Email (SMTP)**
```
EMAIL_HOST=...
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
```

**Google OAuth2**
```
GOOGLE_OAUTH2_CLIENT_ID=...
GOOGLE_OAUTH2_CLIENT_SECRET=...
GOOGLE_OAUTH2_PROJECT_ID=...
```

**Integrations** (set the ones you use)
```
# Moov (ACH payouts)
MOOV_USERNAME=... / MOOV_PASSWORD=... / MOOV_ACCOUNT_UID=... / MOOV_ORIGIN=... / MOOV_WEBHOOK_SECRET=...
# Stripe (subscription billing)
STRIPE_SECRET_KEY=... / STRIPE_PUBLISHABLE_KEY=... / STRIPE_WEBHOOK_SECRET=...
# TaxBandits (payroll tax e-filing)
TAXBANDITS_DOMAIN_REFERENCE_ID=...
```

> **Secrets hygiene:** never commit real credentials. Every key and password is read from
> the environment; `master/settings.py` holds no secret values.

---

## API Documentation

| URL | What |
|---|---|
| `http://127.0.0.1:5000/api/docs/` | Swagger UI (drf-spectacular) |
| `http://127.0.0.1:5000/api/schema` | Raw OpenAPI schema |
| `http://127.0.0.1:5000/admin/` | Django admin |

Top-level API namespaces:

| Prefix | App | Notes |
|---|---|---|
| `/api/v1` | `socailauthio` | Google OAuth login |
| `/api/v1/accounts` | `accounts` | User account APIs |
| `/api/v1/me` | `meapi` | Employee self-service |
| `/api/v1/we`, `/api/v2/we` | `weapi` | Main workspace ERP API |
| `/api/v1/adminio`, `/api/v2/adminio` | `adminio` | Admin APIs |
| `/api/v1/chat` | `chatio` | Chat rooms (WebSocket stream) |
| `/api/v1/public`, `/api/v2/public` | `publicapi` | Public/unauthenticated |

Authenticate by sending `Authorization: Bearer <access_token>` (SimpleJWT). The access
token embeds the `company_id` claim that drives tenant scoping.

---

## Background Jobs & Realtime

- **Celery** (`celery` / `celery_beat` services) runs recurring/async work —
  recurring-transaction generation, notifications, tax/payroll processing, imports.
  Broker is Redis (`CELERY_BROKER_URL`); results are stored in Postgres.
- **Channels/WebSockets** power `chatio`. The `app` container serves both HTTP and
  WebSocket traffic through the same ASGI process; Redis is the channel layer.

---

## Common Operations

Local stack (add `-f docker-compose.prod.yml` for production):

```bash
# Apply migrations (runs as the owner role)
docker compose run --rm migrate

# Create an admin user
docker compose exec app python manage.py createsuperuser

# Collect static files (S3 in production)
docker compose exec app python manage.py collectstatic --noinput

# Tail logs
docker compose logs -f app
docker compose logs -f celery

# Open a shell in the container
docker compose exec app bash

# Stop / rebuild
docker compose down
docker compose up --build -d
```

---

## Project Layout

```
master/            Django project: settings, urls, asgi/wsgi, storages, celery app
common/            Base models, tenant middleware, DB routing, shared choices
accounts/          User model + Chart of Accounts
companyio/         Company tenant, org structure, membership, settings
weapi/  meapi/  publicapi/  adminio/    REST API layers (versioned)
journalio/ salesio/ purchaseio/ paymentio/ creditnoteio/ transactionio/
recurringio/ currencyio/ agencyio/         Accounting & finance
productio/ stockio/ categoryio/ wirehouseio/ brandio/ supplierio/ customerio/ tagio/
                                             Inventory & catalog
employeeio/ payrollio/ attendanceio/ leaveio/    HR & payroll
moovmoneyio/ taxbanditsio/ nexusio/        Money movement & tax compliance
chatio/ notificationio/ messageio/ attachmentio/ fileroomio/ datamigrationio/ livedemoio/
                                             Platform & collaboration
```

---

## Notes & Gotchas

- **Migrations run as a different DB role.** The app's runtime role (`pilucent_app`) is
  intentionally DML-only and **cannot run migrations**. Apply migrations with a role that
  owns the schema (configure a separate `.env`/connection for migration runs, or run them
  as the DB owner), otherwise `migrate` will fail with a permissions error.
- **RLS requires a non-superuser role.** Connecting as a Postgres superuser silently
  bypasses Row-Level Security and breaks tenant isolation — always use the restricted
  role for the app.
- **`django-silk` is DEBUG-only.** Profiling (`/profiling`) is enabled only when
  `DEBUG=True`; it's disabled in production because its per-request DB writes add load.
- **Local Redis is published on 6381** to avoid clashing with a Redis already on the
  machine; Postgres uses `DB_PORT` from `.env`.
