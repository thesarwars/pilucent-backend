# Balanzify — Super Admin · Subscription Management
## Complete Design Specification & Generation Prompt

> A production-ready, build-from-scratch prompt for the **platform-operator (Super Admin)** side of Balanzify's billing engine — the internal cockpit where staff define plans, entitlements, limits, add-ons, coupons, referrals, trials, and manage every tenant subscription, invoice, and audit event. Every value below is exact (colors, type, dimensions, components, screens, data, interactions). Hand this to a designer, a frontend developer, or an AI design tool to reproduce the panel faithfully.

> **This is a different surface from the company-side module.** Company-side = violet `#7C4DFF`, Plus Jakarta Sans, lavender glassmorphism, scaled fixed canvas. Super Admin = **indigo `#5B5BF0`**, **Sora + Inter + JetBrains Mono**, **dark sidebar rail on a light `#F5F6FB` workspace**, responsive fluid layout. Keep them visually distinct.

---

## 0. Role & Goal

You are a **senior product designer + frontend engineer** building the **Super Admin Subscription Management** console for **Balanzify**, an enterprise SaaS finance/HR platform. Build a **fully navigable, fully functional internal web app** (desktop, design width **1440**, fluid to ~1280–1920) with a **calm data-dense operator aesthetic**: dark left rail, light glassy workspace, indigo accent, hand-built charts, and **real CRUD** — every create/edit/delete/toggle mutates shared state, reflects across screens, and writes to an audit trail.

**Tone:** precise, trustworthy, operational. This is a back-office control panel, not a marketing surface. Density over whitespace, clarity over flourish. No dark patterns; destructive actions always confirm.

---

## 1. Layout System & Dimensions

| Token | Value |
|---|---|
| App frame | `position: fixed; inset: 0; display: flex` over `#F5F6FB` |
| **Sidebar rail** | **260px** fixed width, full height, dark gradient, `border-right: 1px solid rgba(255,255,255,.06)` |
| **Topbar** | **72px** height, sticky, glassy (`rgba(245,246,251,.8)` + `blur(14px)`), `border-bottom: 1px solid #E7E8F2` |
| **Content scroll area** | fills remaining width, `overflow-y: auto`, padding **28px** |
| Content max-width | **1340px**, centered (`margin: 0 auto`) |
| Section vertical gap | **22px** (screen-level), **16–18px** (within sections) |
| Card radius | **18–20px** (18 KPI/tight, 20 default) |
| Card padding | **20–24px** (20 KPI/list, 22 default, 24 chart/section) |
| Card border / shadow | `1px solid #E7E8F2` · `0 1px 3px rgba(16,22,46,.05)` |
| Table row padding | `14px 20px`; header `13px 20px` |
| Grid gaps | **16px** (cards/KPIs), **14px** (table columns) |
| Modal width | 440 (confirm) · 560 (add-on/metric) · 620 (general) · 760 (Plan Builder) |
| Drawer width | 560 (tenant) · 580 (coupon), right-anchored, full height |

**Scaling:** unlike the company-side fixed canvas, this app is a **real fluid responsive layout** — flexbox shell, the content column flexes, tables scroll horizontally (`overflow-x:auto`) inside cards when needed. No `transform: scale()`.

---

## 2. Color Palette  (token object `S`)

### Core surfaces & neutrals
| Name | Hex | Use |
|---|---|---|
| ink900 | `#0B1020` | Darkest — sidebar base, primary ink, dark panels |
| ink800 | `#111935` | Toast background, dark buttons |
| **surface** | `#F5F6FB` | App workspace background |
| card | `#FFFFFF` | All card/table surfaces |
| line | `#E7E8F2` | Borders, dividers, table hairlines |
| ink (text) | `#0B1020` | Headings, key values |
| body | `#444A66` | Body text |
| muted | `#6B7090` | Secondary text, labels |
| faint | `#9AA0BF` | Tertiary, placeholders, meta, captions |

### Brand & accent
| Name | Hex | Use |
|---|---|---|
| **brand** | `#5B5BF0` | Indigo — primary buttons, active nav, accents, charts |
| violet | `#7C5CFC` | Secondary accent, gradient partner, ARR series |

