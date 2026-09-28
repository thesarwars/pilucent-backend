# Employee Detail — Tabs Spec (General · Job · Contact · Payment · Attendance · Tax Info · Payroll)

Reproducible spec for the **Employee Detail** page in the Violet Suite — a two-pane profile screen with a sticky
profile card on the left and a tabbed detail area on the right. Inline-style friendly. Pairs with
`Violet Suite - Design Spec.md`, `Employees - Page Spec.md`. Opens when a name is clicked on the Employees list.

---

## 0. Purpose & brief

> One employee, everything about them. A sticky **profile card** (avatar, status, contact tiles, meta) beside a
> **sticky tab bar** and per-tab content built from icon-headed **section cards** of read-only fields. One violet
> accent, tabular figures, `riseIn`/`popIn` motion.

---

## 1. Page anatomy & layout

```
(sticky topbar — search + account, gradient-fade, top:0)
[‹] Detail Employee  (sticky page header, gradient-fade, below topbar)
┌ grid: 330px minmax(0,1fr); gap:18px; align-items:start ──────────────┐
│ LEFT  sticky profile card (top:124px)        │ RIGHT  detail column   │
│  • gradient banner + overlapping avatar       │  • sticky tab bar      │
│  • name + role + ACTIVE pill                   │  • section cards per   │
│  • email / phone contact tiles                 │    active tab          │
│  • Department / Office / Line-manager tiles     │                       │
│  • dark "Action ▾" button                       │                       │
└──────────────────────────────────────────────────────────────────────┘
```

- The scroll region's topbar (`sticky top:0`, `linear-gradient(180deg, rgba(245,243,251,0.92) 70%, transparent)` + blur) and the page header (`[‹] Detail Employee`, sticky below it) both pin. Profile card + tab bar pin at `top:124px`. Sections `riseIn` staggered.

---

## 2. Left profile card

