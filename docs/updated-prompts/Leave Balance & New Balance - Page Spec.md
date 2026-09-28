# Leave Balance & New Leave Balance — Page Spec

Reproducible spec for the **Leave Balance** page and its **New / Edit Leave Balance** drawer in the Violet Suite — the
HRIS screen where an admin defines a balance period and allocates leave days to each employee. Inline-style friendly.
Pairs with `Violet Suite - Design Spec.md`. Sidebar HRIS → Employee → Leave Balance.

---

## 0. Purpose & brief

> One screen to manage leave-balance periods: three KPI tiles, a premium table of defined balances, and a right
> **drawer** that captures the period (title + dates + leave year) and a **per-employee allocation grid**. One violet
> accent, tabular figures, `riseIn`/`popIn`/`slideInR` motion.

---

## 1. Page anatomy

```
Breadcrumb   Dashboard › HRIS › Leave Balance
Header       H1 "Leave Balances" + count chip ·spacer· [Print][Settings][New balance]
KPI          tiles — Total balances · This year · Years covered
Table        "Leave balances" — search · Balance · Leave year · From · To · Action · pager
Drawer       right slide-in — New/Edit leave balance (Balance details + employee allocation)
```

Full-width column. Sections `riseIn` staggered.

---

## 2. Header & KPIs

- **Header row** (`gap:13px`, `riseIn`): H1 "Leave Balances" 28/800 + violet **count chip** ("N balances") + spacer + 40px glass **Print** & **Settings** buttons + a violet **New balance** button (+ icon) opening the drawer.
- **KPI strip** `repeat(3,1fr); gap:14px`: white cards radius 18 — **Total balances** (violet, shield), **This year** (green, calendar), **Years covered** (teal, calendar) — icon chip + value (25/800 tabular) + label + animated `growH` edge bar.

---

## 3. Table

White card radius 20. Header: basket icon chip + "Leave balances" + "{n} balances defined" + search ("Search by balance…").
- **Column strip** (`#FBFAFE`): Balance · Leave year · From · To · Action — grid `minmax(0,1.6fr) 130px 150px 150px 90px; gap:12px`.
- **Rows** (`popIn`, hover violet left accent): a violet **basket icon tile** + balance name (13.5/700); a violet **leave-year chip** (e.g. 2025); From + To dates (`DD Mon YYYY`, tabular); edit + delete actions. Footer "Showing 1–N of M" + a Rows-per-page chip + page button.

---

## 4. New / Edit drawer

Right slide-in (`slideInR`, width 620px, grey `#F4F2FA` canvas, white sub-cards, header + scroll body + footer).
- **Header** (white): violet gradient basket icon tile + "New leave balance" / "Edit leave balance" + "Allocate leaves to employees for a period" + close.
- **Balance details card** (white, radius 16): a `1fr 1fr; gap:14px 18px` grid — **Title** * (span 2), **From date**, **Leave year**, **To date** (span 2). Date inputs tabular.
- **Employee allocation card** (white, radius 16): header "Employee allocation" + an "{n} employees" count chip; a `#FBFAFE` column strip (Employee · New · Sick · Casual · Earned · Edit) grid `minmax(0,1.4fr) 64px 70px 100px 90px 56px; gap:8px`; one **row per employee** (`popIn` staggered) = a gradient avatar + name + four **center-aligned number inputs** (per leave-type) + an edit icon. Each input edits that employee's allocation live.
- **Footer** (white): Cancel + violet **Create balance / Save changes** (check icon; greys to `#C9C2DD` until Title is filled).

---

## 5. Actions & functionality

| Action | Behavior |
|---|---|
| New balance | open drawer (blank, today→Dec dates, year 2026) |
| Title / dates / year | edit the period; Title gates Save |
| Allocation inputs | set each employee's New/Sick/Casual/Earned days live |
| Row edit / delete | reopen drawer pre-filled / remove balance |
| Search | filter balances by name |
| Save | upsert row → table + count chip + KPIs update |

---

## 6. Color usage