### Semantic (each pairs a foreground with a soft tint background)
| Tone | FG | Soft BG | Use |
|---|---|---|---|
| good | `#0FB67A` | `#E2F7EF` | Active, Paid, healthy, within-limit |
| warn | `#F59E0B` | `#FCF1DD` | Overage, grace, at-risk, past-due-ish |
| bad | `#F2415A` | `#FDE5E9` | Failed, suspended, destructive, hard-block |
| info | `#2E8FF2` | `#E3EFFD` | Trialing, soft-warning, neutral notice |
| brand | `#5B5BF0` | `#ECECFE` | Recommended, selected, plan accents |
| violet | `#7C5CFC` | `#EFEAFE` | Secondary categorization |
| gold | `#C9A227` | `#F6EFD7` | Enterprise, coupons, rewards |
| mute | `#6B7090` | `#EEF0F6` | Default/neutral badges, disabled |

### Signature gradients
- **Sidebar:** `linear-gradient(175deg,#0B1020 0%,#080C19 100%)` + a top-left radial glow `radial-gradient(circle, rgba(91,91,240,.4), transparent 65%)`.
- **Brand / primary button & logo:** `linear-gradient(120deg,#5B5BF0,#7C5CFC)`.
- **Active nav item:** `linear-gradient(100deg,rgba(91,91,240,.32),rgba(124,92,252,.22))` + left teal→indigo pill marker `linear-gradient(#2FE0C8,#5B5BF0)`.
- **Live Pricing Simulator panel (dark):** `linear-gradient(155deg,#0B1020,#171a3a)` + violet glow orb; total figure in mint `#2FE0C8`.
- **Logo mark:** `conic-gradient(from 140deg,#5B5BF0,#7C5CFC,#2FE0C8,#5B5BF0)` with an inset `#0B1020` square and white "B".

---

## 3. Typography

| Family | Weights | Use |
|---|---|---|
| **Sora** | 400–800 | Display — page titles, card titles, big numbers, plan names, logo |
| **Inter** | 400–700 | Body — labels, table cells, buttons, nav, descriptions |
| **JetBrains Mono** | 400–700 | Numerics, codes, IDs, prices, dates, object refs (`tabular-nums`) |

Apply `font-feature-settings:'cv11','ss01'` on the root; `font-variant-numeric: tabular-nums` on all figures (helper class `.sa-num`).

| Role | Size | Weight | Tracking | Family / color |
|---|---|---|---|---|
| Topbar page title | 21px | 700 | −0.5px | Sora / ink |
| Topbar subtitle | 12.5px | 500 | — | Inter / muted |
| Card / section title | 16px | 700 | −0.2px | Sora / ink |
| KPI value | 26px | 800 | −0.6px | Sora / ink |
| Big stat (revenue/balance) | 30px | 800 | −1px | Sora / ink |
| Plan price | 30px | 800 | −1.2px | Sora / ink |
| Eyebrow / overline | 11px | 700 | +0.1em, UPPER | Inter / faint |
| Nav group label | 10px | 700 | +0.14em, UPPER | Inter / white-32% |
| Table header | 10.5px | 700 | +0.07em, UPPER | Inter / faint |
| Table cell | 12.5–13.5px | 500–700 | — | Inter / body·ink |
| Body / description | 12.5–13.5px | 500 | — | Inter / body·muted |
| Button label | 12.5 (sm) / 13.5 (md) | 600 | −0.1px | Inter |
| Code / ID / price | 11–13.5px | 600–700 | — | JetBrains Mono |

---

## 4. Component Library

### 4.1 Button (`.sa-btn`)
Radius 11px (sm 9px), weight 600, `transition: transform .08s, box-shadow/bg/color .18s`; active `translateY(.5px) scale(.99)`; disabled opacity .45.
- **Sizes:** `md` 40px h / `0 16px` / 13.5px · `sm` 32px h / `0 12px` / 12.5px.
- **Variants:** `primary` (brand gradient, white, shadow `0 8px 20px -8px rgba(91,91,240,.7)`) · `ghost` (white, ink, `inset 0 0 0 1px #E7E8F2`) · `soft` (`#ECECFE` bg, brand text) · `danger` (`#FDE5E9` bg, `#F2415A` text) · `dark` (`#111935`, white). Optional leading/trailing icon.

