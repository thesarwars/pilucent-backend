# Subscription Engine — Implementation Guide

Pilucent Advanced Subscription Management (Phases 1–6).  
Legacy flows remain on **`/api/v1/`**; the new subscription engine lives under **`/api/v2/`** (no `/v2` segment in the resource path).

**Base URLs**

| App | Prefix |
|-----|--------|
| Company (WE v1) | `/api/v1/we/subscriptions` |
| Company (WE v2) | `/api/v2/we/subscriptions` |
| Super Admin (v1) | `/api/v1/adminio/subscriptions` |
| Super Admin (v2) | `/api/v2/adminio/subscriptions` |
| Public pricing | `/api/v1/public/subscription-plans` (legacy) · `/api/v2/public/subscription-plans` (v2) |

All WE/Admin endpoints require authentication unless noted. WE endpoints use the active company from the logged-in user.

---

## What Was Built

### Phase 1 — Entitlement foundation
- **Models:** `SubscriptionModule`, `SubscriptionFeature`, `PlanVersion`, `PlanLimit`, `PlanFeature`
- **`CompanySubscription.plan_version`** — optional pinned plan version
- **Expanded statuses:** `TRIALING`, `PAST_DUE`, `GRACE`, `SUSPENDED`, `CANCELED`, `EXPIRED`
- **Services:** `EntitlementService`, `AccessPolicy`, `PlanVersionService`, entitlement cache + signals
- **`HaveSubscription`** (v2) delegates to `EntitlementService` instead of raw boolean flags
- **Migration:** `0010_entitlement_engine_phase1`

### Phase 2 — Billing MVP
- **Models:** `SubscriptionInvoice`, `SubscriptionInvoiceLine`, billing period fields on `CompanySubscription`
- **Services:** `UsageService`, `BillingPreviewService`, `SubscriptionBillingService`
- **Stripe:** period sync, invoice upsert, `PAST_DUE` on failed payment
- **Migration:** `0011_billing_mvp_phase2`

### Phase 3 — Limits & enforcement
- **Models:** `UsageCounter`
- **Services:** `LimitEnforcementService`, `PlanChangeGuardService`
- **Guards:** employee create, user invite, v2 checkout (downgrade block)
- **Payroll / banking gating** wired via `PAYROLL_PERMISSION_CLASSES` + `is_bank_transaction`
- **Migration:** `0013_usage_counter_phase3`

### Phase 4 — Promotions & trials
- **Models:** `SubscriptionCoupon`, `CouponRedemption`, `SubscriptionOffer`, `ReferralCode`, `ReferralRedemption`, `SubscriptionCredit`
- **Trial fields:** `CompanySubscription.trial_start`, `trial_end`
- **Services:** `CouponService`, `TrialService`, `ReferralService`
- **Migration:** `0014_promotions_phase4`

### Phase 5 — Lifecycle, dunning & analytics
- **Models:** `SubscriptionEvent`, dunning/cancel fields on `CompanySubscription`
- **Services:** `DunningService`, `LifecycleService`, `SubscriptionEventService`, `SubscriptionAnalyticsService`
- **Dunning flow:** `PAST_DUE` → `GRACE` → `SUSPENDED` → `EXPIRED`
- **Migration:** `0015_lifecycle_phase5`

### Phase 6 — Enterprise
- **Models:** `SubscriptionContract`, `PlanMigrationJob`, `PlanMigrationRecord`
- **`SubscriptionPrice.currency`** + `is_active` (multi-currency matrix)
- **Manual invoices:** `SubscriptionInvoice.is_manual`
- **Services:** `EnterprisePricingService`, `ManualInvoiceService`, `PlanMigrationService`
- **Migrations:** `0016_enterprise_phase6`, `0017_alter_field_choices_alignment`

### v1 reorganization (unchanged URLs)
Legacy checkout, payment info, and Stripe webhook stay at original paths under `/api/v1/we/subscriptions/...`.

---

## Subscription Status Behavior (frontend gating)

