# Subscription v2 — Super Admin & WE Backend (Session Summary)

**Date:** June 8, 2026  
**Branch:** `sarwars` → merged via PR [#850](https://github.com/thesarwars/balanzify_backend/pull/850)  
**Reference:** Full API catalog in [`SUBSCRIPTION_ENGINE.md`](./SUBSCRIPTION_ENGINE.md)

This document summarizes the subscription v2 backend work completed in this session, focused on Super Admin (`/api/v2/adminio/subscriptions`) and supporting WE (`/api/v2/we/subscriptions`) endpoints.

---

## Phase overview

| Phase | Commit | Summary |
|-------|--------|---------|
| **P0** | `89d9a1cb` | Super Admin core: plans list, tenants, invoices, draft matrix |
| **P1** | `b8205bc8` | Referrals, trials, analytics, audit logs |
| **P2** | `8fef441c` | Coupon enhancements + public v2 pricing API |
| **P3** | `acc23569` | Add-on catalog (`SubscriptionAddOn`) + admin CRUD |
| **P4** | `351e7db8` | Add-ons runtime: WE purchase, billing preview, Stripe checkout |
| **P5** | `887c783a` | Plan v2 CRUD + plan version add-on linking |
| **P6** | `6ac0d728` | Account credits on billing + program settings enforcement |
| **P7** | `6e910b94` | Offers runtime + referral reward visibility |
| **P8** | `aef3972f` | Billable metrics admin API, proration, scheduled downgrades |

**Today's session** delivered **P5 → P8** (four commits, merged in PR #850).

---

## P5 — Plan v2 CRUD & version add-on linking

### What was built

- **`AdminPlanCatalogService`** extended with:
  - `create_plan` / `update_plan` / `archive_plan`
  - `get_plan_version_addons` / `sync_plan_version_addons` (draft versions only)
  - Price upsert by `uid` for partial updates
- **Admin endpoints**

| Method | Path |
|--------|------|
| `GET/POST` | `/api/v2/adminio/subscriptions/plans` |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/plans/<uid>` |
| `GET/PUT` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/<version_uid>/addons` |

- Plan version **clone** now copies `PlanAddOn` links from the source version.

### Key files

- `subscriptionio/services/admin_plan_catalog_service.py`
- `subscriptionio/services/plan_version_service.py`
- `adminio/django_rest/views/subscriptions/v2/plans.py`
- `adminio/django_rest/views/subscriptions/v2/plan_versions.py`

---

## P6 — Account credits & program settings

### What was built

**Credits**

- New **`CreditService`** — FIFO balance lookup, preview application, ledger deduction.
- **Billing preview** includes `credit_total`, `available_credit_balance`, and a `CREDIT` line item.
- **Stripe checkout** applies credits as a one-time coupon; webhook deducts ledger on `checkout.session.completed`.
- **`billing/current`** exposes `available_credit_balance`.
- Preview accepts `apply_credits: false` to show totals without credits.

**Program settings enforcement** (`SubscriptionProgramSettings`)

| Setting | Enforced in |
|---------|-------------|
| `referral_program_active` | `ReferralService.validate` / `redeem` |
| `referral_max_per_month` | `ReferralService.validate` |
| `referral_reward_amount` | `ReferralService._reward_amount` |
| `trial_default_days` | `TrialService.start_trial`, Stripe checkout |
| `trial_card_required` | `TrialService.start_trial`, checkout `payment_method_collection` |
| `trial_one_per_domain` | `TrialService.get_status` / `start_trial` |
| `trial_max_extension_days` | `TrialService.extend_trial`, `AdminTrialService.extend_trial` |

### Key files

- `subscriptionio/services/credit_service.py` *(new)*
- `subscriptionio/services/billing_preview_service.py`
- `subscriptionio/services/trial_service.py`
- `subscriptionio/services/referral_service.py`
- `subscriptionio/services/stripe_checkout_service.py`
- `weapi/django_rest/helpers/stripe_webhook.py`

---

## P7 — Offers runtime & referral dashboard

### What was built

**Offers**

- New **`OfferService`** — validates offers via linked coupons, lists eligible offers, resolves `offer_code` → `coupon_code`.
- **Retention on cancel** — cancel response includes `retention_offers`; accept retention clears pending cancel and sets `applied_coupon`.
- New event type: `RETENTION_OFFER_ACCEPTED`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/we/subscriptions/promotions/offers` | Non-retention offers |
| `POST` | `/api/v2/we/subscriptions/promotions/validate-offer` | Validate offer → coupon |
| `GET` | `/api/v2/we/subscriptions/lifecycle/retention-offers` | Retention offers |
| `POST` | `/api/v2/we/subscriptions/lifecycle/accept-retention-offer` | Accept retention offer |

- Checkout and billing preview accept **`offer_code`**.

**Referral dashboard**

- `GET /api/v2/we/subscriptions/promotions/referral` expanded to return:
  - `code`, `program_active`, `reward_amount`
  - `summary` (pending/approved/rejected counts, earned + available credit)
  - `redemptions[]`, `credits[]`

### Key files

- `subscriptionio/services/offer_service.py` *(new)*
- `subscriptionio/services/referral_service.py`
- `subscriptionio/services/lifecycle_service.py`
- `weapi/django_rest/views/subscriptions/v2/promotions.py`
- `weapi/django_rest/views/subscriptions/v2/lifecycle.py`

---

## P8 — Metrics catalog, proration, scheduled downgrades

### What was built

**Admin billable metrics**

- New model: **`SubscriptionBillableMetric`**
- Auto-seeds 6 default metrics on first list (employees, users, branches, payroll runs, storage, AI credits).

| Method | Path |
|--------|------|
| `GET/POST` | `/api/v2/adminio/subscriptions/metrics` |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/metrics/<uid>` |

Response includes **enforcement mode reference** for the Super Admin UI.

**Proration**

- New **`ProrationService`** — mid-cycle plan change proration from remaining billing period fraction.
- Billing preview adds **`PRORATION`** line + `proration_total` when target plan differs from current subscription.

**Scheduled downgrades**

- New model: **`ScheduledPlanChange`**
- New **`PlanChangeService`** — preview, schedule, cancel, execute due changes.

| Method | Path |
|--------|------|
| `POST` | `/api/v2/we/subscriptions/plan-changes/preview` |
| `GET/DELETE` | `/api/v2/we/subscriptions/plan-changes/scheduled` |
| `POST` | `/api/v2/we/subscriptions/plan-changes/schedule-downgrade` |

- `billing/current` includes **`scheduled_plan_change`**.
- New events: `DOWNGRADE_SCHEDULED`, `DOWNGRADE_CANCELED`, `PLAN_CHANGE_EXECUTED`.

### Migration

```
subscriptionio/migrations/0021_p8_metrics_scheduled_changes.py
```

Creates `SubscriptionBillableMetric` and `ScheduledPlanChange`.

### Key files

- `subscriptionio/metric_models.py` *(new)*
- `subscriptionio/lifecycle_models.py` (ScheduledPlanChange)
- `subscriptionio/services/admin_metric_service.py` *(new)*
- `subscriptionio/services/proration_service.py` *(new)*
- `subscriptionio/services/plan_change_service.py` *(new)*
- `adminio/django_rest/views/subscriptions/v2/metrics.py`
- `weapi/django_rest/views/subscriptions/v2/plan_changes.py`

---

## Migrations (full stack)

Run on each environment:

```bash
python manage.py migrate subscriptionio
```

| Migration | Phase | Adds |
|-----------|-------|------|
| `0018` | P1 | `SubscriptionProgramSettings` |
| `0019` | P3 | `SubscriptionAddOn` catalog |
| `0020` | P4 | `PlanAddOn`, `CompanyAddOn` runtime |
| `0021` | P8 | `SubscriptionBillableMetric`, `ScheduledPlanChange` |

---

## Super Admin screen → API map (complete)

| Screen | Primary v2 APIs |
|--------|-----------------|
| Dashboard | analytics overview, revenue-trend, plan-distribution, trial-funnel, audit |
| Plans | plans CRUD, versions draft/publish/clone, add-on links, draft matrix |
| Add-ons | addons catalog CRUD |
| Feature matrix | features + PATCH plan version |
| Limits & metrics | **metrics catalog CRUD** *(P8)* |
| Tenant subscriptions | tenants list/detail/events/actions |
| Invoices & payments | invoices list/retry/refund, manual-invoices |
| Referrals | referrals settings/activity/approve-reject |
| Trials | trials settings/list/extend/convert |
| Audit logs | GET audit-logs |
| Coupons & offers | coupons/offers CRUD, redemptions |
| Enterprise | contracts CRUD, prices CRUD, plan migrations |

---

## Cron / ops checklist

Existing management commands:

```bash
python manage.py snapshot_subscription_usage
python manage.py expire_subscription_trials
python manage.py process_subscription_dunning
python manage.py seed_subscription_features
```

**Not yet wired:** cron command for `PlanChangeService.execute_due_scheduled_changes()` (scheduled downgrades from P8).

---

## Frontend implementation guide

What the **company app (WE)** and **Super Admin app** should build against the v2 APIs above. UI/visual spec: [`Super Admin - Design Spec & Prompt.md`](./Super%20Admin%20-%20Design%20Spec%20%26%20Prompt.md).

### Recommended build order

| Priority | Track | Deliverable |
|----------|-------|-------------|
| 1 | WE | Manifest-driven nav + paywall |
| 2 | WE | Subscription & Billing settings (overview, checkout v2) |
| 3 | WE | Plan change, credits, scheduled downgrade (P6–P8) |
| 4 | WE | Referral, offers, cancel/retention (P7) |
| 5 | Super Admin | Plans + feature matrix + metrics (P5, P8) |
| 6 | Super Admin | Tenants, invoices, referrals, trials, coupons |
| 7 | Public | Marketing pricing page (`/api/v2/public/subscription-plans`) |

---

### Company app (WE) — every session

**On login / company switch:**

1. `GET /api/v2/we/subscriptions/entitlements/access-manifest`
2. Store manifest in global state (Redux / Zustand / Context).
3. Use it to show/hide sidebar routes, dashboard cards, and pre-disable create actions.

Do **not** gate features from legacy `is_*` plan booleans alone — manifest is the source of truth.

**Status banners** (from `billing/current` or `lifecycle/state`):

| Condition | UI |
|-----------|-----|
| `status === TRIALING` | Banner: “X days left” |
| `PAST_DUE` / `GRACE` | Persistent billing alert; limit nav if manifest denies |
| `cancel_at_period_end === true` | “Cancels on {date}” + Reactivate CTA |
| `scheduled_plan_change` present *(P8)* | “Downgrading to {plan} on {date}” + Cancel scheduled change |
| `SUSPENDED` / `EXPIRED` | Full-page paywall; only billing/settings routes |

**Paywall / limit errors:**

- **403** entitlement denial → show `message` + `upgrade_metadata` → CTA to Subscription settings.
- **400** with `denied_by: "subscription_limit"` → inline error on employee/user create + upgrade CTA.

---

### Company app — Subscription & Billing page

Build a **Subscription & Billing** section (settings) with tabs:

#### Overview tab

**API:** `GET /api/v2/we/subscriptions/billing/current`

Display:

- Plan name, status badge, billing period start/end
- Usage meters (employees / users from `usage` + `limits`)
- Live cost from nested `preview` (subtotal, overage, add-ons, discounts, **credit**, **proration**, tax, total)
- **`available_credit_balance`** *(P6)* — show as “Account credit” if > 0
- **`addons.active`** — list purchased add-ons
- **`scheduled_plan_change`** *(P8)* — banner if scheduled downgrade exists

#### Change plan tab

**Flow:**

```
Pick target plan + employee/user counts
  → POST /api/v2/we/subscriptions/plan-changes/preview   (P8 — guardrails + proration)
  → POST /api/v2/we/subscriptions/billing/preview        (full line-item breakdown)
  → POST /api/v2/we/subscriptions/checkout               (Stripe redirect)
  → poll billing/current until ACTIVE | TRIALING
```

**Preview request body** (include new fields from P6–P7):

```json
{
  "plan_title": "Starter",
  "billing_frequency": "MONTHLY",
  "employee_count": 30,
  "user_count": 12,
  "coupon_code": "SAVE20",
  "offer_code": "WELCOME10",
  "addon_uids": ["<uuid>"],
  "apply_credits": true
}
```

**Preview line types to render:**

| `line_type` | Label |
|-------------|-------|
| `BASE` | Plan base |
| `OVERAGE` | Employee/user overage |
| `ADDON` | Add-on |
| `DISCOUNT` | Plan or coupon discount |
| `CREDIT` | Account credit *(P6)* |
| `PRORATION` | Plan change proration *(P8)* |
| `TAX` | Tax |

**Downgrade UX *(P8)*:**

- If `plan-changes/preview` returns `is_downgrade: true` and `allowed: false` → show `blockers` (usage vs included) and **do not** allow immediate checkout.
- If downgrade allowed → default action: **`POST /plan-changes/schedule-downgrade`** (changes at period end), not checkout.
- Show `requires_usage_reduction: true` warning when blockers exist but schedule is still offered.
- **`DELETE /plan-changes/scheduled`** to cancel a pending downgrade.

**Upgrade UX:**

- Use checkout v2 immediately; preview should show positive **`proration_total`** when mid-cycle.

#### Add-ons tab

| Action | API |
|--------|-----|
| List available + active | `GET /api/v2/we/subscriptions/addons` |
| Purchase | `POST /api/v2/we/subscriptions/addons/purchase` → redirect to Stripe if one-time |

Include selected add-ons in checkout/preview via `addon_uids` / `addon_quantities`.

#### Invoices tab

**API:** `GET /api/v2/we/subscriptions/billing/invoices`

Table: date, amount, status, link to `hosted_invoice_url` when present.

#### Promotions tab (coupons, offers, referral)

| Feature | API | UI |
|---------|-----|-----|
| Validate coupon | `POST .../promotions/validate-coupon` | Field on checkout; show discount in preview |
| Validate offer | `POST .../promotions/validate-offer` *(P7)* | Alternative to coupon; returns `coupon_code` |
| List offers | `GET .../promotions/offers` *(P7)* | Cards for eligible promos |
| Referral dashboard | `GET .../promotions/referral` *(P7)* | Share code, copy link, table of redemptions, credit balance |

**Referral dashboard fields to show:**

- `code` + copy button
- `summary.pending_count`, `approved_count`, `total_earned`, `available_credit`
- `redemptions[]` — referred company, status badge, reward amount, date
- `credits[]` — balance ledger

#### Trial tab

| Action | API |
|--------|-----|
| Eligibility | `GET .../trial/status` |
| Start (no Stripe) | `POST .../trial/start` |

Respect `eligible`, `message` (e.g. domain limit, card required).

#### Cancel tab

**Flow:**

```
GET .../lifecycle/retention-offers          (optional — show before cancel)
  → user tries retention offer?
      POST .../lifecycle/accept-retention-offer   (P7)
  → else
      POST .../lifecycle/cancel { at_period_end, reason }
```

- Cancel response includes **`retention_offers[]`** *(P7)* — show “Stay and save” cards with offer title + discount.
- **`POST .../lifecycle/reactivate`** if `cancel_at_period_end`.
- **`GET .../lifecycle/events`** for timeline on History sub-tab.

---

### Company app — checkout v2 (summary)

```
billing/preview  →  validate-coupon / validate-offer  →  checkout  →  Stripe  →  poll billing/current
```

**Checkout body:**

```json
{
  "plan_title": "Growth",
  "billing_frequency": "MONTHLY",
  "employee_count": 30,
  "user_count": 12,
  "coupon_code": "SAVE20",
  "offer_code": "WELCOME10",
  "referral_code": "REF-ABCD1234",
  "start_trial": false,
  "addon_uids": ["<uuid>"]
}
```

- Credits apply automatically from ledger *(P6)*; show in preview before redirect.
- Handle **400** from plan-change guard with user-readable `error` message.

---

### Public marketing site

| Step | API |
|------|-----|
| Plan cards | `GET /api/v2/public/subscription-plans?currency=USD` |
| Anonymous price slider | `POST /api/v2/public/subscription-plans/preview` |
| CTA | Sign up → WE checkout v2 |

Use published plan version for feature/limit bullets on cards (not legacy booleans).

---

### Super Admin app — screen-by-screen

Base path: **`/api/v2/adminio/subscriptions`**. Wire each nav item to live APIs (not dummy seed only).

#### 1. Dashboard

| Widget | API |
|--------|-----|
| KPIs / MRR | `GET .../analytics/overview` |
| Revenue chart | `GET .../analytics/revenue-trend` |
| Plan mix | `GET .../analytics/plan-distribution` |
| Trial funnel | `GET .../analytics/trial-funnel` |
| Recent activity | `GET .../audit-logs?limit=20` |

#### 2. Plans

| Action | API |
|--------|-----|
| Plan cards + table | `GET .../plans` |
| Create plan | `POST .../plans` |
| Edit / archive | `PATCH/DELETE .../plans/<uid>` |
| Version list | `GET .../plans/<uid>/versions` |
| Draft matrix | `PATCH .../plans/<uid>/versions/<version_uid>` |
| Link add-ons on draft | `GET/PUT .../plans/<uid>/versions/<version_uid>/addons` *(P5)* |
| Publish / clone | `POST .../versions/<version_uid>/publish` / `clone` |

**Plan builder UX:**

- Monthly/annual price rows on create/update (`prices[]`).
- Draft-only editing for features/limits; publish promotes to live entitlements.
- Clone copies feature matrix **and** add-on links.

#### 3. Modules & features (matrix)

| Action | API |
|--------|-----|
| Feature catalog | `GET .../features` |
| Toggle features on draft | `PATCH .../versions/<version_uid>` with `plan_features[]` |

Grid: modules × plans; boolean toggle or metered value per cell.

#### 4. Limits & metrics *(P8)*

| Action | API |
|--------|-----|
| Metric table | `GET .../metrics` (includes `enforcement_modes` reference) |
| Create / edit | `POST .../metrics`, `PATCH .../metrics/<uid>` |
| Archive | `DELETE .../metrics/<uid>` |

Show: code pill, unit, enforcement badge, default overage rate.  
Per-plan limits still edited on plan version draft (`limits[]` in PATCH version).

#### 5. Add-ons

| Action | API |
|--------|-----|
| Catalog CRUD | `GET/POST .../addons`, `PATCH/DELETE .../addons/<uid>` |
| Linked plans count | from `linked_plans` in response |

Toggle status, link to plans via `applies_to_subscription_uids`.

#### 6. Coupons & offers

| Action | API |
|--------|-----|
| Coupons CRUD | `GET/POST .../coupons`, `PATCH/DELETE .../coupons/<uid>` |
| Redemptions | `GET .../coupons/<uid>/redemptions` |
| Offers CRUD | `GET/POST .../offers`, `PATCH/DELETE .../offers/<uid>` |

Coupon builder: live discount preview using plan price from catalog.  
Mark offers `is_retention_offer` for cancel-flow promos *(consumed by WE P7)*.

#### 7. Referrals

| Action | API |
|--------|-----|
| Settings | `GET/PATCH .../referrals/settings` |
| Activity + KPIs | `GET .../referrals/activity` |
| Approve / reject | `POST .../referrals/<uid>/approve` / `reject` |

#### 8. Trials

| Action | API |
|--------|-----|
| Default settings | `GET/PATCH .../trials/settings` |
| Active trials table | `GET .../trials?search=` |
| Extend / convert | `POST .../trials/<company_uid>/extend`, `.../convert` |

#### 9. Tenant subscriptions

| Action | API |
|--------|-----|
| List + filters | `GET .../tenants?search=&status=&plan_uid=` |
| Detail drawer | `GET .../tenants/<company_uid>` |
| Timeline | `GET .../tenants/<company_uid>/events` |
| Admin actions | `POST .../tenants/<company_uid>/actions` |

**Drawer actions:** override plan, apply credit, extend trial, suspend/reactivate (`action` in body).

#### 10. Invoices & payments

| Action | API |
|--------|-----|
| Ledger | `GET .../invoices?status=` |
| Retry / refund | `POST .../invoices/<uid>/retry`, `.../refund` |
| Manual invoice | `POST .../manual-invoices` |

#### 11. Audit logs

`GET .../audit-logs?category=&search=` — feed from all mutations; filter chips per design spec.

#### 12. Enterprise

| Action | API |
|--------|-----|
| Contracts | `GET/POST .../contracts`, `PATCH .../contracts/<uid>` |
| Multi-currency prices | `GET/POST .../prices`, `PATCH .../prices/<uid>` |
| Plan migrations | `POST .../migrations`, preview, execute, records |

---

### Super Admin — shared frontend patterns

- **Confirm dialogs** on archive/delete/disable (plans, metrics, add-ons, coupons).
- **Optimistic UI optional** — prefer refetch after mutation; audit log is source of truth for compliance.
- **Mono pills** for codes (`JetBrains Mono`): plan codes, coupon codes, metric codes, invoice IDs.
- **Status badges** map to subscription status enums (`ACTIVE`, `TRIALING`, `PAST_DUE`, etc.).
- **Error display** — show API `error` string from 400 responses; for tenant actions show blocker detail from plan-change payloads when relevant.

---

### v1 → v2 migration (frontend)

| Area | Stop using (v1) | Use (v2) |
|------|-----------------|----------|
| Checkout | `/api/v1/we/subscriptions/checkout` | `/api/v2/we/subscriptions/checkout` |
| Plan info | Payment information list | `GET .../billing/current` |
| Feature gating | Implicit 403 / old booleans | `GET .../entitlements/access-manifest` |
| Invoices | Payment information URLs | `GET .../billing/invoices` |
| Public pricing | `/api/v1/public/subscription-plans` | `/api/v2/public/subscription-plans` |

Keep v1 checkout behind a feature flag until v2 verified in staging.

---

## Known follow-ups (backend)

| Item | Notes |
|------|-------|
| Scheduled downgrade cron | Wrap `execute_due_scheduled_changes` in a management command |
| WE add-on cancel/remove | Purchase exists; no self-service remove yet |
| Seed default add-ons command | Faster staging setup |
| `trial_auto_convert` at expiry | Setting stored; expire job still marks `EXPIRED` only |
| Trial reminder emails | `trial_reminder_days` stored; no job yet |

---

## Related docs

- [`SUBSCRIPTION_ENGINE.md`](./SUBSCRIPTION_ENGINE.md) — full API reference, frontend integration guide
- [`Super Admin - Design Spec & Prompt.md`](./Super%20Admin%20-%20Design%20Spec%20%26%20Prompt.md) — UI spec for Super Admin screens
- [`Balanzify_Advanced_Subscription_Management_PRD.md`](./Balanzify_Advanced_Subscription_Management_PRD.md) — product requirements
