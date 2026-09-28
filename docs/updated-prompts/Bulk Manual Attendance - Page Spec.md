# Bulk Manual Attendance — Page Spec

Reproducible spec for the **Bulk Manual Attendance** page in the Violet Suite — a fast, in-layout screen where an
admin marks the whole team's attendance for a chosen day in one pass (status + in/out times + note). Inline-style
friendly. Pairs with `Violet Suite - Design Spec.md`, `Attendance List & Bulk - Page Spec.md`.

---

## 0. Purpose & brief

> Mark every employee for a day at speed: a live summary, a control panel (date · "mark everyone" presets · quick-fill
> times & note), and a per-employee table with one-tap **P / A / L / H / O** marks, time inputs, and notes — with a
> running % progress bar. One violet accent, tabular figures, `riseIn`/`popIn` motion. Opens from the Attendance page's
> "Bulk attendance" button (`pageE:'attbulk'`); sidebar/topbar stay.

---

## 1. Page anatomy

```
Header        [‹back] icon tile  "Bulk attendance" + subtitle ·spacer· "{n} of {m} marked" chip
Summary       5 mini cards — Present · Absent · Late · Half day · Holiday (live counts)
Control panel  gradient header: date-tile + date label + picker + "Mark everyone" presets + Clear
               quick-fill row: In · Out · Note · Apply(to all / N selected)
Table          progress bar · select-all + per-row P/A/L/H/O + in/out + note (horizontal scroll)
Footer         "{marked} · {date}" ·spacer· Cancel · Save attendance
```

In-layout full page. Sections `riseIn` staggered.

---

## 2. Header

- **Row** (`gap:13px`, `riseIn`): a 36px glass **back arrow** (→ Attendance), a violet gradient **calendar icon tile**, H1 "Bulk attendance" 26/800 + sub "Mark the whole team for a day in one pass", spacer, and a violet **"{n} of {m} marked"** count chip.

---

## 3. Summary strip

`grid-template-columns: repeat(5,1fr); gap:12px`. Five mini cards (radius 14): a tall **colored bar** (10×34px) + value (21/800 tabular) + label — Present `#137A57`, Absent `#D2483E`, Late `#B97608`, Half day `#0E7490`, Holiday `#7C4DFF`. Counts update live as you mark.

---

## 4. Control panel card

White card radius 20, overflow hidden, two zones:
- **Gradient header** (`linear-gradient(120deg,#F4F0FF,#FBFAFF)`, bottom hairline): a 44px violet gradient **date-tile** (month abbr over day number), an "Attendance date" eyebrow + the full **weekday, D Month YYYY** label, and a **date picker**; on the right, "Mark everyone" + three **preset pills** (All present green / All absent red / All holiday violet, dot + label) and a **Clear** trash pill.
- **Quick-fill row** (white): a teal clock icon chip + "Quick fill", a divider, **In** + **Out** time inputs, a **Note for everyone** text field, and a violet **Apply** button whose label is **"Apply to all"** or **"Apply to N selected"** depending on row selection.

---

## 5. Per-employee table