| Status | Feature access | UI hint |
|--------|----------------|---------|
| `ACTIVE` | Full (per plan) | Normal |
| `TRIALING` | Full (per plan) | Show trial days remaining |
| `GRACE` | Full (per plan) | Warning: payment overdue |
| `PAST_DUE` | Billing-only (restricted) | Prompt update payment |
| `SUSPENDED` | Billing-only | Strong paywall |
| `CANCELED` / `EXPIRED` | Denied | Upgrade / reactivate CTA |
| `PENDING` | Denied | Complete checkout |

Use **`GET /api/v2/we/subscriptions/entitlements/access-manifest`** on app load to drive menus, routes, and feature cards (replaces scattered `is_*` checks over time).

---

## API Endpoints

### WE v1 (legacy — keep using until v2 checkout is live)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/we/subscriptions` | List payment information |
| `GET/PATCH` | `/api/v1/we/subscriptions/<uid>` | Payment information detail |
| `POST` | `/api/v1/we/subscriptions/checkout` | Legacy Stripe checkout (no overage breakdown) |
| `POST` | `/api/v1/we/subscriptions/stripe/webhook/j12t34` | Stripe webhook (server only) |

**WE v2 base:** `/api/v2/we/subscriptions`

### WE v2 — Entitlements

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/we/subscriptions/entitlements/access-manifest` | Full access map for UI (features + RBAC) |
| `POST` | `/api/v2/we/subscriptions/entitlements/check` | Single feature check |

**`POST .../check` body**
```json
{ "feature": "is_sales" }
```
or `{ "feature_code": "sales" }` (catalog code).

**Response (denied example)**
```json
{
  "allowed": false,
  "feature": "is_sales",
  "denied_by": "subscription",
  "message": "This feature is not included in your current plan...",
  "upgrade_metadata": { "feature": "is_sales", "current_plan": "Starter", "suggested_action": "upgrade" }
}
```

### WE v2 — Billing

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/we/subscriptions/billing/current` | Plan, usage, limits, period, preview, lifecycle |
| `POST` | `/api/v2/we/subscriptions/billing/preview` | Price breakdown before plan change |
| `GET` | `/api/v2/we/subscriptions/billing/usage` | Usage + limit status (refreshes snapshot) |
| `GET` | `/api/v2/we/subscriptions/billing/invoices` | Invoice history |
| `GET` | `/api/v2/we/subscriptions/billing/invoices/<uid>` | Invoice + line items |

**`POST .../preview` body**
```json
{
  "subscription_price_slug": "optional",
  "plan_title": "Starter",
  "billing_frequency": "MONTHLY",
  "employee_count": 30,
  "user_count": 12,
  "tax_rate": 8.5,
  "coupon_code": "SAVE20",
  "currency": "EUR",
  "addon_uids": ["<uuid>"],
  "addon_quantities": { "<uuid>": 1 },
  "apply_credits": true
}
```

Preview and `billing/current` responses include `credit_total`, `available_credit_balance`, and a `CREDIT` line when account credits reduce amount due. Checkout applies credits as a Stripe one-time discount and deducts the ledger on `checkout.session.completed`.

**Credit formula:** `total = max(0, subtotal - discounts + overage + addons + tax - credit_total)`

### Program settings enforcement (P6)

`SubscriptionProgramSettings` is enforced at runtime:

| Setting | Enforced in |
|---------|-------------|
| `referral_program_active` | `ReferralService.validate` / `redeem` |
| `referral_max_per_month` | `ReferralService.validate` |
| `referral_reward_amount` | `ReferralService._reward_amount` |
| `trial_default_days` | `TrialService.start_trial`, Stripe checkout when plan has no trial |
| `trial_card_required` | `TrialService.start_trial`, Stripe checkout `payment_method_collection` |
| `trial_one_per_domain` | `TrialService.get_status` / `start_trial` |
| `trial_max_extension_days` | `TrialService.extend_trial`, `AdminTrialService.extend_trial` |

`billing/current` includes an `addons` object with `available` and `active` lists, plus `available_credit_balance`.

### WE v2 — Add-ons

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/we/subscriptions/addons` | Available + active add-ons for current plan |
| `POST` | `/api/v2/we/subscriptions/addons/purchase` | Purchase add-on on active subscription |

**`POST .../purchase` body:** `{ "addon_uid": "<uuid>", "quantity": 1 }`

Recurring add-ons attach via Stripe subscription item; one-time add-ons return a Stripe payment checkout URL.

### WE v2 — Checkout

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v2/we/subscriptions/checkout` | Stripe session with base + overage + add-on line items |

