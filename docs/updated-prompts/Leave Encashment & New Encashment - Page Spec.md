# Leave Encashment & New Encashment — Page Spec

Reproducible spec for the **Leave Encashment** page and its **New Leave Encashment** drawer in the Violet Suite — the
HRIS screen where an admin converts an employee's unused leaves into pay. Inline-style friendly. Pairs with
`Violet Suite - Design Spec.md`, `Leave Balance & New Balance - Page Spec.md`. Sidebar HRIS → Employee → Leave Encashment.

---

## 0. Purpose & brief

> One screen to record leave encashments: three KPI tiles (count · total $ · employees), a premium records table with
> a friendly empty state, and a wide right **drawer** that captures the employee/date/balance and a **per-leave-type
> calc grid** that totals to a live payout. One violet accent, tabular money, `riseIn`/`popIn`/`slideInR` motion.

---

## 1. Page anatomy

```
Breadcrumb   Dashboard › HRIS › Leave Encashment
Header       H1 "Leave Encashments" + count chip ·spacer· [Print][Settings][Add new]
KPI          tiles — Encashments · Total amount · Employees
Table        "Leave encashments" — search · Employee · Encashment date · Total amount · Action · pager
Drawer       right slide-in — New leave encashment (details + leave-type calc grid + total footer)
```

Full-width column. Sections `riseIn` staggered.

---

## 2. Header & KPIs

- **Header row** (`gap:13px`): H1 "Leave Encashments" 28/800 + a violet **count chip** ("N records") + spacer + 40px glass **Print** & **Settings** buttons + a violet **Add new** button (+ icon) opening the drawer.
- **KPI strip** `repeat(3,1fr); gap:14px`: white cards radius 18 — **Encashments** (violet, card icon), **Total amount** (green, $), **Employees** (teal, people) — icon chip + value (25/800 tabular) + label + animated `growH` edge bar.

---

## 3. Records table

White card radius 20. Header: card icon chip + "Leave encashments" + "{n} records · ${total} total" + search ("Search encashments").
- **Column strip** (`#FBFAFE`): Employee · Encashment date · Total amount (right) · Action (right) — grid `minmax(0,1.6fr) 170px 160px 90px; gap:12px`.
- **Rows** (`popIn`, hover violet left accent): gradient avatar + employee name + "{n} leave types" sub; encashment date (`DD Mon YYYY`); bold **total amount** (right, tabular); edit + delete.
- **Empty state** (no records): centered 48px violet icon tile + "No encashments yet" + "Record a leave encashment to get started." + a soft **Add new** button.
- Footer: "Showing 1–N of M" (or "No records") + a Rows-per-page chip + page button.

---

## 4. New encashment drawer

Right slide-in (`slideInR`, width 720px, grey `#F4F2FA` canvas, white sub-cards, header + scroll body + sticky total footer).
- **Header** (white): violet gradient card icon tile + "New leave encashment" + "Encash unused leaves for an employee" + close.
- **Encashment details card**: a `1.4fr 1fr 1fr; gap:14px 18px` grid — **Employee*** select ("Select an employee"), **Encashment date** (date input), **Leave balance** select ("Select" → e.g. 2026 Annual).
- **Leave-type calc card**: a `#FBFAFE` column strip — Leave type · Balance · Encashable · Days · Amount/day · Total · (remove), grid `minmax(0,1.3fr) 76px 96px 96px 100px 90px 44px; gap:8px`. Each **line row** (`popIn`): a **leave-type select** (New/Sick/Casual/Earned, "Select a leave"), four center number inputs (Balance, Actual encashable, Encashment days, Amount/day), a computed **Total** (= days × rate, right, bold), and a trash button. An **Add new** pill adds a line.
- **Footer** (white, sticky): "Total encashment" + a big live **$total** (17/800, = Σ line totals); spacer; **Cancel** + violet **Create encashment** (check icon; greys to `#C9C2DD` until an employee is chosen and total > 0).

---

## 5. Actions & functionality