### 4.2 Badge (`SBadge`)
Height 24px, radius 20px, padding `0 10px` (`0 11px 0 9px` with dot), 12px/700, soft-tint pairs from the semantic table. Optional 6px leading dot or 12px icon.

### 4.3 Card (`SCard`) — see §1 dimensions. Optional `hover` lift.

### 4.4 KPI Card (`KPICard`)
Radius 18, pad 20. Top row: 38px rounded-square tinted icon chip (left) + optional **sparkline** (right, 64×26). Then 12px muted label, 26px Sora value, then a trend pill (`▲/▼` + %, in good/bad soft tint) + faint context text.

### 4.5 Filter chip (`SChip` / `.sa-chip`)
Height 34px, radius 20px (pill), 12.5px/600. Default white + `#E7E8F2` border, muted text; hover darkens border; **active = `#0B1020` bg, white text**. Optional trailing count bubble (`.sa-chipcount`).

### 4.6 Segmented control (`SSegmented`)
Padding 4px, bg `#EEF0F6`, radius 11px. Active segment = white pill + `0 2px 6px -2px` shadow; inactive muted. Supports inline mini-badge (e.g. "−20%", "Save 20%").

### 4.7 Toggle (`SToggle` / `.sa-toggle`)
42×24px, off `#D4D7E8`, on brand gradient; 18px white knob slides `.18s`.

### 4.8 Input / Select (`.sa-input`, `.sa-select`)
40px h, radius 11px, `1px #E7E8F2`, 13.5px. Focus: border brand + ring `0 0 0 3px rgba(91,91,240,.16)`. Mono variant for codes/prices. Form field (`SField`): 12px/600 body label, optional prefix/suffix glyph, 11.5px faint hint.

### 4.9 Range sliders
- **Dark (simulator)** `.sa-range`: 8px track `linear-gradient(brand var(--fill), rgba(255,255,255,.12))`, 24px white thumb w/ 5px brand border + indigo glow.
- **Light (forms)** `.sa-range-l`: same with `#E7E8F2` track.

### 4.10 Version pill (`VPill`) — mono 11px, soft-tint, radius 7px (e.g. `v3`).

### 4.11 Progress bar (`SProgress`) — track `#EEF0F6`, rounded; fill auto-colors brand→warn(≥85%)→bad(≥100%); used in usage cells, redemption caps, plan-link counts.

### 4.12 Avatar (`SAvatar`) — rounded-square (radius = size×0.3), brand/teal gradient, Sora white monogram. Logo (`SLogo`) — conic mark + "Balanzify" wordmark, optional "SUPER ADMIN" eyebrow.

### 4.13 Table scaffold (`THead` + grid rows)
CSS-grid rows (`grid-template-columns` per screen), header is uppercase 10.5px faint; rows `.sa-tr` hover `#FAFAFE`; row-level icon buttons (`.sa-iconbtn`, 30–34px, hover → brand). Tables scroll horizontally inside their card on narrow widths.

### 4.14 Overlays
- **Modal (`SModal`):** centered, radius 24px, scrim `rgba(11,16,32,.5)` + blur 4px, `saModalIn .3s` scale/translate-in; sticky header + body + footer action row.
- **Drawer (`SDrawer`):** right-anchored, full height, `surface` bg, `saDrawerIn .32s` slide-in; sticky `SDrawerHead` (avatar + title + sub + close) and sticky footer action bar.
- **Toast (`SToast`):** bottom-center dark `#111935` pill, min-width 340, tinted icon chip + title + msg, `saToastIn .32s`, auto-dismiss 4s.
- **Wizard rail (`WizardRail`):** numbered 28px circles — done = emerald `#0FB67A` with check, current = brand, future = muted; connector bars fill emerald as completed.
- **Confirm modal (`ConfirmModal`):** 440px, tinted icon, title + message, Cancel + (danger/primary) confirm.

---

## 5. App Shell