**Body** (same selectors as preview, plus):
```json
{
  "plan_title": "Starter",
  "billing_frequency": "MONTHLY",
  "employee_count": 30,
  "user_count": 12,
  "coupon_code": "SAVE20",
  "offer_code": "WELCOME10",
  "referral_code": "REF-ABCD1234",
  "start_trial": false,
  "addon_uids": ["<uuid>"],
  "addon_quantities": { "<uuid>": 1 }
}
```

**Response**
```json
{
  "checkout_url": "https://checkout.stripe.com/...",
  "session_id": "cs_...",
  "billing_preview": { "total": "...", "lines": [...] }
}
```

Redirect user to `checkout_url`. On return, poll `GET .../billing/current` until status is `ACTIVE` or `TRIALING`.

### WE v2 — Promotions & trials

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v2/we/subscriptions/promotions/validate-coupon` | Validate coupon before checkout |
| `POST` | `/api/v2/we/subscriptions/promotions/validate-offer` | Validate offer and resolve linked coupon |
| `GET` | `/api/v2/we/subscriptions/promotions/offers` | List eligible non-retention offers |
| `GET` | `/api/v2/we/subscriptions/promotions/referral` | Referral code, rewards, redemptions, credits |
| `GET` | `/api/v2/we/subscriptions/trial/status` | Trial eligibility & days remaining |
| `POST` | `/api/v2/we/subscriptions/trial/start` | Start internal trial (no Stripe) |

**Referral dashboard (`GET .../referral`)** returns `code`, `summary` (pending/approved/earned credit), `redemptions[]`, and `credits[]`.

**Checkout / preview** accept `offer_code` (resolves to linked coupon; mutually exclusive with a different `coupon_code`).

Aliases also exist under `/promotions/trial/...` (same handlers).

### WE v2 — Plan changes (P8)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v2/we/subscriptions/plan-changes/preview` | Preview upgrade/downgrade with guardrails + proration |
| `GET/DELETE` | `/api/v2/we/subscriptions/plan-changes/scheduled` | View or cancel scheduled downgrade |
| `POST` | `/api/v2/we/subscriptions/plan-changes/schedule-downgrade` | Schedule downgrade for period end |

Billing preview adds a `PRORATION` line when the target plan differs from the current subscription. `billing/current` includes `scheduled_plan_change`.

### Admin v2 — Billable metrics (P8)

| Method | Path | Purpose |
|--------|------|---------|
| `GET/POST` | `/api/v2/adminio/subscriptions/metrics` | Metric catalog + enforcement mode reference |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/metrics/<uid>` | Metric detail / update / archive |

Default metrics seed on first list: employees, users, branches, payroll runs, storage, AI credits.

### WE v2 — Lifecycle (self-service)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/we/subscriptions/lifecycle/state` | Cancel/dunning status |
| `POST` | `/api/v2/we/subscriptions/lifecycle/cancel` | Cancel subscription (response includes `retention_offers`) |
| `GET` | `/api/v2/we/subscriptions/lifecycle/retention-offers` | Retention offers before/at cancel |
| `POST` | `/api/v2/we/subscriptions/lifecycle/accept-retention-offer` | Accept retention offer and undo pending cancel |
| `POST` | `/api/v2/we/subscriptions/lifecycle/reactivate` | Undo cancel / restore |
| `GET` | `/api/v2/we/subscriptions/lifecycle/events` | Subscription event timeline |

**`POST .../cancel` body**
```json
{ "at_period_end": true, "reason": "optional" }
```

### Public pricing (marketing site)

**v1 (legacy)** — boolean feature flags on `Subscription`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/public/subscription-plans` | Published plans |
| `GET` | `/api/v1/public/subscription-plans/<slug>` | Plan detail |
| `GET` | `/api/v1/public/subscription-plans/prices` | Published prices |

**v2 (use for new pricing page)** — plan versions, entitlements, limits, multi-currency

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/public/subscription-plans` | Published plans + prices + published version matrix (`?currency=&kind=`) |
| `GET` | `/api/v2/public/subscription-plans/<slug>` | Single plan detail |
| `POST` | `/api/v2/public/subscription-plans/preview` | Anonymous quote with employee/user overage |