| Action | Behavior |
|---|---|
| Add new | open drawer (today's date, one blank line) |
| Employee / date / balance | set the header context |
| Add new line / remove | add/remove a leave-type calc row |
| Days × Amount/day | computes that line's Total live |
| Live total | sums all line totals into the footer + Save gate |
| Create encashment | append a record → table + count chip + KPIs update |
| Search / delete | filter / remove records |

---

## 6. Color usage

| Element | Color |
|---|---|
| Title / values | `#16172A` · labels `#44405C` · muted `#9A95AE` |
| Primary / icon tiles / Save | `#7C4DFF` on `#EEE9FF` (hover `#8B5CF6`) |
| Encashments KPI | violet `#7C4DFF`/`#EEE9FF` · Total amount green `#137A57`/`#DEF5E9` · Employees teal `#0E7490`/`#E0F2F7` |
| Drawer canvas / sub-cards | `#F4F2FA` / `#FFFFFF` |
| Icon tile | `linear-gradient(140deg,#7C4DFF,#A78BFF)`; avatars per-row gradients |
| Inputs | border `#D8D2EC`/`#E2DDF0`; focus `#7C4DFF` + `0 0 0 3px #EEE9FF` |
| Disabled Save | `#C9C2DD` |
| Delete hover | `#D2483E` on `#FCE8E8` |
| Card / strip | `#FFFFFF` / `#FBFAFE` |

---

## 7. Typography & spacing

- **Plus Jakarta Sans.** H1 28/800; KPI value 25/800; drawer title 15/800; card titles 13.5/800; column micro-headers 10–10.5/800 uppercase `0.05–0.07em`; employee name 13.5/700; line inputs 12.5/600; footer total 17/800. `tabular-nums` on all money, days, dates, counts.
- KPI grid `repeat(3,1fr); gap:14px`. Table grid `minmax(0,1.6fr) 170px 160px 90px`. Drawer 720px (`max-width:calc(100vw-28px)`); details grid `1.4fr 1fr 1fr`; line grid `minmax(0,1.3fr) 76px 96px 96px 100px 90px 44px; gap:8px`. Cards radius 20 (KPI/sub-cards 18/16, pills 999); icon tile 34px; row avatar 36px; header buttons 40px.

---

## 8. Motion

- **Entrances:** header `riseIn`; KPIs + table `riseIn 0.4s` staggered; table rows `popIn 0.22s ease {i*0.04}s`.
- **KPI edge bars:** `growH 0.6s cubic-bezier(0.22,1,0.36,1)`.
- **Drawer:** `slideInR 0.3s`; scrim `popIn`; line rows `popIn 0.18s`; line/footer totals recompute live.
- **Save hover:** background `#7C4DFF → #8B5CF6`.
- **Icons:** inline SVG, `stroke-width:1.7–2.4`, round caps, 11–22px.

---

## 9. Paste-ready prompt

> Build a **Leave Encashment** page + **New Leave Encashment drawer** in the Violet Suite style (HRIS → Employee → Leave
> Encashment). Header: H1 "Leave Encashments" 28/800 `#16172A` + a violet count chip + glass Print/Settings buttons + a violet
> **Add new** button. A **KPI strip** `repeat(3,1fr); gap:14px` (Encashments violet / Total amount green / Employees teal —
> icon chip, value 25/800, animated edge bar). A **Leave encashments** table (radius 20): header + "{n} records · ${total}
> total" + search; a `#FBFAFE` strip (Employee · Encashment date · Total amount · Action, grid `minmax(0,1.6fr) 170px 160px
> 90px`); rows = gradient avatar + name + "{n} leave types", date, bold total, edit/delete; a friendly **empty state** ("No
> encashments yet" + Add-new button); footer pager. A right **drawer** (`slideInR`, 720px, grey `#F4F2FA` canvas, white
> sub-cards): an **Encashment details** card (Employee* select, Encashment date, Leave balance select — `1.4fr 1fr 1fr` grid)
> and a **leave-type calc** card with a `#FBFAFE` strip (Leave type · Balance · Encashable · Days · Amount/day · Total ·
> remove) and add-able line rows (leave-type select + four center number inputs + a computed Total = days × rate + trash), an
> **Add new** pill; a sticky footer "Total encashment" + live **$total** + Cancel + violet **Create encashment** (disabled
> `#C9C2DD` until employee chosen and total > 0). Inputs focus `#7C4DFF` + `0 0 0 3px #EEE9FF`; Plus Jakarta Sans; tabular
> money; springy `popIn`/`riseIn`/`slideInR` motion. Saving appends a record and updates the count chip + KPIs.
