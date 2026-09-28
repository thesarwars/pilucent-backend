# Workspace Switcher (Multi-Company) — Page Spec

Reproducible spec for the **Workspace Switcher** — the standalone pre-app screen where a user signs in, picks one of
their companies, and lands in the redesigned Balanzify layout. Three full-screen states (Login → Company picker →
Entering) plus an **Add company modal**. Dark-canvas brand shell, Violet Suite accent. Inline-style friendly.

---

## 0. Purpose & brief

> One login, many sets of books. A split-screen **login**, a **company picker** with search + role filters + pinned/all
> grids, an animated **entering** hand-off, and an **Add a company** modal (Create new / Join with code / Sign in &
> link). Soft violet canvas, glassy cards, `riseIn`/`popIn`/`floatGlow`/`shimmer`/`barFill` motion.

---

## 1. Shell & canvas

- `body { font-family:'Plus Jakarta Sans'; background:#0E0B1A; }`. Root wrapper `min-height:100vh; position:relative; overflow:hidden` with a layered light wash: `radial-gradient(1100px 600px at 82% -10%, #ECE5FB, transparent 60%), radial-gradient(820px 560px at 4% 110%, #F1ECFB, transparent 55%), #F5F3FB`.
- Two floating **glow orbs**: 460px violet `rgba(124,77,255,0.28)` top-right (`floatGlow 11s`), 360px cyan `rgba(34,211,238,0.12)` bottom-left (`floatGlow 13s`).
- **Keyframes:** `riseIn` (10px up + fade), `popIn` (scale .96→1), `floatGlow` (drift + scale), `barFill` (4%→100% width), `shimmer` (bg-position −200%→200%).
- One state visible at a time via `sc-if` on `screen` = `login` / `picker` / `entering`; the Add modal overlays the picker.

---

## 2. State A — Login (split screen)

`grid-template-columns: 1fr 1fr; min-height:100vh; popIn 0.4s`.
- **Left brand panel** — `linear-gradient(165deg,#241B3D,#45357C 60%,#5B46A0 115%)`, `padding 52px 56px`: a 38px violet gradient **logo tile** (stacked-layers SVG) + "Balanzify" 19/800 white; a centered block with a "Multi-company workspace" pill (violet tint, green dot), an `H1` "One login. Every set of books." 42/800 white (`-0.035em`), a 15px muted paragraph, and **three feature rows** (30px glass icon chip + 13.5px text); a footer trust line ("SOC 2 Type II · Bank-grade encryption · US payroll ready").
- **Right form card** — centered, `max-width:396px`, white, radius 22, shadow `0 40px 90px -30px rgba(0,0,0,0.6)`, `padding 34px`, `riseIn`: "Sign in" 21/800 + subtitle; **Google + Apple** SSO buttons (white, `#E2DDF0` border, brand SVGs); an "or" divider; **Work email** + **Password** inputs (focus `#7C4DFF` + `0 0 0 3px #EEE9FF`) with a "Forgot?" link; a "Keep me signed in" checkbox; a full-width violet **Sign in** button (glow) → goes to picker; a "Create account" footer link.

---

## 3. State B — Company picker

`min-height:100vh; flex column; popIn 0.4s`.
- **Top bar** (`padding 22px 40px`): 34px logo tile + "Balanzify" 17/800; spacer; an **account pill** (white, radius 999, `#ECE9F4` border) — 30px orange gradient avatar "AO" + name + email.
- **Centered column** `max-width:940px`:
  - **Greeting** block (`riseIn`): `H1` "Good morning, Amara" 32/800 + sub "{N} companies · {owned} you own, {managed} you manage".
  - **Search + Add row**: a search input (magnifier, "Search companies, EIN or role", radius 13, focus violet) + a glassy **Add company** button (+ icon) opening the modal.
  - **Role filter pills**: All / Owner / Accountant / Admin — each a pill with a count badge; selected = solid violet (`#7C4DFF`, white text, translucent count); idle = white + `#E2DDF0` border.
  - **Pinned section** (if any): a gold star + "PINNED" micro-header, then a **2-col card grid** (`.wsgrid`, `gap:14px`).
  - **All companies / Results** section: list icon + label (switches to "Results" when filtering), then the 2-col grid of remaining cards.
  - **Empty state** (no matches): dashed-border white card, "No companies match your search" + hint.