**`POST .../preview` body**
```json
{
  "plan_slug": "plus",
  "billing_frequency": "MONTHLY",
  "currency": "USD",
  "employee_count": 30,
  "user_count": 10
}
```

---

## Admin APIs (Super Admin)

**v1 base:** `/api/v1/adminio/subscriptions`  
**v2 base:** `/api/v2/adminio/subscriptions`

### v1 (legacy plan CRUD)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/adminio/subscriptions` | List plans |
| `GET/PATCH` | `/api/v1/adminio/subscriptions/retrieve/<uid>` | Plan detail/update |

### v2 — Add-ons (Super Admin)

| Method | Path | Purpose |
|--------|------|---------|
| `GET/POST` | `/api/v2/adminio/subscriptions/addons` | Add-on catalog list/create (`?status=&search=`) |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/addons/<uid>` | Add-on detail (delete disables) |

**Create/update body**
```json
{
  "code": "ADDON_EMP",
  "title": "Extra Employee Capacity",
  "pricing_model": "RECURRING",
  "price": "6.000",
  "billing_frequency": "MONTHLY",
  "currency": "USD",
  "status": "ACTIVE",
  "metric_code": "EMPLOYEE",
  "unit_label": "per employee",
  "applies_to_subscription_uids": []
}
```

`pricing_model`: `RECURRING`, `ONE_TIME`, `USAGE_BASED`. Empty `applies_to_subscription_uids` = all plans.

### v2 — Plan catalog & versions

| Method | Path | Purpose |
|--------|------|---------|
| `GET/POST` | `/api/v2/adminio/subscriptions/plans` | List plans / create plan + draft version |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/plans/<uid>` | Plan detail / update / archive |
| `GET` | `/api/v2/adminio/subscriptions/features` | Feature/module catalog |
| `GET` | `/api/v2/adminio/subscriptions/plans/<uid>/versions` | List plan versions |
| `POST` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/draft` | Create draft version |
| `PATCH` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/<version_uid>` | Update draft features/limits |
| `GET/PUT` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/<version_uid>/addons` | Plan version add-on links |
| `POST` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/<version_uid>/publish` | Publish version |
| `POST` | `/api/v2/adminio/subscriptions/plans/<uid>/versions/<version_uid>/clone` | Clone version |

**`POST /plans` body**
```json
{
  "title": "Growth",
  "description": "For growing teams",
  "currency": "USD",
  "employee_limit": 25,
  "user_limit": 10,
  "storage_limit": 100,
  "trial_period": 14,
  "status": "DRAFT",
  "publish_initial_version": false,
  "prices": [
    { "billing_frequency": "MONTHLY", "price": "250.000", "currency": "USD" }
  ]
}
```

**`PUT .../versions/<version_uid>/addons` body**
```json
{
  "addons": [
    { "addon_uid": "<uuid>", "availability": "OPTIONAL" }
  ]
}
```

**`PATCH .../versions/<version_uid>` body (draft only)**
```json
{
  "notes": "optional",
  "plan_features": [
    { "feature_code": "sales", "is_enabled": true, "access_level": "FULL" }
  ],
  "limits": [
    {
      "metric_code": "EMPLOYEE",
      "included_quantity": 25,
      "overage_unit_price": "6.000",
      "enforcement_mode": "AUTO_OVERAGE"
    }
  ]
}
```

### v2 — Tenant subscriptions (Super Admin ops)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/adminio/subscriptions/tenants` | List tenants (`?search=&status=&plan_uid=`) |
| `GET` | `/api/v2/adminio/subscriptions/tenants/<company_uid>` | Tenant drawer detail (billing, usage, lifecycle) |
| `GET` | `/api/v2/adminio/subscriptions/tenants/<company_uid>/events` | Subscription event timeline |
| `POST` | `/api/v2/adminio/subscriptions/tenants/<company_uid>/actions` | Admin override actions |

**`POST .../actions` body**
```json
{
  "action": "override_plan",
  "subscription_price_uid": "<uuid>",
  "plan_version_uid": "<uuid>",
  "reason": "optional"
}
```

