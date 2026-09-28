# Super Admin — Subscription Add-ons API

**Base URL:** `/api/v2/adminio/subscriptions`  
**Auth:** Super Admin (`IsSuperAdmin`)

Related: [`SUBSCRIPTION_ENGINE.md`](./SUBSCRIPTION_ENGINE.md) · [`subscription_v2_admin.md`](./subscription_v2_admin.md)

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/addons` | List add-ons (`?status=&search=`) |
| `POST` | `/addons` | Create add-on |
| `GET` | `/addons/<uid>` | Add-on detail |
| `PATCH` | `/addons/<uid>` | Update add-on |
| `DELETE` | `/addons/<uid>` | Disable add-on (soft delete) |

---

## POST `/addons` — Create add-on

### Request body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `code` | string | **Yes** | — | Unique catalog code; stored uppercase |
| `title` | string | No | `code` | Display name |
| `description` | string | No | `""` | Long description |
| `pricing_model` | string | No | `RECURRING` | See [Pricing models](#pricing-models) |
| `price` | number / string | No | `0` | Decimal price, e.g. `"6.000"` |
| `billing_frequency` | string | No | `null` | Required for `RECURRING`; see [Billing frequency](#billing-frequency) |
| `currency` | string | No | `USD` | ISO currency code |
| `status` | string | No | `DRAFT` | `DRAFT`, `ACTIVE`, `DISABLED` |
| `metric_code` | string | No | `null` | Billable metric; see [Metric codes](#metric-codes) |
| `unit_label` | string | No | `""` | e.g. `"per employee"`, `"per 1k credits"` |
| `stripe_price_id` | string | No | `null` | Stripe Price ID for WE checkout |
| `applies_to_subscription_uids` | uuid[] | No | all plans | Plan UUIDs this add-on applies to |

**Plan linking rules**

- Omit `applies_to_subscription_uids` → add-on applies to **all** plans.
- Pass `[]` (empty array) → applies to **all** plans.
- Pass one or more plan UUIDs → add-on limited to those plans only.

---

### Example — recurring add-on (all plans)

```http
POST /api/v2/adminio/subscriptions/addons
Content-Type: application/json
```

```json
{
  "code": "ADDON_EMP",
  "title": "Extra Employee Capacity",
  "description": "Additional billable employees beyond plan included quantity",
  "pricing_model": "RECURRING",
  "price": "6.000",
  "billing_frequency": "MONTHLY",
  "currency": "USD",
  "status": "ACTIVE",
  "metric_code": "EMPLOYEE",
  "unit_label": "per employee",
  "stripe_price_id": "price_1Example",
  "applies_to_subscription_uids": []
}
```

---

### Example — one-time add-on (specific plans)

```json
{
  "code": "ADDON_AI_PACK",
  "title": "AI Credit Pack",
  "description": "1,000 AI credits one-time purchase",
  "pricing_model": "ONE_TIME",
  "price": "25.000",
  "currency": "USD",
  "status": "ACTIVE",
  "metric_code": "AI_CREDIT",
  "unit_label": "per 1k credits",
  "applies_to_subscription_uids": [
    "7392ea74-46a2-4a4d-9958-ad8f832b1cb1",
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  ]
}
```

---

### Example — minimal payload

```json
{
  "code": "ADDON_SUPPORT",
  "title": "Premium Support",
  "price": "99.000",
  "pricing_model": "RECURRING",
  "billing_frequency": "MONTHLY",
  "status": "ACTIVE"
}
```

---

### Success response (`201 Created`)

```json
{
  "uid": "f8a3b2c1-1234-5678-9abc-def012345678",
  "code": "ADDON_EMP",
  "title": "Extra Employee Capacity",
  "description": "Additional billable employees beyond plan included quantity",
  "pricing_model": "RECURRING",
  "price": "6.000",
  "billing_frequency": "MONTHLY",
  "currency": "USD",
  "status": "ACTIVE",
  "metric_code": "EMPLOYEE",
  "unit_label": "per employee",
  "stripe_price_id": "price_1Example",
  "linked_plans": {
    "count": 4,
    "applies_to_all": true,
    "plans": []
  },
  "created_at": "2026-06-08T12:00:00Z",
  "updated_at": "2026-06-08T12:00:00Z"
}
```

When linked to specific plans, `linked_plans` looks like:

```json
{
  "count": 2,
  "applies_to_all": false,
  "plans": [
    {
      "uid": "7392ea74-46a2-4a4d-9958-ad8f832b1cb1",
      "title": "Growth",
      "slug": "growth"
    }
  ]
}
```

---

### Error responses (`400 Bad Request`)

```json
{ "error": "code is required." }
```

```json
{ "error": "An add-on with this code already exists." }
```

---

## PATCH `/addons/<uid>` — Update add-on

Same fields as POST, all optional. Include `applies_to_subscription_uids` to replace plan links.

```json
{
  "title": "Extra Employee Capacity (updated)",
  "price": "7.000",
  "status": "ACTIVE",
  "applies_to_subscription_uids": ["7392ea74-46a2-4a4d-9958-ad8f832b1cb1"]
}
```

`code` can be changed if the new code is not already taken.

---

## DELETE `/addons/<uid>` — Disable add-on

Soft delete — sets `status` to `DISABLED`.

```json
{
  "status": "disabled",
  "message": "Add-on disabled."
}
```

---

## GET `/addons` — List add-ons

**Query params**

| Param | Description |
|-------|-------------|
| `status` | Filter: `DRAFT`, `ACTIVE`, `DISABLED` |
| `search` | Match `code` or `title` (case-insensitive) |

Returns an array of add-on objects (same shape as create response).

---

## Enum reference

### Pricing models

| Value | Use |
|-------|-----|
| `RECURRING` | Billed each billing cycle (requires `billing_frequency`) |
| `ONE_TIME` | Single charge at purchase |
| `USAGE_BASED` | Usage-metered add-on |

### Billing frequency

`WEEKLY` · `MONTHLY` · `QUARTERLY` · `HALF_YEARLY` · `YEARLY`

### Status

| Value | Meaning |
|-------|---------|
| `DRAFT` | Not visible to tenants |
| `ACTIVE` | Available for purchase / plan linking |
| `DISABLED` | Retired from catalog |

### Metric codes

| Value | Typical use |
|-------|-------------|
| `EMPLOYEE` | Extra employee seats |
| `USER` | Extra login users |
| `BRANCH` | Extra branches |
| `STORAGE` | Extra storage (GB) |
| `PAYROLL_RUN` | Extra payroll runs |
| `AI_CREDIT` | AI credit packs |

---

## Linking add-ons to plan versions

Catalog add-ons (`POST /addons`) define the **product**. To attach them to a **plan version** (draft only):

```http
PUT /api/v2/adminio/subscriptions/plans/<plan_uid>/versions/<version_uid>/addons
```

```json
{
  "addons": [
    { "addon_uid": "f8a3b2c1-1234-5678-9abc-def012345678", "availability": "OPTIONAL" }
  ]
}
```

`availability`: `OPTIONAL`, `REQUIRED`, `UNAVAILABLE`.

---

## WE runtime (tenant purchase)

After catalog is `ACTIVE` and linked to a plan version:

| Method | Path |
|--------|------|
| `GET` | `/api/v2/we/subscriptions/addons` |
| `POST` | `/api/v2/we/subscriptions/addons/purchase` |

Include purchased add-ons in checkout/preview via `addon_uids` or `addon_codes`.