White card radius 20, **horizontal scroll** with an inner `min-width:760px` (so the Note column is always reachable).
- A top **progress bar** (4px, violet gradient fill = % marked).
- **Header strip** (`#FBFAFE`): a **select-all checkbox** + "Employee" · "Status · P / A / L / H / O" · "Check in" · "Check out" · "Note / remarks". Columns `minmax(150px,1.2fr) 248px 96px 96px minmax(130px,1fr); gap:10px`.
- **Rows** (`popIn` staggered; tinted violet when marked): a per-row checkbox + gradient avatar + name + shift sub; a **P / A / L / H / O button group** (42×38px each — Present green, Absent red, Late amber, Half day teal, Holiday violet; selected fills its color, others are soft tints; tapping auto-fills that status's default in/out times); **Check in / Check out** `type=time` inputs (disabled + dimmed when Absent/Holiday); and a **Note** input (placeholder switches to "Reason (optional)" for off-days).
- **Footer:** "{n} of {m} marked · {date}", spacer, **Cancel** (glass) + violet **Save attendance** (check icon).

---

## 6. Actions & functionality

| Action | Behavior |
|---|---|
| Date tile / picker | choose the day being marked (label + tile update) |
| Preset pills | mark everyone Present / Absent / Holiday at once |
| Clear | wipe all marks + times |
| Quick-fill Apply | push In/Out/Note to all rows, or only selected rows |
| Select-all / row checkbox | scope the quick-fill |
| P/A/L/H/O button | set that row's status + auto-fill default times |
| In / Out / Note | per-row edits (times disabled for absent/holiday) |
| Progress bar + summary | recompute live as rows are marked |
| Save attendance | persist + return to Attendance list |

---

## 7. Color usage

| Element | Color |
|---|---|
| Values | `#16172A` · labels `#44405C` · muted `#9A95AE` |
| Present | `#137A57` on `#DEF5E9` · Absent `#D2483E` on `#FCE8E8` · Late `#B97608` on `#FDF2DE` · Half day `#0E7490` on `#E0F2F7` · Holiday/primary `#7C4DFF` on `#EEE9FF` |
| Icon tile / date-tile / Apply / Save | `linear-gradient(140deg,#7C4DFF,#A78BFF)` / `#7C4DFF` (hover `#8B5CF6`) |
| Panel header | `linear-gradient(120deg,#F4F0FF,#FBFAFF)` |
| Progress fill | `linear-gradient(90deg,#A78BFF,#7C4DFF)` |
| Clear hover | `#D2483E` border/text |
| Inputs | border `#D8D2EC`; focus `#7C4DFF` + `0 0 0 3px #EEE9FF`; disabled opacity 0.4 |
| Glass back / Cancel | `rgba(255,255,255,0.62)` + blur / white + `#D8D2EC` |
| Card / strip | `#FFFFFF` / `#FBFAFE` |

---

## 8. Typography & spacing

- **Plus Jakarta Sans.** H1 26/800; date-tile day 17/800; summary value 21/800; column micro-headers 10.5/800 uppercase `0.07em`; row name 13.5/700; quick-mark letters 14/800; inputs 12/600. `tabular-nums` on all times, counts, the date.
- Summary grid `repeat(5,1fr); gap:12px`. Table `min-width:760px`; columns `minmax(150px,1.2fr) 248px 96px 96px minmax(130px,1fr); gap:10px`; quick-mark buttons 42×38px (radius 11). Cards radius 20 (summary 14, pills 999); date-tile 44px; avatar 36–38px; back/icon tile 36px; progress bar 4px.

---

## 9. Motion

- **Entrances:** header `riseIn 0.3s`; summary + control panel + table `riseIn 0.4s` staggered; rows `popIn 0.22s ease {i*0.03}s`.
- **Marking:** quick-mark buttons + selection transition `0.15s`; rows tint when marked; **progress bar `width 0.35s ease`**; summary counts recompute live.
- **Buttons:** preset pills hover lift + brightness; Apply/Save hover background shift.
- **Icons:** inline SVG, `stroke-width:1.9–2.2`, round caps, 12–17px.

---

## 10. Paste-ready prompt

> Build a **Bulk Manual Attendance** page in the Violet Suite style — an in-layout full page (sidebar/topbar stay) to mark the
> whole team for one day. Header: glass back arrow + violet gradient calendar icon tile + H1 "Bulk attendance" 26/800
> `#16172A` + "Mark the whole team for a day in one pass" + a violet **"{n} of {m} marked"** chip. A **summary strip**
> `repeat(5,1fr); gap:12px` — five mini cards (Present green / Absent red / Late amber / Half day teal / Holiday violet) with a
> tall color bar + live count. A **control panel card** (radius 20): a `linear-gradient(120deg,#F4F0FF,#FBFAFF)` header with a
> 44px violet **date-tile** (month abbr over day), the full "Weekday, D Month YYYY" label + a date picker, and on the right
> "Mark everyone" + three **preset pills** (All present / absent / holiday) + a Clear trash pill; then a white **Quick fill**
> row — teal clock chip, In + Out time inputs, a "Note for everyone" field, and a violet **Apply** button reading "Apply to
> all" or "Apply to N selected". A **per-employee table** (horizontal scroll, inner `min-width:760px`): a top violet **progress
> bar** (% marked), a `#FBFAFE` header with select-all + Employee / Status (P/A/L/H/O) / Check in / Check out / Note; rows =
> per-row checkbox + gradient avatar + name + shift, a **P/A/L/H/O button group** (42×38px, selected fills its status color and
> auto-fills default in/out times), Check in/out `type=time` inputs (disabled + dimmed for Absent/Holiday), and a Note input
> (placeholder "Reason (optional)" for off-days). Footer: "{marked} · {date}" + Cancel + violet **Save attendance**. Marking
> recomputes the summary + progress live. Plus Jakarta Sans, tabular figures, one violet accent, springy `popIn`/`riseIn`
> motion.