Supported `action` values: `override_plan`, `apply_credit`, `extend_period`, `extend_trial`, `suspend`, `reactivate`.

### v2 — Invoices & payments (Super Admin)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/adminio/subscriptions/invoices` | Cross-tenant invoice ledger + KPI summary |
| `GET` | `/api/v2/adminio/subscriptions/invoices/<uid>` | Invoice detail + lines |
| `POST` | `/api/v2/adminio/subscriptions/invoices/<uid>/retry` | Retry failed/open invoice |
| `POST` | `/api/v2/adminio/subscriptions/invoices/<uid>/refund` | Refund paid invoice |
| `POST` | `/api/v2/adminio/subscriptions/manual-invoices` | Create manual invoice |

### v2 — Promotions

| Method | Path | Purpose |
|--------|------|---------|
| `GET/POST` | `/api/v2/adminio/subscriptions/coupons` | Coupon list/create |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/coupons/<uid>` | Coupon detail (delete disables if redeemed) |
| `GET` | `/api/v2/adminio/subscriptions/coupons/redemptions` | All coupon redemptions (`?search=&limit=`) |
| `GET` | `/api/v2/adminio/subscriptions/coupons/<uid>/redemptions` | Per-coupon redemptions |
| `GET/POST` | `/api/v2/adminio/subscriptions/offers` | Offer list/create |
| `GET/PATCH/DELETE` | `/api/v2/adminio/subscriptions/offers/<uid>` | Offer detail (delete archives) |

Coupon create/update accepts `applies_to_subscription_uids: [<plan_uid>, ...]` (empty = all plans).

### v2 — Referrals (Super Admin)

| Method | Path | Purpose |
|--------|------|---------|
| `GET/PATCH` | `/api/v2/adminio/subscriptions/referrals/settings` | Referral program rules |
| `GET` | `/api/v2/adminio/subscriptions/referrals/activity` | Referral ledger (`?status=&search=`) |
| `POST` | `/api/v2/adminio/subscriptions/referrals/<uid>/actions` | Approve/reject pending referral |

**`POST .../actions` body:** `{ "action": "approve" }` or `{ "action": "reject", "reason": "..." }`

### v2 — Trials (Super Admin)

| Method | Path | Purpose |
|--------|------|---------|
| `GET/PATCH` | `/api/v2/adminio/subscriptions/trials/settings` | Default trial rules |
| `GET` | `/api/v2/adminio/subscriptions/trials` | Active trials (`?search=`) |
| `POST` | `/api/v2/adminio/subscriptions/trials/<company_uid>/actions` | Extend or convert trial |

**`POST .../actions` body:** `{ "action": "extend", "days": 7 }` or `{ "action": "convert" }`

### v2 — Audit logs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/adminio/subscriptions/audit-logs` | Subscription event feed (`?category=&search=&limit=`) |

Categories: `plan`, `billing`, `trial`, `coupon`, `referral`, or `all`.

### v2 — Analytics

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/adminio/subscriptions/analytics/overview` | MRR, ARR, churn, trials, overage |
| `GET` | `/api/v2/adminio/subscriptions/analytics/mrr-breakdown` | MRR by plan |
| `GET` | `/api/v2/adminio/subscriptions/analytics/revenue-trend` | Monthly revenue/MRR trend (`?months=12`) |
| `GET` | `/api/v2/adminio/subscriptions/analytics/plan-distribution` | Subscriber share by plan |
| `GET` | `/api/v2/adminio/subscriptions/analytics/trial-funnel` | Trial funnel (`?days=90`) |

### v2 — Enterprise

| Method | Path | Purpose |
|--------|------|---------|
| `GET/POST` | `/api/v2/adminio/subscriptions/prices` | Multi-currency price matrix |
| `GET/PATCH` | `/api/v2/adminio/subscriptions/prices/<uid>` | Price detail |
| `GET/POST` | `/api/v2/adminio/subscriptions/contracts` | Enterprise contracts |
| `GET/PATCH` | `/api/v2/adminio/subscriptions/contracts/<uid>` | Contract detail |
| `GET/POST` | `/api/v2/adminio/subscriptions/migrations` | Plan migration jobs |
| `GET` | `/api/v2/adminio/subscriptions/migrations/<uid>/preview` | Preview eligible companies |
| `POST` | `/api/v2/adminio/subscriptions/migrations/<uid>/execute` | Run migration |
| `GET` | `/api/v2/adminio/subscriptions/migrations/<uid>/records` | Per-company results |
| `POST` | `/api/v2/adminio/subscriptions/manual-invoices` | Create manual invoice |

---

## Ops & One-Time Setup

```bash
# Apply all subscription migrations (0010–0017)
python manage.py migrate subscriptionio