```
<div .sa-root> (fixed, flex, #F5F6FB)
 ├─ <Sidebar> 260px, dark gradient + radial glow
 │   ├─ Logo (B mark + "Balanzify", eyebrow "SUPER ADMIN")
 │   ├─ Nav groups (label + items):
 │   │    OVERVIEW   → Dashboard
 │   │    CATALOG    → Plans (4) · Modules & Features · Limits & Metrics · Add-ons
 │   │    GROWTH     → Coupons & Offers · Referral Program · Trials (38)
 │   │    OPERATIONS → Tenant Subscriptions · Invoices & Payments (7) · Audit Logs
 │   │    (active item: gradient fill + left teal→indigo pill marker; count bubbles)
 │   └─ Admin footer card: avatar "Anik Mahmud / Platform Owner" + settings cog
 └─ <Main> (flex column)
     ├─ <Topbar> 72px sticky glass: page title + subtitle · search (⌘K) · bell(dot) · help
     └─ <ScrollArea> pad 28, max-w 1340 centered → routed screen
 + Global overlay layer: PlanBuilder modal · Add-on modal · Metric modal · Confirm modal · Tenant drawer · Coupon drawer · Toast
```

**Nav item** (`.sa-nav`): 11px gap, radius 11, `9px 12px`, white-62% → hover white-06% bg → active gradient + 4px left marker. Count bubble mono 11px.

---

## 6. State, Routing & Interaction Model

- **Central reactive store** (`saStore`) seeded from the data model holds ALL mutable collections (plans, matrix, metrics, addons, coupons, refRules, referrals, trialSettings, trials, tenants, invoices, audit). Pub/sub; `useSaStore()` hook re-renders subscribers on `emit()`.
- **Every mutation logs to the audit trail** (`saStore.log(action, object, cat)`) and surfaces on the Dashboard activity feed.
- **Routing store** (`saNav`): `route` (persisted to localStorage), `modal` (+`modalData`), `drawer` (`{type,data}`), `toastData`. Helpers `saGo`, `saModal`, `saDrawer`, `saToast`, `saConfirm`.
- **Destructive actions** route through the Confirm modal.

### Required working flows (all real, not faked)
1. **Plans:** New Plan → 5-step Plan Builder (create) → publish adds v1 draft. Edit → builder preloaded → publish bumps version. Clone → private draft copy. Visibility toggle. Archive (confirm) → removes.
2. **Plan Builder live pricing simulator** — drag the simulated-employees slider; base + overage recompute the monthly total in real time (the signature moment).
3. **Entitlement matrix** — tap any boolean cell to toggle access; Publish rolls a new version + invalidates cache.
4. **Metrics / Add-ons** — create/edit via modal, status toggle, delete (confirm).
5. **Coupons** — New/Edit drawer persists code/type/value/cap/dates/eligible-plans/stacking; live discount preview; delete (confirm); status toggle.
6. **Referrals** — Approve (issues $50 reward) / Reject (zeroes); rule toggles persist.
7. **Trials** — Extend +7d; **Convert** removes the trial and creates an active tenant.
8. **Tenants** — row → detail drawer (billing math, usage bars, timeline); Override plan (dropdown), Apply credit, Extend, Suspend/Reactivate — all mutate and the drawer reflects live.
9. **Invoices** — Retry settles Failed→Paid; Refund (confirm) → Refunded; KPI totals recompute.
10. **Tables** — search + filter chips actually filter every list.

---

## 7. Screen-by-Screen Specification (11 views)

### 1 · Dashboard
- **8 KPI cards** (4-col grid) each w/ sparkline: MRR `$128,940` ▲8.2% · ARR `$1.55M` ▲11.4% · Active Subscriptions `271` ▲+14 · Active Trials `38` (42% conv) · Monthly Churn `2.1%` ▼ improving · Failed Payments `7` ($1,380 in dunning) · Overage Revenue `$14,320` ▲22% · Coupon Redemptions `64` ▲+9.
- **Row 2:** Recurring Revenue Trend (smooth area chart, MRR/ARR segmented toggle, trailing 12 mo) `1.55fr` + Plan Distribution donut + legend `1fr`.
- **Row 3 (3-col):** Overage Revenue bar chart · Trial→Paid funnel (90→71→48→38 with conversion %) · **Recent Activity** feed (live from the audit store: actor + action + object · time).