| Element | Color |
|---|---|
| Title / values | `#16172A` · labels `#44405C` · muted `#9A95AE` |
| Primary / icon tiles / leave-year chip / Save | `#7C4DFF` / `#5B3BC4` on `#EEE9FF` (hover `#8B5CF6`) |
| Total-balances KPI | violet `#7C4DFF`/`#EEE9FF` · This year green `#137A57`/`#DEF5E9` · Years covered teal `#0E7490`/`#E0F2F7` |
| Drawer canvas / sub-cards | `#F4F2FA` / `#FFFFFF` |
| Icon tile | `linear-gradient(140deg,#7C4DFF,#A78BFF)`; avatars per-employee gradients |
| Inputs | border `#D8D2EC`/`#E2DDF0`; focus `#7C4DFF` + `0 0 0 3px #EEE9FF` |
| Disabled Save | `#C9C2DD` |
| Delete hover | `#D2483E` on `#FCE8E8` |
| Card / strip | `#FFFFFF` / `#FBFAFE` |

---

## 7. Typography & spacing

- **Plus Jakarta Sans.** H1 28/800; KPI value 25/800; drawer title 15/800; card titles 13.5/800; column micro-headers 10–10.5/800 uppercase `0.06–0.07em`; balance name 13.5/700; allocation inputs 12.5/600. `tabular-nums` on all dates, years, counts, allocation numbers.
- KPI grid `repeat(3,1fr); gap:14px`. Table grid `minmax(0,1.6fr) 130px 150px 150px 90px; gap:12px`. Drawer 620px (`max-width:calc(100vw-28px)`); details grid `1fr 1fr; gap:14px 18px`; allocation grid `minmax(0,1.4fr) 64px 70px 100px 90px 56px; gap:8px`. Cards radius 20 (KPI/drawer-cards 18/16, pills 999); icon tile 34px; row basket tile 36px; allocation avatar 28px; header buttons 40px.

---

## 8. Motion

- **Entrances:** header `riseIn`; KPIs + table `riseIn 0.4s` staggered; table rows `popIn 0.22s ease {i*0.04}s`.
- **KPI edge bars:** `growH 0.6s cubic-bezier(0.22,1,0.36,1)`.
- **Drawer:** `slideInR 0.3s`; scrim `popIn`; allocation rows `popIn 0.2s ease {i*0.03}s`; inputs update live.
- **Save hover:** background `#7C4DFF → #8B5CF6`.
- **Icons:** inline SVG, `stroke-width:1.8–2.4`, round caps, 11–18px.

---

## 9. Paste-ready prompt

> Build a **Leave Balance** page + **New/Edit Leave Balance drawer** in the Violet Suite style (HRIS → Employee → Leave
> Balance). Header: H1 "Leave Balances" 28/800 `#16172A` + a violet count chip + glass Print/Settings buttons + a violet **New
> balance** button. A **KPI strip** `repeat(3,1fr); gap:14px` (Total balances violet / This year green / Years covered teal —
> icon chip, value 25/800, animated edge bar). A **Leave balances** table (radius 20): header + "{n} balances defined" +
> search; a `#FBFAFE` strip (Balance · Leave year · From · To · Action, grid `minmax(0,1.6fr) 130px 150px 150px 90px`); rows =
> a violet basket icon tile + balance name, a violet **leave-year chip**, From/To dates (`DD Mon YYYY`), and edit/delete;
> footer "Showing 1–N of M" + rows-per-page + pager. A right **drawer** (`slideInR`, 620px, grey `#F4F2FA` canvas, white
> sub-cards): a **Balance details** card (Title* span 2, From date, Leave year, To date span 2 — `1fr 1fr` grid) and an
> **Employee allocation** card (a `#FBFAFE` strip Employee · New · Sick · Casual · Earned · Edit, grid `minmax(0,1.4fr) 64px
> 70px 100px 90px 56px`; one row per employee = gradient avatar + name + four center number inputs + edit icon); footer Cancel
> + violet **Create balance / Save changes** (disabled `#C9C2DD` until Title filled). Inputs focus to `#7C4DFF` + `0 0 0 3px
> #EEE9FF`; Plus Jakarta Sans; tabular figures; springy `popIn`/`riseIn`/`slideInR` motion. Saving upserts the table row and
> updates the count chip + KPIs.
