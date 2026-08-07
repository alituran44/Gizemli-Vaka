---
name: Mobile API layer (api.py)
description: How the token-based mobile REST API is wired alongside the session-based web app, and the circular-import trap to avoid.
---

# Mobile JSON API (/api/v1)

A native (Swift/Kotlin) app talks to the platform via `api.py`, a token (JWT)
based REST blueprint added *next to* the existing cookie/session web app. It is
registered at the very end of `main.py` via `from api import register_api; register_api(app)`.

## Circular-import trap (important)
`main.py` is launched as `python main.py`, so its module name is `__main__`.
If `api.py` does a top-level `import main` / `from main import ...`, then when
`main.py` reaches `register_api`, Python re-executes `main.py` as a *separate*
`main` module (re-running DB init, file sync, then hitting `from api import ...`
again) → `ImportError: partially initialized module 'api'` (circular import).

**Fix / rule:** `api.py` must NOT import `main` at module load. Declare the
needed objects (db, models, helpers) as module-level `None` placeholders, then
inside `register_api(flask_app)` bind them from the already-running module via
`sys.modules.get(flask_app.import_name) or sys.modules.get('main') or sys.modules.get('__main__')`.
Route handlers reference these as globals at request time, so late binding is fine.
**Why:** any sibling module that needs main's globals hits this whenever the app
is run as a script rather than imported.

## Auth & security invariants
- JWT signed with `os.environ.get('API_JWT_SECRET') or app.secret_key` (the web
  secret is hardcoded; setting API_JWT_SECRET decouples API tokens without
  logging out web sessions). Token types: `access`, `refresh`, `payment_bridge`.
- Google native login: app sends `id_token`; server verifies via Google
  `tokeninfo`, checks `email_verified` and `aud` against GOOGLE_OAUTH_CLIENT_ID
  (plus optional comma-list env `API_GOOGLE_CLIENT_IDS` for separate iOS/Android
  client IDs).
- **Every gameplay/paid endpoint must enforce `user_owns_case()`** (ownership =
  case_id in user.unlocked_cases OR a paid Purchase). Applies to evidence,
  hints (list + use), report-suspect, report-text. Missing this is a paid-content
  bypass — was caught in review once, do not regress.
- Evidence content endpoint guards path traversal with realpath + commonpath
  against the uploads root, and personalizes HTML via `personalize_case_html`.

## Payment bridge (mobile 3DS)
No access token in URLs. `POST /payments/checkout` (Bearer) returns a one-time,
5-min `payment_bridge` token; app opens `GET /payments/start?bt=...` in a WebView,
which sets the server session and redirects into the existing web 3D-Secure flow
(`/payment/select/<case_id>`). After payment, app polls `/me/cases`.
**Why:** reuses the working web payment flow; bridge token can't access the API,
limiting leak blast-radius.

## Known non-blocking gap
Score/GameProgress updates are non-atomic (same as the web app) — parallel report
requests could double-apply points. Matches existing web behavior; not fixed here.