### 2 · Plans
- Monthly/Annual segmented (`−20%` badge) + **New Plan** primary.
- **4 plan cards** (top color bar, name + dot, tagline, big price, dashed spec box [employees / included users / overage], subscriber count + version pill, Edit / Clone / Visibility buttons; Growth featured w/ "Most Popular"). Starter `$150`, Growth `$250`, Scale `$450`, Enterprise `Custom`.
- **All Plans table:** Plan · Visibility · Monthly · Annual · Employees · Overage · Subscribers · version + edit + archive. Row click → builder.

### 3 · Modules & Features (entitlement matrix)
- Feature filter input + Export + **Publish**.
- Grid `1.8fr repeat(4,1fr)`: sticky-style header with the 4 plan columns (Growth tinted). **Module group bands** (Accounting Core, Sales & Invoicing, Inventory, Payroll, Reports & AI, Support) each with feature rows. Cells render as ✓ (good chip) / – (faint) / **metered value pill** (e.g. `2k`, `∞`, `8`). Tap boolean cells to toggle. Legend footer (Included / Metered / Not included).

### 4 · Limits & Usage Metrics
- **Billable Metrics table** (New Metric): Metric (icon) · Code (mono pill) · Unit · Enforcement badge · Overage rate · edit. Rows: Active Employees ($4–6/emp, Auto overage), Login Users ($9, Soft warning), Branches (Hard block), Payroll Runs ($2/run), Storage ($15/50GB), AI Credits ($25/1k, Grace). Row → metric editor.
- **Enforcement Models** (6 cards): Hard Block, Soft Warning, Auto Overage, Manual Approval, Grace Overage, Snapshot Billing — each a tone badge + description.

### 5 · Add-ons
- **Catalog table** (New Add-on): Add-on (icon) · Code · Pricing model · Price · Cycle · Linked plans (count + mini progress) · Status (toggle) · edit. 7 rows (Extra Employee Capacity $6, Extra User Seats $9, Premium Support $99, Payroll Tax Filing $49, AI Credit Pack $25 one-time, Extra Storage $15 draft).

### 6 · Coupons & Offers
- Filter chips (All/Active/Scheduled/Depleted) + **New Coupon**.
- **Table:** Code (tag icon, mono) · Type · Value · Eligibility · Redemptions (x/cap + progress) · Status · Ends · edit/delete. Row → **Coupon Builder drawer**: code, discount type segmented, value/duration/min-invoice/cap/dates, eligible-plan tiles, stacking toggles, and a **dark live discount preview** (base → discount → first invoice). Create/Save/Delete persist.

### 7 · Referral Program
- 3 stat KPIs (Referred companies 42 · Pending rewards $650 · Approved & paid $2,150).
- **Program Rules** card (reward type, trigger, cap, anti-abuse) each with a persisted toggle.
- **Referral Activity table:** referrer (avatar) · referred · reward · status badge (Approved/Pending/Rejected/Redeemed) · date · Approve/Reject actions on pending rows.

### 8 · Trials
- 3 stat KPIs (Active 38 · Converting ≤3 days · 30-day conversion 42%).
- **Default Trial Settings** (6 tiles: 14 days, no card upfront, auto-convert, reminders D7/3/1, +7 max extension, 1/domain).
- **Active Trials table:** company (avatar) · plan · owner email · card ✓/✗ · days-left (color-coded + progress) · health badge (Engaged/At risk/Idle) · **+7d / Convert** actions. Convert (confirm) → creates a tenant.

### 9 · Tenant Subscriptions
- Search + filter chips (All/Active/Trialing/Past Due/Suspended) + Export.
- **Table:** company (avatar, currency·users) · plan · status badge · employees (n/max + "over" badge) · usage bar · MRR · renewal · open. Row → **Tenant detail drawer**: status pills, current billing breakdown (base + overage + users + renewal + effective MRR), usage mini-bars, subscription timeline, and footer actions (Override plan dropdown · Apply credit · Extend · Suspend/Reactivate).