### Company card (`.wscard`)
`background:rgba(255,255,255,0.97); border:1px solid rgba(255,255,255,0.5); border-radius:16px; padding:16px; cursor:pointer`; hover `translateY(-3px)` + shadow `0 22px 44px -20px rgba(0,0,0,0.55)`.
- Top row: a **46px gradient initials tile** (per-company `linear-gradient(140deg,…)`, inner white ring); name 14.5/800 (ellipsis) + a **role badge** (Owner green `#137A57`/`#DEF5E9`, Accountant violet `#5B3BC4`/`#EEE9FF`, Admin teal `#0E7490`/`#E0F2F7`, Viewer grey `#6F6A85`/`#F0EEF6`); a "{type} · EIN {ein}" sub line; and a **pin star button** (filled gold `#F5B22E` on `#FDF2DE` when pinned, else outline `#C9C4D6` on `#F4F2FA`; hover `#FDF2DE`).
- Footer (hairline-top): a "{last opened}" timestamp + spacer + a violet **Open →** affordance. Clicking the card → Entering state.

---

## 4. State C — Entering (hand-off)

Centered, `popIn 0.3s`. An **86px rounded gradient tile** (24px radius) with the company initials + a diagonal **shimmer** sweep (`shimmer 1.4s`); the company name 21/800 + "Preparing your books & securing your session"; a 230px track with a violet **progress fill** (`barFill 1.8s`). After ~1.9s it navigates the top window to `Balanzify Redesign.dc.html` (the main app).

---

## 5. Add a company modal

- **Scrim:** `position:fixed; inset:0; z-index:100; background:rgba(14,11,26,0.6); backdrop-filter:blur(4px)`, `popIn 0.2s`. Click to close.
- **Dialog:** centered (`left/top:50%; translate(-50%,-50%)`), `z-index:110; width:420px; max-width:calc(100vw-32px)`, white, radius 22, shadow `0 40px 90px -24px rgba(0,0,0,0.6)`, `padding 24px`, `popIn 0.26s cubic-bezier(0.22,1,0.36,1)`.
- **Header:** 34px violet gradient building icon tile + "Add a company" 15/800 + "Create new, or join with an invite code"; a 30px close button (`#F4F2FA`, hover `#FCE8E8`/`#D2483E`).
- **Option grid** `1fr 1fr; gap:10px`: two selectable tiles — **Create new** (+ icon, violet chip `#EEE9FF`/`#7C4DFF`, "A fresh company file") and **Join with code** (login-arrow icon, teal chip `#E0F2F7`/`#0E7490`, "Use an invite from an owner"); selected tile = `#F8F5FF` + violet border, hover border `#B49AFF`.
- **Conditional fields** (`popIn 0.18s`): Join mode → an **Invite code** input (uppercase, placeholder "BLZ-4F2A-9KQ"); Sign-in mode → an info line + **User ID** + **Password** inputs (to link a company by its own login).
- **CTA:** full-width violet button whose label switches — **Create company** / **Join company** / **Sign in & link** (glow, hover `#8B5CF6`).

---

## 6. Functions & state

| State key | Role |
|---|---|
| `screen` | `login` → `picker` → `entering` |
| `liEmail / liPass / remember` | login form |
| `pickQ` | picker search (name/EIN/role/type) |
| `roleFilter` | All/Owner/Accountant/Admin |
| `pinned{}` | per-company pin map |
| `addOpen / addMode` | modal + Create/Join/Sign-in mode |
| `joinCode / siUser / siPass` | add-company inputs |
| `enterId` | which company is being entered |

| Action | Behavior |
|---|---|
| Sign in | `screen → picker` |
| Search / role pill | live-filter the company grids |
| Pin star | toggle company into the Pinned section |
| Open card | `screen → entering`, then navigate to the app after ~1.9s |
| Add company | open modal; pick Create/Join/Sign-in; CTA label adapts |

---

## 7. Color palette

| Element | Color |
|---|---|
| Body / brand panel | `#0E0B1A` / `linear-gradient(165deg,#241B3D,#45357C,#5B46A0)` |
| Canvas wash | `#F5F3FB` + lilac radials `#ECE5FB`/`#F1ECFB` |
| Primary / accent | `#7C4DFF` (hover `#8B5CF6`), gradient `linear-gradient(140deg,#7C4DFF,#A78BFF)` |
| Ink | `#16172A` · `#44405C` · `#6F6A85` · `#9A95AE` · `#B8B2C7` |
| Role badges | Owner `#137A57`/`#DEF5E9` · Accountant `#5B3BC4`/`#EEE9FF` · Admin `#0E7490`/`#E0F2F7` · Viewer `#6F6A85`/`#F0EEF6` |
| Pin star | gold `#F5B22E` on `#FDF2DE` (active) / `#C9C4D6` on `#F4F2FA` (idle) |
| Company avatars | per-company `linear-gradient(140deg,…)` (violet, green, cyan, amber, pink, indigo) |
| Glow orbs | `rgba(124,77,255,0.28)` / `rgba(34,211,238,0.12)` |
| Inputs | border `#D8D2EC`/`#E2DDF0`; focus `#7C4DFF` + `0 0 0 3px #EEE9FF` |
| Cards | `rgba(255,255,255,0.97)` (cards) / `#FFFFFF` (panels) |