# Seed feature catalog from legacy boolean flags (run once per env)
python manage.py seed_subscription_features

# Optional cron jobs
python manage.py snapshot_subscription_usage      # refresh usage counters
python manage.py expire_subscription_trials       # expire ended trials
python manage.py process_subscription_dunning     # advance dunning states
python manage.py run_plan_migration <job_uid>     # CLI plan migration
```

---

## Frontend Integration Guide

### 1. App bootstrap (every session)

1. Call **`GET /api/v2/we/subscriptions/entitlements/access-manifest`** after login / company switch.
2. Store manifest in global state (Redux/Zustand/Context).
3. Use manifest to:
   - Show/hide sidebar modules and routes
   - Enable/disable dashboard cards (same pattern as dashboard v2)
   - Gate "Create" buttons before API calls (employee, user invite, etc.)

Do **not** rely only on hardcoded `is_*` flags from old plan payloads — manifest is the source of truth.

### 2. Subscription settings page (new)

Build a **Subscription & Billing** section with tabs:

| Tab | APIs | UI |
|-----|------|-----|
| **Overview** | `GET /api/v2/we/subscriptions/billing/current` | Plan name, status badge, period end, usage meters (employees/users), live cost |
| **Change plan** | `POST /api/v2/we/subscriptions/billing/preview` → `POST /api/v2/we/subscriptions/checkout` | Plan picker, employee/user sliders, price breakdown, Stripe redirect |
| **Invoices** | `GET /api/v2/we/subscriptions/billing/invoices` | Table with link to `hosted_invoice_url` when present |
| **Coupons** | `POST /api/v2/we/subscriptions/promotions/validate-coupon` | Coupon field on preview/checkout |
| **Referral** | `GET /api/v2/we/subscriptions/promotions/referral` | Show shareable code |
| **Trial** | `GET /api/v2/we/subscriptions/trial/status`, `POST /api/v2/we/subscriptions/trial/start` | Start trial CTA if eligible |
| **Cancel** | `GET /api/v2/we/subscriptions/lifecycle/state`, `POST /api/v2/we/subscriptions/lifecycle/cancel` | Cancel at period end vs immediate |
| **History** | `GET /api/v2/we/subscriptions/lifecycle/events` | Timeline for support/debug |

### 3. Checkout flow (v2)

```
User selects plan + usage
    → POST /api/v2/we/subscriptions/billing/preview (show breakdown)
    → optional: POST /api/v2/we/subscriptions/promotions/validate-coupon
    → POST /api/v2/we/subscriptions/checkout
    → window.location = checkout_url
    → return URL: poll GET /api/v2/we/subscriptions/billing/current until ACTIVE|TRIALING