### 10 · Invoices & Payments
- 3 KPIs (Collected this cycle · Outstanding · Failed in dunning) — recompute live.
- Filter chips (All/Paid/Open/Failed/Past Due) + Export.
- **Ledger table:** invoice (mono) · company · amount · method · date · status badge · **Retry** (failed/past-due) / **Refund** (paid, confirm) / Download.

### 11 · Audit Logs
- Search + category chips (All/Plan/Billing/Trial/Coupon/Referral).
- **Table** (live, newest first, scrollable): actor (avatar or System cpu icon) · action · object (mono pill) · category badge · timestamp. Auto-populated by every mutation across the app.

---

## 8. Data Model (dummy seed — never empty)

```
Plans:    Starter $150/mo ($1,440/yr) · 1–25 emp · 10 users · $6 overage · 142 subs · v3 · Public · popular
          Growth  $250/mo ($2,400/yr) · 26–100 · 25 users · $5 · 86 subs · v2 · Public · ★Most Popular
          Scale   $450/mo ($4,320/yr) · 101–300 · 75 users · $4 · 31 subs · v2 · Public
          Enterprise Custom · unlimited · 12 subs · v1 · Private
Pricing:  overage = max(0, employees − included) × rate;  total = base + overage;  annual = base×12×0.8
Metrics:  employees(Auto, $4–6), users(Soft, $9), branches(Hard, —), payroll_runs(Auto, $2),
          storage_gb(Soft, $15/50GB), ai_credits(Grace, $25/1k)
Add-ons:  addon_emp $6 · addon_seat $9 · addon_support $99 · addon_tax $49 · addon_ai $25 one-time · addon_storage $15 draft
Coupons:  WELCOME20 (20%·3mo, new, 38/100) · SAVE50FIRST ($50, all, 64/200) · FREEMONTH (1mo, annual, 21/50)
          PAYROLL50 (50% add-on, 12/80) · ANNUAL25 (depleted 150/150) · SPRINGOFF (scheduled 0/120)
Referral: $50 credit on first paid invoice · cap 5/mo · block self+duplicate · 42 referred / $650 pending / $2,150 paid
Trials:   14-day, no card upfront, auto-convert, reminders D7/3/1, +7 max, 1/domain · 6 sample companies
Tenants:  Northwind Traders, Acme Logistics(over limit), Brightside Cafe(past_due), Delta Build(grace),
          Vertex Health(Enterprise), Cedar & Co(trial), Olive Branch(trial), Harbor Freight(suspended),
          Pinewood Studios, Spark Robotics(canceled) — currency, users, emp/max, MRR, renewal
Invoices: INV-4821…4814 — $0–$1,850, Visa/MC/ACH/Wire, statuses Paid/Open/Failed/Past Due/Refunded
Audit:    seed entries across Plan/Billing/Trial/Coupon/Referral; grows with every mutation
Operators: Anik Mahmud (Platform Owner), Nadia Rahman; "System" for automated events
```

---

## 9. Charts (hand-built SVG/CSS, no libraries)
- **Sparkline** — smooth path + gradient fill, 64×26, in KPI cards.
- **Area chart** — smooth cubic path, gradient fill, dashed gridlines, x-axis labels, end dot; MRR/ARR toggle.
- **Donut** — stroked segments, center total + label; plan distribution.
- **Bar chart** — gradient bars, value labels on top; overage revenue.
- **Funnel** — horizontal proportional bars with step value + conversion %.
- **Timeline** — vertical connected nodes (tinted icon chips); tenant subscription history.

---

## 10. Quality Bar
- Indigo `#5B5BF0` is the single accent; semantic tones only for status. Two structural surfaces: dark rail + light workspace.
- Tabular numerals on every figure; JetBrains Mono for codes/IDs/prices/dates.
- Every action does something real — mutate state, reflect across screens, log to audit, confirm if destructive, toast on success.
- Data density with breathing room on the 16/22px rhythm; tables scroll inside cards, never break layout.
- Hand-built charts only; no chart dependencies.
- Operator-grade copy: precise, neutral, no marketing tone. Destructive actions are never one click.
- Visually distinct from the company-side module (indigo/Sora/dark-rail vs violet/Jakarta/glassmorphism).