---

## 8. Typography & dimensions

- **Plus Jakarta Sans** 400–800. Login H1 42/800 (`-0.035em`); picker H1 32/800; brand logo 17–19/800; card title 14.5/800; sign-in heading 21/800; entering name 21/800; section micro-headers 11.5/800 uppercase `0.08em`; body 13–15; labels 12/600; badges 10/800. `tabular-nums` not required (few raw numbers) but EINs read mono-aligned.
- **Sizes:** brand panel `padding 52px 56px`; login card `max-width:396px`, radius 22; picker column `max-width:940px`; card grid 2-col `gap:14px`; cards radius 16, `padding 16px`; avatar tiles 46px (radius 13); pin button 28px; account avatar 30px; logo tiles 34–38px; modal 420px; entering tile 86px (radius 24); progress track 230×5px.

---

## 9. Motion

- **State transitions:** each screen `popIn 0.4s`; login card `riseIn 0.45s 0.08s`; greeting/search/filters `riseIn` staggered 0.05/0.1/0.12s.
- **Cards:** hover lift + shadow `0.16s`.
- **Glow orbs:** `floatGlow 11s / 13s ease-in-out infinite`.
- **Entering:** tile `popIn 0.5s spring`, **shimmer** sweep `1.4s linear infinite`, **barFill** `1.8s cubic-bezier(0.5,0,0.3,1)`.
- **Modal:** scrim `popIn 0.2s`, dialog `popIn 0.26s spring`, conditional fields `popIn 0.18s`.
- **Icons:** inline SVG, `stroke-width:1.6–2.4`, round caps, 13–20px.

---

## 10. Paste-ready prompt

> Build a **Workspace Switcher** (multi-company pre-app) in the Violet Suite style — three full-screen states over a soft
> violet canvas (`#F5F3FB` + lilac radials, two floating glow orbs) with one accent `#7C4DFF`. **Login**: a split screen —
> left a dark brand panel (`linear-gradient(165deg,#241B3D,#45357C,#5B46A0)`) with logo, a "Multi-company workspace" pill, an
> H1 "One login. Every set of books." 42/800, and three feature rows; right a white card (`max-width:396px`, radius 22) with
> Google/Apple SSO, Work email + Password inputs, a "Keep me signed in" checkbox, and a violet **Sign in** button → picker.
> **Company picker**: a top bar (logo + account pill "AO · Amara Osei"), a centered 940px column with an H1 "Good morning,
> Amara" + "{N} companies · {owned} you own, {managed} you manage", a **search** ("Search companies, EIN or role") + glassy
> **Add company** button, **role filter pills** (All/Owner/Accountant/Admin with counts, selected solid violet), and a
> **PINNED** + **All companies** 2-col card grid. Each **company card** (`rgba(255,255,255,0.97)`, radius 16, hover lift): a
> 46px gradient initials tile, name + a **role badge** (Owner green / Accountant violet / Admin teal / Viewer grey), a "{type}
> · EIN {ein}" sub, a **pin star** (gold when pinned), and a footer "{last opened}" + violet **Open →**; clicking goes to the
> Entering state. **Entering**: an 86px gradient initials tile with a **shimmer** sweep, the company name, and a violet
> **barFill** progress bar, then navigate to the app after ~1.9s. **Add a company modal** (420px, blurred scrim, `popIn`):
> header + two option tiles (**Create new** violet / **Join with code** teal, selected `#F8F5FF` violet border), conditional
> **Invite code** or **User ID + Password** fields, and a violet CTA whose label switches (Create company / Join company /
> Sign in & link). Plus Jakarta Sans; inputs focus `#7C4DFF` + `0 0 0 3px #EEE9FF`; `riseIn`/`popIn`/`floatGlow`/`shimmer`/
> `barFill` motion.