```

Show **plan-change guard** errors from preview/checkout (`400` with message when downgrade blocked due to usage).

### 4. Paywall & upgrade UX

When any API returns **403** with subscription denial (or manifest says feature off):

- Show `message` from entitlement check
- Show `upgrade_metadata` (current plan, suggested action)
- CTA → Subscription settings → Change plan

For limit blocks on create (employee/user):

- Backend returns `400` with `denied_by: "subscription_limit"` and `upgrade_metadata`
- Show inline error + upgrade CTA

### 5. Status-specific UI

| Status | Frontend behavior |
|--------|---------------------|
| `TRIALING` | Banner: "X days left" from `trial/status` or `billing/current` |
| `PAST_DUE` / `GRACE` | Persistent billing alert; restrict non-billing routes if manifest denies |
| `cancel_at_period_end` | Banner: "Cancels on {date}" + Reactivate button |
| `SUSPENDED` / `EXPIRED` | Full-page paywall; only billing/settings routes |

### 6. Pricing / marketing page

- Use **`GET /api/v2/public/subscription-plans`** for plan cards (features/limits from published plan version)
- Add **employee slider** → `POST /api/v2/public/subscription-plans/preview` (anonymous) or WE `billing/preview` when logged in
- Support **currency** via `?currency=USD` on list/detail and in preview body
- CTA → signup → WE checkout v2

### 7. Admin dashboard (Super Admin)

| Screen | APIs |
|--------|------|
| Dashboard | v2 analytics overview, revenue-trend, plan-distribution, trial-funnel, audit feed |
| Plans | v2 plans CRUD, versions draft/publish/clone, add-on links, `PATCH` draft matrix |
| Add-ons | v2 addons catalog CRUD |
| Feature matrix | v2 features + `PATCH` plan version |
| Tenant subscriptions | v2 tenants list/detail/events/actions |
| Invoices & payments | v2 invoices list/retry/refund + manual-invoices |
| Referrals | v2 referrals settings/activity/approve-reject |
| Trials | v2 trials settings/list/extend/convert |
| Audit logs | v2 `GET /audit-logs` |
| Coupons & offers | v2 coupons/offers CRUD, redemptions, plan eligibility |
| Enterprise contracts | v2 contracts CRUD |
| Multi-currency prices | v2 prices CRUD |
| Limits & metrics | v2 metrics catalog CRUD, enforcement modes |
| Plan migrations | v2 migrations preview → execute → records |

### 8. Feature code reference (common `required_feature` values)

Legacy views still use `is_*` strings. Manifest returns both legacy fields and catalog codes.

| Module | Feature flag |
|--------|----------------|
| Sales | `is_sales` |
| Payroll | `is_payroll` |
| Employees | `is_employees` |
| Expenses | `is_expense` |
| Inventory | `is_inventory` |
| Bank reconcile | `is_bank_transaction` |
| Reports | `is_standard_report` |
| Multicurrency | `is_multicurrency` |

Prefer checking **manifest features** object keys over hardcoding.

### 9. Migration from v1 to v2 (frontend)

| Area | v1 (legacy) | v2 (use going forward) |
|------|-------------|------------------------|
| Checkout | `POST /api/v1/we/subscriptions/checkout` | `POST /api/v2/we/subscriptions/checkout` |
| Plan info | Payment information list | `GET /api/v2/we/subscriptions/billing/current` |
| Gating | Implicit via API 403 | `GET /api/v2/we/subscriptions/entitlements/access-manifest` |
| Invoices | Payment information URLs | `GET /api/v2/we/subscriptions/billing/invoices` |

Keep v1 checkout until v2 is verified in staging; then switch CTA to v2 only.

---

## Key Backend Files (for reference)

```
subscriptionio/
  entitlement_models.py    # PlanVersion, PlanLimit, PlanFeature, ...
  billing_models.py        # SubscriptionInvoice, lines
  enforcement_models.py    # UsageCounter
  promotion_models.py      # Coupons, referrals, credits
  lifecycle_models.py      # SubscriptionEvent
  enterprise_models.py     # Contracts, plan migrations
  services/
    entitlement_service.py
    billing_preview_service.py
    stripe_checkout_service.py
    limit_enforcement_service.py
    credit_service.py
    offer_service.py
    proration_service.py
    plan_change_service.py
    admin_metric_service.py
    trial_service.py, coupon_service.py, lifecycle_service.py
    dunning_service.py, enterprise_pricing_service.py
weapi/django_rest/views/subscriptions/v1/   # legacy
weapi/django_rest/views/subscriptions/v2/   # new engine
adminio/django_rest/views/subscriptions/v2/
```

---

## Suggested Frontend Milestones

1. **Manifest-driven navigation** — hide modules without entitlement  
2. **Billing overview page** — `billing/current` + usage meters  
3. **v2 checkout** — preview → Stripe redirect  
4. **Invoice list** — billing/invoices  
5. **Trial + coupon** — promotions APIs on checkout  
6. **Cancel/reactivate** — lifecycle APIs  
7. **Admin analytics + coupons** — admin v2 screens  

---

*Last updated: June 2026 — Super Admin P0–P8, WE P4–P8, migrations through `0021`.*
