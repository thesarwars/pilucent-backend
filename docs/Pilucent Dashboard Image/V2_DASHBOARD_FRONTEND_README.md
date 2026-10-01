# Pilucent v2 Dashboard — Frontend Integration Guide

This document describes the **v2 Dashboard API** and what the frontend needs to
build to consume it. It covers the 26 feature cards from
`Pilucent_Dashboard_Feature_Cards_Documentation.pdf`.

- **v1 is unchanged.** Existing endpoints (e.g. `/dashboards/finance-overview`)
  keep working exactly as before. Migrate to v2 card-by-card.
- **One endpoint per card.** Each card is its own request, so cards load, fail,
  and refresh independently.
- **Consistent envelope.** Every card returns the same payload shape, so a
  single renderer can drive skeleton / empty / stale / error / restricted states.

---

## 1. Base URL & Auth

- Base path: `/api/v1/we/dashboards/v2`
- Auth: JWT `Authorization: Bearer <access_token>` (same as the rest of the WE API).
- Scope: every card is automatically scoped to the user's **active company**.
  No company id needs to be passed.

---

## 2. Global Filters (query params)

All cards accept the same global filters. Send the same set to every card so the
numbers stay consistent across the dashboard.

| Param | Type | Default | Notes |
|---|---|---|---|
| `date_from` | `YYYY-MM-DD` | 30 days before `date_to` | Also accepts `start_date` alias |
| `date_to` | `YYYY-MM-DD` | today | Also accepts `end_date` alias |
| `comparison_period` | string | `previous_period` | Drives trend comparison |
| `currency` | string | company default | Display hint |
| `accounting_basis` | `accrual` \| `cash` | `accrual` | |
| `months` | int (`3,6,7,12`) | per card | Only for time-series cards (P&L, Income vs Expense, Cash Flow) |
| `limit` | int | per card | Only for list cards (top customers/products, recent txns, tickets, activity) |
| `days` | int | `30` | Only for Upcoming Events |

The **comparison period** is computed server-side as the equally-long window
immediately before `[date_from, date_to]`.

---

## 3. Card Response Envelope

Every endpoint returns HTTP `200` with this shape:

```jsonc
{
  "card": "invoice_overview",
  "value": 12450.0,                 // headline number (or count, or null)
  "comparison_value": 11000.0,      // previous-period value (nullable)
  "trend_percent": 13.18,           // nullable; null means "New / no prior data"
  "trend_direction": "up",          // "up" | "down" | "flat" | "new"
  "chart_series": [ ... ],          // time-series / breakdown rows (may be [])
  "list_items": [ ... ],            // table/list rows (may be [])
  "action_route": "/sales/invoices",// where the card drills down
  "last_updated_at": null,
  "permission_state": "allowed",    // "allowed" | "restricted"
  "data_state": "ok",               // "ok" | "empty" | "error"
  "error_state": null               // { "message", "retryable" } when failed
  // ...card-specific extra keys (see each card below)
}
```

### Frontend state handling (required)

| Condition | What to render |
|---|---|
| `data_state == "ok"` | Normal card |
| `data_state == "empty"` | Empty state ("No data for this period") |
| `data_state == "error"` | Error state + retry button (use `error_state.message`) |
| `permission_state == "restricted"` | Locked/upgrade state (show `message`, hide values) |
| `trend_direction == "new"` | Show "New" instead of a percentage |

> Important: a failing card returns `200` with `data_state="error"` — it never
> 500s the page. Render each card independently; do not block the dashboard on
> one card.

---

## 4. API List (26 cards)

All paths are relative to `/api/v1/we/dashboards/v2`.

### Finance / Accounting

| # | Card | Method | Endpoint | Key fields (beyond envelope) |
|---|---|---|---|---|
| 01 | KPI Summary | GET | `/kpi-summary` | `kpis[]` (revenue, net_profit, cash_balance, AR, AP, inventory_value — each with own trend) |
| 02 | Cash Flow Overview | GET | `/cash-flow` | `chart_series[] {month, inflow, outflow, net}`, `inflow`, `outflow` |
| 03 | Profit & Loss | GET | `/profit-loss` | `chart_series[] {month, income, expense, net}` |
| 04 | Income vs Expense | GET | `/income-vs-expense` | `chart_series[]`, `income`, `expense`, `net` |
| 11 | Invoice Overview | GET | `/invoice-overview` | `outstanding`, `status_breakdown {paid,pending,overdue,draft,total}`, `list_items[]` |
| 12 | Recent Transactions | GET | `/recent-transactions` | `list_items[] {source, date, description, account, party, debit, credit, amount}` |
| 13 | Bank Balances | GET | `/bank-balances` | `list_items[] {uid, name, balance}`, `account_count` |
| 16 | Top Customers | GET | `/top-customers` | `list_items[] {uid, name, revenue, percent}` |
| 17 | Top Selling Products | GET | `/top-selling-products` | `list_items[] {uid, name, sku, quantity, revenue, percent}` |
| 19 | Mini Expense & Cash | GET | `/mini-expense-cash` | `expense`, `cash_balance`, `cash_inflow`, `cash_outflow` |
| 22 | AR Aging | GET | `/ar-aging` | `chart_series[] {bucket, label, amount}` (Current/1-30/31-60/61-90/90+) |
| 23 | AP Aging | GET | `/ap-aging` | `chart_series[]` (same buckets) |
| 24 | Expense Breakdown | GET | `/expense-breakdown` | `list_items[] {category, amount, percent}` |
| 25 | Cash Runway | GET | `/cash-runway` | `value` = months (nullable), `cash_balance`, `avg_monthly_burn`, `runway_status` |