White, radius 22, **card shadow**, overflow hidden, sticky.
- **Gradient banner** (`linear-gradient(135deg,#7C4DFF,#A78BFF)`, ~84px tall) with a soft radial glow orb; the **avatar** (84px circle, gradient or photo, 4px white ring, initials) overlaps the banner bottom (`margin-top:-42px`, own stacking context so it isn't clipped).
- **Name** 19/800 `#16172A`, **role** 12.5 `#9A95AE`, a glowing green **ACTIVE** pill (`#137A57`/`#DEF5E9`, dot) with a chevron to change status.
- **Contact tiles** — email (violet icon chip) and phone (green icon chip), each a `#FBFAFE` rounded tile (label 10.5 + value 13/700).
- **Meta tiles** — Department (violet building), Office (teal pin), Line manager (amber person): icon-chip rows with a hover highlight + chevron.
- **Action ▾** — full-width dark button (`#16172A`, hover `#2A2440`) with a dropdown caret.

---

## 3. Tab bar

Sticky white pill-bar (radius 20, `padding 6px 8px`, horizontal scroll). Tabs: **General · Job · Contact · Payment · Attendance · Tax Info · Payroll**. The active tab is a **dark pill** (`#16172A`, white text, shadow `0 8px 18px -8px rgba(22,23,42,0.5)`); idle tabs `#6F6A85`, hover `#16172A`. Clicking sets `edTab`.

---

## 4. Section card (shared shell)

Every tab's content is one or more **section cards**: white, radius 20, **card shadow**, `padding 22px 24px`, `riseIn` staggered.
- **Header:** a 34px tinted **icon chip** + title 15/800 + optional subtitle 11.5 `#9A95AE`; a right-aligned **edit pencil** button (ghost, `#F5F1FF`/`#7C4DFF`) toggles the fields editable.
- **Field grid:** `repeat(3,1fr); gap:16px 22px` (responsive to 2 where noted). Each field = label 12/600 `#44405C` + a read-only-styled **input/select** (`#FBFAFE` fill, `border:1px solid #EBE8F2`, radius 11, 13px). Selects show a chevron; editing flips fill to white + violet focus ring.

---

## 5. Per-tab content

**General** — two cards:
- **Personal Details** (violet user icon): Employee ID, Status (select), First / Middle / Last name, Gender (select), Salutation, Date of birth, Role (select), SSN.
- **Company Details** (teal building icon): Company, Department (select), Designation, Report-to (select), Employee Type (select), Work Phone, Work Email.

**Job** — cards built from a Job set:
- **Hiring Info** (violet check-badge): Confirmation date, Offer date, Notice day, Contract end date.
- **Termination** (rose): Terminate date, Last date worked, Terminate type, Termination description.

**Contact** — 
- **Contact** (violet phone): Phone number, Home phone, Preferred email.
- **Address** (teal pin): Address line, State (select), City, Zip; a "mailing same as" note.
- **Emergency Contact** (amber): Contact name, Relationship, Emergency phone.

**Payment** —
- **Payment Info** (violet card): Payment method (select) + a secure-bank-details note strip.

**Attendance** —
- **Attendance Info** (teal clock): Attendance device ID, Holiday calendar (select), Shift (select).

**Tax Info** — two cards (US-compliant):
- **State Withholding**: State, Marital status, Allowances, Additional withholding, Works-in-state, Exempt — plus a "W-4 missing" status chip.
- **Federal W-4**: Which W-4, Withholding status (Step 1c), Multiple jobs (2c), Step-3 dependents (children + others) with an **auto-calc Step-3 total** (read-only violet, `$2,000/child + $500/other`), Step 4a/b/c.

**Payroll** — a control bar (Pay schedule + **Salary/Hourly** segmented toggle + OT/Holiday/Bonus flags) then add-able tables:
- **Earning** (Pay type / Description / Recurring amount), **Deductions & Contributions** (DC / Employee / Tax option / Company), **Garnishment** (type / description / amount / max %). Each: a bordered table (`#FBFAFE` head strip, uppercase 10/800 column heads), `popIn` rows with selects/inputs + a red delete, an **Add** pill, and Save/Cancel when populated.

---

## 6. Actions & functionality

| Action | Behavior |
|---|---|
| Click tab | switch `edTab`; section cards re-render + `riseIn` |
| Edit pencil | flip that section's fields editable (fill white, focus ring) |
| Status pill chevron | change employment status |
| Action ▾ | employee actions menu |
| Payroll Salary/Hourly | swap the pay field set |
| Add / delete row | manage Earning / Deduction / Garnishment tables |
| Step-3 dependents | auto-computes the W-4 Step-3 credit total |
| Sticky topbar / header / card / tabs | stay in view while content scrolls |

---

## 7. Color usage

| Element | Color |
|---|---|
| Values | `#16172A` · labels `#44405C` · muted `#9A95AE` |
| Primary / active tab fill / icon chips | `#7C4DFF` on `#EEE9FF`; active tab `#16172A` |
| Profile banner / avatar ring | `linear-gradient(135deg,#7C4DFF,#A78BFF)` / 4px `#FFFFFF` |
| ACTIVE pill | `#137A57` on `#DEF5E9` |
| Section icon chips | violet `#EEE9FF` · teal `#E0F2F7` · amber `#FDF2DE` · rose `#FCE7F0` |
| Read-only fields | `#FBFAFE` fill, `#EBE8F2` border; edit → white + `#7C4DFF` focus + `0 0 0 3px #EEE9FF` |
| W-4 Step-3 total | `#5B3BC4` on `#F5F1FF` · "W-4 missing" `#D2483E` on `#FCE8E8` |
| Action button | `#16172A` (hover `#2A2440`); Add pill `#7C4DFF` on `#FFFFFF`/`#DECFFF` |
| Delete hover | `#D2483E` on `#FCE8E8` |
| Canvas / card | `#F5F3FB` / `#FFFFFF` |

---

## 8. Typography & spacing

- **Plus Jakarta Sans.** Page header 21/800; profile name 19/800; section title 15/800; tab 13/700; field labels 12/600; inputs 13; table column heads 10/800 uppercase `0.05em`; micro-labels 10.5. `tabular-nums` on IDs, dates, money, SSN.
- Page grid `330px minmax(0,1fr); gap:18px; align-items:start`. Field grids `repeat(3,1fr); gap:16px 22px`. Cards radius 20 (profile 22); inputs 11; icon chip 34px; avatar 84px; tab bar radius 20. Sticky offsets: topbar `top:0`, header below it, profile card + tabs `top:124px`.

---

## 9. Motion

- **Entrances:** profile card `riseIn 0.4s 0.04s`; tab bar `0.05s`; each section card `riseIn 0.4s` staggered; table rows `popIn 0.18s`.
- **Tab switch:** content re-renders with `riseIn`.
- **Edit toggle / focus:** field border + fill transition `0.15s`.
- **Sticky:** topbar/header/card/tabs pin with gradient fade.
- **Icons:** inline SVG, `stroke-width:1.8–2`, round caps, 14–17px.

---

## 10. Paste-ready prompt

> Build an **Employee Detail** page in the Violet Suite style — a two-pane profile (grid `330px minmax(0,1fr); gap:18px;
> align-items:start`). Sticky topbar (search + account, gradient-fade) + a sticky "[‹] Detail Employee" header below it.
> **Left sticky profile card** (white, radius 22): a `linear-gradient(135deg,#7C4DFF,#A78BFF)` banner with glow orb, an 84px
> avatar (4px white ring) overlapping it, name 19/800 + role + a glowing green **ACTIVE** pill, **email/phone contact tiles**
> (violet/green icon chips on `#FBFAFE`), **Department/Office/Line-manager** icon-tile rows with chevrons, and a dark **Action
> ▾** button. **Right detail column**: a sticky white **tab pill-bar** (General · Job · Contact · Payment · Attendance · Tax
> Info · Payroll; active = dark pill `#16172A`), then per-tab **section cards** (white, radius 20, a 34px tinted icon chip +
> title + subtitle + an edit-pencil that makes fields editable; field grid `repeat(3,1fr); gap:16px 22px` of read-only-styled
> inputs/selects — `#FBFAFE` fill, `#EBE8F2` border, focus `#7C4DFF` + `0 0 0 3px #EEE9FF`). **General** = Personal Details +
> Company Details; **Job** = Hiring Info + Termination; **Contact** = Contact + Address + Emergency Contact; **Payment** =
> Payment Info; **Attendance** = device/holiday/shift; **Tax Info** = State Withholding + Federal W-4 (with an auto-calc Step-3
> dependents total `$2,000/child + $500/other` in a read-only violet field and a "W-4 missing" chip); **Payroll** = a pay
> schedule + Salary/Hourly toggle + OT/Holiday/Bonus flags, plus add-able **Earning / Deductions & Contributions /
> Garnishment** tables (`#FBFAFE` head strip, `popIn` rows, Add pill, Save/Cancel). Sticky topbar/header/card/tabs pin while
> content scrolls. Plus Jakarta Sans, tabular figures, one violet accent, springy `popIn`/`riseIn` motion.
