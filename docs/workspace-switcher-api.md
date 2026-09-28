# Workspace Switcher API

Backend contract for the multi-company workspace switcher (login → company
picker → enter → in-app switching, plus the "Add a company" modal).

All paths are under the accounts prefix: **`/api/v1/accounts`**.
Auth: send the JWT as `Authorization: Bearer <access>` unless noted.

## The one rule that matters: token swapping

There are **two kinds of access token**:

| Token | Carries a company? | What it's for |
|-------|--------------------|---------------|
| **Unscoped** | no | issued by login; only used to list/select a company |
| **Scoped**   | yes (`company_id`/`company_uid` claim) | everything else — all tenant data requests |

The flow is: **login gives an unscoped token → the user picks a company →
you exchange it for a scoped token.** Whenever you receive a new
`access`/`refresh` pair from `select-company`, `switch-company`, or
`join-by-code`, **replace whatever you stored.** From that point every request
is automatically scoped to that company (the backend reads the claim, sets the
tenant context, and enforces Row-Level Security). Refreshing a scoped token
keeps the company claim.

---

## 1. Login → render the picker

```
POST /api/v1/accounts/auth/token
{ "email": "amara@example.com", "password": "…" }
```
```jsonc
200 OK
{
  "access": "…",            // UNSCOPED — do not use for app data yet
  "refresh": "…",
  "memberships": [ /* company cards, see schema below */ ],
  "summary": { "total": 3, "owned": 1, "managed": 2 }
}
```
Render the picker from `memberships`; the greeting line uses `summary`
("{total} companies · {owned} you own, {managed} you manage").

### Membership object (company card)
```jsonc
{
  "company_uid": "f0…uuid",
  "name": "Acme Books",
  "legal_name": "Acme Books LLC",
  "type": "CONSTRUCTION",        // Company.kind
  "ein": "12-3456789",           // Company.business_id_no
  "logo": "https://…/logo.png",  // or null
  "roles": ["admin"],            // raw role names
  "role": "Owner",               // badge label: Owner / Accountant / Admin / Viewer
  "is_owner": true,
  "is_pinned": false,
  "last_opened_at": "2026-06-20T11:04:00Z",  // or null
  "avatar_seed": "f0…uuid"       // hash this for the per-company gradient
}
```

## 2. Refresh the picker without re-login (optional)

```
GET /api/v1/accounts/workspace/memberships          (Bearer)
→ { "memberships": [...], "summary": {...} }
```
Use after creating/joining a company to re-render the grid.

## 3. Open a company — the "Entering / securing your session" step

```
POST /api/v1/accounts/workspace/select-company      (Bearer unscoped)
{ "company_uid": "f0…uuid" }
```
```jsonc
200 OK
{
  "access": "…",     // SCOPED — store this, use for all app requests
  "refresh": "…",
  "company": { /* the membership card for the entered company */ }
}
```
→ **Swap your stored tokens for these**, then navigate into the app.
Errors: `400 { "company_uid": ["You do not have access to this company."] }`,
or `400 { "detail": "…not active yet…" }` if the user is a gated employee of
that company.

## 4. Switch company from inside the app

```
POST /api/v1/accounts/workspace/switch-company      (Bearer)
{ "company_uid": "…" }
→ { "access", "refresh", "company" }     // new scoped pair — swap stored tokens
```
Identical to `select-company`; named separately for clarity.

## 5. Pin / unpin

```
POST /api/v1/accounts/workspace/pin-company         (Bearer)
{ "company_uid": "…", "is_pinned": true }   // omit is_pinned to toggle
→ { "company": { …updated card… } }
```

## 6. "Add a company" modal

**Create new**
```
POST /api/v1/we/companies                            (Bearer)
{ "name": "…", "business_id_no": "…", … }
```
Then `GET /workspace/memberships` to refresh, and `select-company` to enter it.

**Join with code**
```
POST /api/v1/accounts/workspace/join-by-code         (Bearer)
{ "code": "BLZ-4F2A-9KQ" }
```
```jsonc
200 OK
{
  "memberships": [...], "summary": {...},   // refreshed list
  "access": "…", "refresh": "…",            // SCOPED to the joined company
  "company": { …card… }
}
```
→ Swap tokens and drop straight into the new workspace. The code must have been
issued to the signed-in user's email; otherwise `400`.

**Sign in & link** — not implemented yet.

---

## Recommended client sequence

```
login
  └─ store unscoped {access, refresh}; render picker from memberships
user clicks a company card
  └─ POST select-company { company_uid }
       └─ store the returned SCOPED {access, refresh}  ← overwrites the unscoped pair
       └─ show "Entering…" then navigate into the app
in-app "switch workspace"
  └─ POST switch-company { company_uid } → store new scoped pair → reload app shell
add company → join with code
  └─ POST join-by-code { code } → store scoped pair → enter workspace
```

## Notes
- Token lifetime is 7 days; refresh via `POST /api/v1/accounts/auth/token/refresh`
  preserves the company claim, so the session stays scoped to the same company.
- Tenant scoping is enforced both in the application layer and (as a backstop)
  by PostgreSQL RLS, keyed off the scoped token's `company_id` claim. A request
  made with an **unscoped** token falls back to app-level behavior, so always
  carry the scoped token after selection.