### HR / Attendance / Payroll

| # | Card | Method | Endpoint | Key fields | Gating |
|---|---|---|---|---|---|
| 06 | Attendance Summary | GET | `/attendance-summary` | `value` = rate %, `scheduled`, `present`, `late`, `on_leave` | — |
| 07 | Employee Overview | GET | `/employee-overview` | `value` = active count, `chart_series` (dept split), `new_joiners`, `upcoming_confirmations` | — |
| 08 | Leave Requests | GET | `/leave-requests` | `value` = pending, `counts {pending,approved,rejected}`, `list_items[]` | — |
| 09 | Today's Workforce | GET | `/todays-workforce` | `scheduled`, `on_shift`, `yet_to_check_in`, `on_leave`, `absent`, `is_approximation` | — |
| 10 | Upcoming Events | GET | `/upcoming-events` | `list_items[] {type, name, date}` (birthday/anniversary/contract_end), `is_approximation` | — |
| 20 | Payroll Snapshot | GET | `/payroll-snapshot` | `value` = total cost, `gross`, `net`, taxes, `employees_paid` | `is_payroll` |
| 21 | Tax Center Snapshot | GET | `/tax-center-snapshot` | `value` = total liability, `sales_tax {...}`, `payroll_tax {...}` | — |

### Tax / Support / Activity / Workflow / AI / Productivity

| # | Card | Method | Endpoint | Key fields | Gating |
|---|---|---|---|---|---|
| 05 | AI Business Insights | GET | `/ai-insights` | `list_items[] {key, severity, title, message, value, action_route}` | — |
| 14 | Open Support Tickets | GET | `/support-tickets` | `value` = open count, `list_items[] {ticket_number, status, age_days}`, `is_approximation` | `is_support_ticket` |
| 15 | Activity Feed | GET | `/activity-feed` | `list_items[] {action, content_name, object, actor, timestamp}` | `is_audit_log` |
| 18 | Approval Center | GET | `/approval-center` | `value` = total, `list_items[] {key, label, count, action_route}` | — |
| 26 | Quick Actions | GET | `/quick-actions` | `list_items[] {key, label, action_route}` | feature-filtered tiles |

**Gating column**: cards requiring a subscription feature return
`permission_state="restricted"` (with a `message`) when the company's plan does
not include that feature. Render the locked/upgrade state — do not treat it as an
error.

---

## 5. Frontend Work Checklist

1. **Shared dashboard data layer**
   - A single `useDashboardCard(endpoint, filters)` hook/service that injects the
     global filters and returns `{ data, isLoading, isError }`.
   - Fetch cards in parallel; never await one card before rendering another.

2. **Generic card renderer**
   - Handle all five states: `ok`, `empty`, `error` (+retry), `restricted`
     (+upgrade CTA), and `new` trend.
   - Render the trend chip from `trend_percent` / `trend_direction`
     (green up / red down / neutral flat / "New").

3. **Global filter bar**
   - Date range picker → `date_from` / `date_to`.
   - Comparison period, currency, accounting basis selectors.
   - On change, re-fetch all cards with the new filters.
   - Note: **branch/location filter is intentionally not supported** in v2
     (no branch model yet) — do not add a branch selector.

4. **Card-specific views**
   - KPIs: render the `kpis[]` array as the top headline row.
   - Charts: P&L, Income vs Expense, Cash Flow use `chart_series` (line/bar);
     AR/AP Aging and Expense Breakdown use `chart_series` (bar/donut).
   - Lists/tables: Recent Transactions, Top Customers/Products, Leave Requests,
     Activity Feed, Support Tickets, Approval Center, AI Insights, Quick Actions.

5. **Drill-down navigation**
   - Every card returns `action_route`; wire card click / "View all" to it.
   - List rows that include their own `action_route` (insights, approval center,
     quick actions) should navigate to that route.

6. **Time-series controls**
   - For P&L, Income vs Expense, Cash Flow add a `months` selector (3 / 6 / 12).

7. **Empty/loading polish**
   - Skeletons while `isLoading`.
   - Friendly empty copy when `data_state == "empty"`.

---

## 6. Known Approximations (surface in UI where relevant)

These cards use heuristics because there is no backing model yet. They return an
`is_approximation: true` flag — consider a subtle "estimated" tooltip:

- **Today's Workforce** — "scheduled" ≈ active employees with an assigned shift.
- **Upcoming Events** — derived from employee birthdays / work anniversaries /
  contract-end dates only (no manual HR calendar).
- **Open Support Tickets** — surfaced by status + age; no priority / SLA.

---

## 7. Acceptance Criteria

- Card totals reconcile with the detailed reports under identical filters.
- One failing card shows its error state; the dashboard still renders.
- Sensitive cards (payroll, activity, support) respect `permission_state`.
- Every card provides a working `action_route` drill-down.
